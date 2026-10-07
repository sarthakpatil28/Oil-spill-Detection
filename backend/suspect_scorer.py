"""
suspect_scorer.py — Member 3: Multi-Factor Suspect Risk Scoring Engine
=======================================================================
AquaGuard AI — Member 3 integrated with Member 2 backend.

Ranks AIS vessels by likelihood of being responsible for a detected oil spill.

Three weighted factors (project contract §2.4 overrides ZIP defaults):
    1. Proximity       weight=0.40   max radius=20.0 km
    2. SOG drop        weight=0.35   (previous SOG – current SOG, signed, max 8 kn)
    3. COG deviation   weight=0.25   (circular delta, max 45°)

Score formula (0–100):
    proximity_factor = max(0, 1 – distance_km / 20.0)
    sog_factor       = min(max(prev_sog – curr_sog, 0) / 8.0, 1.0)
    cog_factor       = min(circular_delta_cog / 45.0, 1.0)
    score            = 100 × (0.40×proximity_factor + 0.35×sog_factor + 0.25×cog_factor)

Incident-Time Observation Rule:
    For each vessel identity, the observation CLOSEST to origin_timestamp
    (within ±3h) is the "incident record" — NOT simply records[-1].

Month Derivation:
    Month is derived from origin_timestamp, NEVER from AQUAGUARD_AIS_DATE.

Month-Boundary Crossing:
    origin_timestamp ± 3h spanning two months → both months are loaded.

IMO/MMSI Grouping:
    Valid IMO  → group by IMO
    Invalid/missing IMO → group by MMSI (separate identities remain separate)

Return Type:
    list[dict]  (NOT the wrapper SuspectLeaderboardResponse object)
    Each dict keys: rank, imo, mmsi, vessel_name, vessel_type, latitude, longitude,
                    sog_knots, cog_degrees, timestamp, distance_to_origin_km,
                    proximity_km, delta_sog, delta_cog, score, suspect_score_pct,
                    risk_tier, factors

Zero-fabrication guarantee:
    Empty list [] is valid when no candidates match — never fabricate suspects.

NOTE on ZIP's FastAPI router (suspects_router):
    The ZIP's suspect_scorer.py contained a FastAPI APIRouter mounted at:
        GET  /vessels  /api/v1/vessels
        POST /suspects/rank  /api/v1/suspects/rank
        GET  /suspects  /api/v1/suspects
    That router is NOT used here. Member 2's main.py owns all routes.
    suspects_router is NOT defined in this file.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Project-Contract Scoring Parameters
# (Override ZIP defaults: 250km/±6h/0.5-0.3-0.2)
# ---------------------------------------------------------------------------
SPATIAL_RADIUS_KM:      float = 20.0
TEMPORAL_WINDOW_HOURS:  float = 3.0
PROXIMITY_WEIGHT:       float = 0.40
SOG_WEIGHT:             float = 0.35
COG_WEIGHT:             float = 0.25

# Normalisation denominators
_PROXIMITY_DENOM_KM:  float = 20.0   # radius (distance at which proximity_factor = 0)
_SOG_DENOM_KN:        float = 8.0    # SOG drop (kn) that saturates the factor at 1.0
_COG_DENOM_DEG:       float = 45.0   # COG deviation (°) that saturates the factor at 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_utc(ts: str) -> datetime:
    """
    Parse an ISO-8601 or NOAA BaseDateTime string into a UTC-aware datetime.
    Handles: '2025-05-01T14:23:11Z', '2025-05-01 14:23:11', '2025-05-01T14:23:11+00:00'
    """
    ts = ts.strip().replace("Z", "+00:00")
    if "T" not in ts and "+" not in ts and len(ts) >= 16:
        ts = ts + "+00:00"
    ts = ts.replace(" ", "T", 1)
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cog_circular_delta(cog_a: float, cog_b: float) -> float:
    """
    Return the absolute angular difference between two bearings, normalised to [0, 180].
    Uses circular arithmetic to avoid 359°↔1° = 358° error.
    """
    raw = abs(cog_a - cog_b) % 360.0
    return min(raw, 360.0 - raw)


def _risk_tier(score: float) -> str:
    if score >= 80.0:
        return "CRITICAL"
    if score >= 50.0:
        return "HIGH"
    if score >= 25.0:
        return "MEDIUM"
    return "LOW"


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km between two WGS-84 points."""
    R = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _identity_key(vessel: dict[str, Any]) -> str:
    """
    Return the grouping key for a vessel.
    Valid IMO → 'IMO:<imo>'
    Missing/invalid IMO → 'MMSI:<mmsi>'
    Never fabricates a key.
    """
    imo = vessel.get("imo_number")
    if imo is not None and str(imo).strip() not in ("", "0", "None"):
        return f"IMO:{imo}"
    mmsi = vessel.get("mmsi", "")
    return f"MMSI:{mmsi}"


# ---------------------------------------------------------------------------
# Core scoring engine
# ---------------------------------------------------------------------------

def _compute_score(
    distance_km: float,
    prev_sog: float | None,
    curr_sog: float,
    prev_cog: float | None,
    curr_cog: float,
) -> tuple[float, dict[str, float]]:
    """
    Apply the project-contract scoring formula.

    proximity_factor = max(0, 1 – D / 20.0)
    sog_factor       = min(max(prev_sog – curr_sog, 0) / 8.0, 1.0)   [signed drop]
    cog_factor       = min(circular_delta(prev_cog, curr_cog) / 45.0, 1.0)
    score            = 100 × (0.40×prox + 0.35×sog + 0.25×cog)

    When no previous observation exists, sog_factor = cog_factor = 0.0.
    """
    proximity_factor = max(0.0, 1.0 - distance_km / _PROXIMITY_DENOM_KM)

    if prev_sog is not None:
        sog_drop = max(prev_sog - curr_sog, 0.0)   # signed drop only
        sog_factor = min(sog_drop / _SOG_DENOM_KN, 1.0)
    else:
        sog_drop = 0.0
        sog_factor = 0.0

    if prev_cog is not None:
        cog_delta = _cog_circular_delta(prev_cog, curr_cog)
        cog_factor = min(cog_delta / _COG_DENOM_DEG, 1.0)
    else:
        cog_delta = 0.0
        cog_factor = 0.0

    raw_score = 100.0 * (
        PROXIMITY_WEIGHT * proximity_factor
        + SOG_WEIGHT * sog_factor
        + COG_WEIGHT * cog_factor
    )
    score = round(min(100.0, raw_score), 4)

    factors = {
        "proximity":      round(proximity_factor, 4),
        "sog_drop":       round(sog_factor, 4),
        "cog_deviation":  round(cog_factor, 4),
    }
    return score, factors


# ---------------------------------------------------------------------------
# rank_suspect_vessels — internal engine
# ---------------------------------------------------------------------------

def rank_suspect_vessels(
    origin_lat: float,
    origin_lon: float,
    origin_timestamp: str,
    vessels: list[dict[str, Any]],
    spatial_radius_km: float = SPATIAL_RADIUS_KM,
    temporal_window_hours: float = TEMPORAL_WINDOW_HOURS,
) -> list[dict[str, Any]]:
    """
    Rank candidate vessels by their likelihood of causing the spill.

    Parameters
    ----------
    origin_lat, origin_lon : float
        Drift-computed spill origin coordinates.
    origin_timestamp : str
        ISO-8601 UTC timestamp of the spill event.
    vessels : list[dict]
        Flat list of canonical vessel records (from accessais_loader).
    spatial_radius_km : float
        Maximum Haversine distance for eligibility (default: 20.0 km per contract).
    temporal_window_hours : float
        ±window around origin_timestamp for eligibility (default: ±3h per contract).

    Returns
    -------
    list[dict]
        Ranked list (rank 1 = highest score). Empty [] when no candidates.
        Never fabricates suspects.
    """
    try:
        origin_dt = _parse_utc(origin_timestamp)
    except Exception as exc:
        raise ValueError(f"Cannot parse origin_timestamp '{origin_timestamp}': {exc}") from exc

    window_start = origin_dt - timedelta(hours=temporal_window_hours)
    window_end   = origin_dt + timedelta(hours=temporal_window_hours)

    # --- Group by identity (IMO if valid, MMSI fallback) ---
    grouped: dict[str, list[dict[str, Any]]] = {}
    for v in vessels:
        key = _identity_key(v)
        grouped.setdefault(key, []).append(v)

    # Sort each group chronologically
    for key in grouped:
        try:
            grouped[key].sort(key=lambda r: _parse_utc(str(r["timestamp"])))
        except Exception:
            pass

    candidates: list[dict[str, Any]] = []

    for identity_key, records in grouped.items():
        # --- Find all records within the temporal window ---
        in_window: list[tuple[datetime, dict[str, Any]]] = []
        for r in records:
            try:
                r_dt = _parse_utc(str(r["timestamp"]))
                if window_start <= r_dt <= window_end:
                    in_window.append((r_dt, r))
            except Exception:
                continue

        if not in_window:
            continue

        # --- Incident-time observation: closest to origin_timestamp, NOT records[-1] ---
        in_window.sort(key=lambda x: abs((x[0] - origin_dt).total_seconds()))
        incident_dt, incident_rec = in_window[0]

        # --- Spatial gate ---
        try:
            dist_km = _haversine(
                origin_lat, origin_lon,
                float(incident_rec["latitude"]),
                float(incident_rec["longitude"]),
            )
        except (KeyError, TypeError, ValueError):
            continue

        if dist_km > spatial_radius_km:
            continue

        # --- Previous observation (for behavioral delta) ---
        # The immediately preceding chronological record BEFORE incident_dt
        prev_rec = None
        for r in reversed(records):
            try:
                r_dt = _parse_utc(str(r["timestamp"]))
                if r_dt < incident_dt:
                    prev_rec = r
                    break
            except Exception:
                continue

        prev_sog = float(prev_rec["sog_knots"]) if prev_rec else None
        prev_cog = float(prev_rec["cog_degrees"]) if prev_rec else None
        curr_sog = float(incident_rec["sog_knots"])
        curr_cog = float(incident_rec["cog_degrees"])

        # --- Score ---
        score, factors = _compute_score(dist_km, prev_sog, curr_sog, prev_cog, curr_cog)

        # --- Derive output fields from incident record ---
        imo_raw = incident_rec.get("imo_number")
        imo_str = str(imo_raw) if imo_raw is not None else ""
        mmsi_str = str(incident_rec.get("mmsi", ""))

        candidates.append({
            "identity_key":          identity_key,
            "imo":                   imo_str,
            "imo_number":            imo_str,
            "mmsi":                  mmsi_str,
            "vessel_name":           incident_rec.get("vessel_name") or "",
            "vessel_type":           incident_rec.get("vessel_type") or "",
            "latitude":              float(incident_rec["latitude"]),
            "longitude":             float(incident_rec["longitude"]),
            "sog_knots":             curr_sog,
            "cog_degrees":           curr_cog,
            "timestamp":             str(incident_rec["timestamp"]),
            "distance_to_origin_km": round(dist_km, 4),
            "proximity_km":          round(dist_km, 4),
            "delta_sog":             round(curr_sog - (prev_sog or curr_sog), 4),
            "delta_cog":             round(_cog_circular_delta(prev_cog, curr_cog) if prev_cog is not None else 0.0, 4),
            "score":                 score,
            "suspect_score_pct":     score,
            "factors":               factors,
        })

    # --- Sort descending by score ---
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # --- Attach ranks ---
    ranked: list[dict[str, Any]] = []
    for rank, c in enumerate(candidates, start=1):
        ranked.append({
            "rank":       rank,
            "risk_tier":  _risk_tier(c["score"]),
            **c,
        })

    logger.info(
        "rank_suspect_vessels: %d suspects within %.1f km / ±%.1f h of origin (%.4f, %.4f) @ %s",
        len(ranked), spatial_radius_km, temporal_window_hours,
        origin_lat, origin_lon, origin_timestamp,
    )
    return ranked


# ---------------------------------------------------------------------------
# Public API — score_suspects() for Member 2 backend integration
# ---------------------------------------------------------------------------

def score_suspects(
    origin_lat: float,
    origin_lon: float,
    origin_timestamp: str,
) -> list[dict[str, Any]]:
    """
    Public interface called by Member 2 backend (/suspects route).

    Month is derived from origin_timestamp directly (NOT from AQUAGUARD_AIS_DATE).
    Handles month-boundary crossing (window spanning two months → loads both).

    Mode:
        AQUAGUARD_AIS_SOURCE=sample → use data/accessais_sample.csv
        AQUAGUARD_AIS_SOURCE=real  → use NOAA monthly dataset(s)

    Returns
    -------
    list[dict]
        Ranked suspect list. Empty [] when no candidates — NEVER fabricated.

    Raises
    ------
    DataCoverageError
        In real mode when required monthly data is not on disk.
    ConfigurationError
        When environment is misconfigured for the requested mode.
    """
    from accessais_loader import (
        load_accessais_data,
        load_vessels_for_window,
        DataCoverageError,
        ConfigurationError,
        _FALLBACK_CSV,
    )

    source = (os.environ.get("AQUAGUARD_AIS_SOURCE") or "sample").strip().lower()
    logger.info(
        "score_suspects() called — source=%r, origin=(%.4f, %.4f), ts=%s",
        source, origin_lat, origin_lon, origin_timestamp,
    )

    if source == "real":
        # Month derived from origin_timestamp — NOT from AQUAGUARD_AIS_DATE
        vessels = load_vessels_for_window(
            origin_timestamp=origin_timestamp,
            window_hours=TEMPORAL_WINDOW_HOURS,
        )
    else:
        # Sample mode (or unknown source → sample)
        vessels = load_accessais_data(_FALLBACK_CSV)

    return rank_suspect_vessels(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        origin_timestamp=origin_timestamp,
        vessels=vessels,
        spatial_radius_km=SPATIAL_RADIUS_KM,
        temporal_window_hours=TEMPORAL_WINDOW_HOURS,
    )
