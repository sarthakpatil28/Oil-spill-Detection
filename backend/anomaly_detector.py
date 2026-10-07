"""
AquaGuard AI — Anomaly Detector
Member 2 owns: SOG anomaly, COG anomaly, HIGH-severity classification, ROI generation.
Member 3 owns: AIS loading / preparation (ais_loader.py / accessais_loader.py).

CONTRACT §13-18, §76
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Thresholds — contract §13, §14, §15
# ---------------------------------------------------------------------------
SOG_DROP_THRESHOLD_KNOTS: float = 8.0    # §13
COG_CHANGE_THRESHOLD_DEG: float = 45.0   # §14
HIGH_SOG_DROP_MIN: float = 8.0           # §15
HIGH_CURRENT_SOG_MAX: float = 3.0        # §15
HIGH_SHORE_MIN_KM: float = 5.0           # §15


def _compute_sog_drop(previous_sog: float, current_sog: float) -> float:
    """
    SOG drop = previous_sog - current_sog  (signed, not absolute).
    Contract §13: A speed increase is NOT a SOG-drop anomaly.
    """
    return previous_sog - current_sog


def _compute_cog_change(previous_cog: float, current_cog: float) -> float:
    """
    Shortest angular distance on a 360° circle.
    Contract §14: must correctly handle 359->1 = 2° and 1->359 = 2°.

    Formula: abs(((current - previous + 180) % 360) - 180)
    """
    raw = (current_cog - previous_cog + 180.0) % 360.0 - 180.0
    return abs(raw)


def detect_anomaly(
    *,
    previous_sog: float,
    current_sog: float,
    previous_cog: float,
    current_cog: float,
    lat: float,
    lon: float,
    time_utc: str,
    imo: Optional[str],
    mmsi: Optional[str],
    vessel_type: Optional[str],
    distance_to_shore_km: Optional[float],
) -> dict:
    """
    Detect SOG anomaly, COG anomaly, and HIGH-severity for a single
    consecutive vessel record pair.

    Parameters
    ----------
    previous_sog          : SOG of the previous AIS record (knots)
    current_sog           : SOG of the current AIS record (knots)
    previous_cog          : COG of the previous AIS record (degrees)
    current_cog           : COG of the current AIS record (degrees)
    lat / lon             : geographic position of the current AIS record
    time_utc              : ISO-8601 UTC timestamp of the current record
    imo / mmsi            : vessel identifiers (either may be None)
    vessel_type           : AIS vessel type string (may be None)
    distance_to_shore_km  : distance to nearest shore in km (may be None)

    Returns
    -------
    Anomaly dict per contract §18.  ROI is the anomalous vessel position.
    """
    sog_drop = _compute_sog_drop(previous_sog, current_sog)
    cog_change = _compute_cog_change(previous_cog, current_cog)

    # --- individual anomaly flags -------------------------------------------
    sog_anomaly: bool = sog_drop >= SOG_DROP_THRESHOLD_KNOTS         # §13
    cog_anomaly: bool = cog_change >= COG_CHANGE_THRESHOLD_DEG       # §14

    # --- HIGH severity (ALL three conditions required) ----------------------
    # §15: sog_drop >= 8 AND current_sog < 3 AND distance > 5 km
    # §17: if distance_to_shore_km is None → high_severity = False
    if distance_to_shore_km is not None:
        high_severity: bool = (
            sog_drop >= HIGH_SOG_DROP_MIN
            and current_sog < HIGH_CURRENT_SOG_MAX
            and distance_to_shore_km > HIGH_SHORE_MIN_KM
        )
    else:
        high_severity = False

    # --- reasons list -------------------------------------------------------
    reasons: list[str] = []
    if sog_anomaly:
        reasons.append(
            f"SOG drop {sog_drop:.2f} knots "
            f"(≥ {SOG_DROP_THRESHOLD_KNOTS} threshold)"
        )
    if cog_anomaly:
        reasons.append(
            f"COG change {cog_change:.2f}° "
            f"(≥ {COG_CHANGE_THRESHOLD_DEG}° threshold)"
        )
    if high_severity:
        reasons.append(
            f"HIGH severity: SOG drop {sog_drop:.2f} kn, "
            f"current SOG {current_sog:.2f} kn < {HIGH_CURRENT_SOG_MAX} kn, "
            f"shore {distance_to_shore_km:.2f} km > {HIGH_SHORE_MIN_KM} km"
        )

    # --- ROI: anomalous vessel position §18 --------------------------------
    roi = {"lat": lat, "lon": lon}

    return {
        "imo": imo,
        "mmsi": mmsi,
        "vessel_type": vessel_type,
        "lat": lat,
        "lon": lon,
        "time": time_utc,
        "previous_sog_knots": previous_sog,
        "current_sog_knots": current_sog,
        "sog_drop_knots": round(sog_drop, 6),
        "previous_cog_deg": previous_cog,
        "current_cog_deg": current_cog,
        "cog_change_deg": round(cog_change, 6),
        "distance_to_shore_km": distance_to_shore_km,
        "sog_anomaly": sog_anomaly,
        "cog_anomaly": cog_anomaly,
        "high_severity": high_severity,
        "roi": roi,
        "reasons": reasons,
    }


def run_anomaly_detection(vessels_df) -> list[dict]:
    """
    Process a pandas DataFrame of AIS records and return all anomalies.

    Pre-processing (contract §11):
      1. Parse timestamp → timezone-aware UTC
      2. Sort chronologically
      3. Group by vessel
      4. Compare consecutive records from the SAME vessel only

    Vessel identity (contract §12):
      Preferred: IMO  |  Fallback: MMSI

    Parameters
    ----------
    vessels_df : pandas.DataFrame
        Must contain at minimum:
            MMSI, BaseDateTime, LAT, LON, SOG, COG
        Optionally:
            IMO, VesselType, DistanceToShoreKm

    Returns
    -------
    List of anomaly dicts (only records with sog_anomaly OR cog_anomaly).
    """
    import pandas as pd
    import numpy as np

    df = vessels_df.copy()

    # --- 1. Parse timestamp -------------------------------------------------
    df["_ts"] = pd.to_datetime(df["BaseDateTime"], utc=True, errors="coerce")

    # --- 2. Sort chronologically --------------------------------------------
    df.sort_values("_ts", inplace=True)

    # --- Normalise optional columns -----------------------------------------
    if "IMO" not in df.columns:
        df["IMO"] = None
    if "VesselType" not in df.columns:
        df["VesselType"] = None
    if "DistanceToShoreKm" not in df.columns:
        df["DistanceToShoreKm"] = None

    # Replace NaN with None for Python-level checks
    def _to_py(val):
        if val is None:
            return None
        try:
            if math.isnan(float(val)):
                return None
        except (TypeError, ValueError):
            pass
        return val

    anomalies: list[dict] = []

    # --- 3 & 4. Group by vessel; compare consecutive records ----------------
    # §12: group by IMO when available, otherwise fall back to MMSI
    imo_valid = (
        df["IMO"].notna()
        & df["IMO"].astype(str).str.strip().ne("")
    )

    df["_vessel_key"] = df["IMO"].where(imo_valid, df["MMSI"])

    for vessel_key, group in df.groupby("_vessel_key", sort=False, dropna=False):
        group = group.sort_values("_ts").reset_index(drop=True)

        for i in range(1, len(group)):
            prev = group.iloc[i - 1]
            curr = group.iloc[i]

            prev_sog = _to_py(prev.get("SOG"))
            curr_sog = _to_py(curr.get("SOG"))
            prev_cog = _to_py(prev.get("COG"))
            curr_cog = _to_py(curr.get("COG"))

            # Skip if essential values missing
            if any(v is None for v in [prev_sog, curr_sog, prev_cog, curr_cog]):
                continue

            lat = float(curr["LAT"])
            lon = float(curr["LON"])

            ts = curr["_ts"]
            time_utc = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            mmsi_val = _to_py(curr.get("MMSI"))
            mmsi = str(int(mmsi_val)) if mmsi_val is not None and not _is_nan(mmsi_val) else None

            imo_val = _to_py(curr.get("IMO"))
            imo = (
                str(imo_val).strip()
                if imo_val is not None and not _is_nan(imo_val) and str(imo_val).strip() != ""
                else None
            )
            vessel_type = _to_py(curr.get("VesselType"))
            dist = _to_py(curr.get("DistanceToShoreKm"))
            if dist is not None:
                try:
                    dist = float(dist)
                except (TypeError, ValueError):
                    dist = None

            result = detect_anomaly(
                previous_sog=float(prev_sog),
                current_sog=float(curr_sog),
                previous_cog=float(prev_cog),
                current_cog=float(curr_cog),
                lat=lat,
                lon=lon,
                time_utc=time_utc,
                imo=imo,
                mmsi=mmsi,
                vessel_type=str(vessel_type) if vessel_type is not None else None,
                distance_to_shore_km=dist,
            )

            # §55: produce ROI for SOG anomaly OR COG anomaly
            if result["sog_anomaly"] or result["cog_anomaly"]:
                anomalies.append(result)

    return anomalies


def _is_nan(val) -> bool:
    """Return True if val is a float NaN."""
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return False
