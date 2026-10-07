"""
AquaGuard AI — Drift Engine
Member 2 owns: physics-based drift, hindcast, forecast.

CONTRACT §29-48, §77-78
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Physical constants — contract §30, §37, §38
# ---------------------------------------------------------------------------
WIND_FACTOR: float = 0.03          # V_oil = V_current + 0.03 * V_wind  §30
DT_SECONDS: int = 600              # 10-minute timestep                  §38
M_PER_DEG_LAT: float = 111_000.0  # metres per degree latitude          §37
FORECAST_HOURS: int = 5            # fixed MVP forecast duration          §44


# ---------------------------------------------------------------------------
# Direction convention
# ---------------------------------------------------------------------------
# CONTRACT §32: direction convention MUST be verified before use.
#
# The POST /drift endpoint accepts:
#   wind_deg    — meteorological convention: direction the wind blows FROM
#   current_deg — oceanographic convention: direction the flow goes TOWARD
#
# HOWEVER: since no external data provider is connected in the repository
# (empty repo), and the contract requires stopping at vector conversion if
# unresolved (§32), we accept EXPLICIT U/V components directly so the
# convention is unambiguous — the caller provides eastward (U) and
# northward (V) components.
#
# MODE A (preferred): caller supplies wind_U, wind_V, current_U, current_V
# MODE B: caller supplies wind_speed, wind_deg (TOWARD convention verified),
#         current_speed, current_deg (TOWARD convention verified)
#
# The direction convention for MODE B is:
#   TOWARD — i.e. the direction the flow/wind vector points.
#   U = speed * sin(radians(direction))
#   V = speed * cos(radians(direction))
# This matches standard navigation bearing convention (0° = North, 90° = East).
# The contract requires callers to pass `convention: "toward"` to enable MODE B.
# If convention is absent/unknown, MODE B raises EnvironmentConventionError.
# ---------------------------------------------------------------------------


class EnvironmentConventionError(ValueError):
    """Raised when direction convention is unresolved (contract §32)."""
    pass


class GeoreferencingError(ValueError):
    """Raised when geographic centroid is unavailable (contract §51, §72)."""
    pass


class DriftValidationError(ValueError):
    """Raised for invalid drift inputs (contract §51, §77-H)."""
    pass


def _speed_dir_to_uv(speed: float, direction_deg: float, convention: str) -> tuple[float, float]:
    """
    Convert speed + direction to (U=eastward, V=northward) components.

    convention must be "toward" (i.e. direction the vector points).
    Contract §32: never call without verified convention.
    """
    if convention != "toward":
        raise EnvironmentConventionError(
            f"Direction convention '{convention}' is unverified. "
            "Only 'toward' is accepted. Provide explicit U/V components, "
            "or supply convention='toward' if your provider uses TOWARD convention."
        )
    theta = math.radians(direction_deg)
    U = speed * math.sin(theta)
    V = speed * math.cos(theta)
    return U, V

def _finite_float(value, field_name: str) -> float:
    """Convert a value to float and reject NaN/infinite values."""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DriftValidationError(
            f"{field_name} must be a finite numeric value."
        ) from exc

    if not math.isfinite(result):
        raise DriftValidationError(
            f"{field_name} must be a finite numeric value."
        )

    return result

def _resolve_environment(env: dict) -> tuple[float, float]:
    """
    Return (oil_U, oil_V) from the environment dict.

    MODE A:
        wind_U, wind_V, current_U, current_V

    MODE B:
        wind_speed, wind_deg, current_speed, current_deg,
        convention="toward"

    Applies:
        V_oil = V_current + 0.03 * V_wind
    """

    # MODE A — caller already provides U/V components.
    if all(k in env for k in ("wind_U", "wind_V", "current_U", "current_V")):
        wind_U = _finite_float(env["wind_U"], "wind_U")
        wind_V = _finite_float(env["wind_V"], "wind_V")
        current_U = _finite_float(env["current_U"], "current_U")
        current_V = _finite_float(env["current_V"], "current_V")

        oil_U = current_U + WIND_FACTOR * wind_U
        oil_V = current_V + WIND_FACTOR * wind_V

        return oil_U, oil_V

    # MODE B — caller provides speed + direction.
    required_b = (
        "wind_speed",
        "wind_deg",
        "current_speed",
        "current_deg",
    )

    if all(k in env for k in required_b):
        convention = env.get("convention", "unknown")

        wind_speed = _finite_float(env["wind_speed"], "wind_speed")
        wind_deg = _finite_float(env["wind_deg"], "wind_deg")
        current_speed = _finite_float(
            env["current_speed"],
            "current_speed",
        )
        current_deg = _finite_float(
            env["current_deg"],
            "current_deg",
        )

        wind_U, wind_V = _speed_dir_to_uv(
            wind_speed,
            wind_deg,
            convention,
        )

        current_U, current_V = _speed_dir_to_uv(
            current_speed,
            current_deg,
            convention,
        )

        oil_U = current_U + WIND_FACTOR * wind_U
        oil_V = current_V + WIND_FACTOR * wind_V

        return oil_U, oil_V

    raise DriftValidationError(
        "Environment must contain either "
        "(wind_U, wind_V, current_U, current_V) [MODE A] "
        "or "
        "(wind_speed, wind_deg, current_speed, current_deg, convention) "
        "[MODE B]."
    )

def _parse_utc_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 string and require timezone-aware input."""
    dt = datetime.fromisoformat(ts)

    if dt.tzinfo is None:
        raise DriftValidationError(
            "Timestamp must be timezone-aware ISO-8601."
        )

    return dt.astimezone(timezone.utc)


def _dt_to_iso(dt: datetime) -> str:
    """Convert datetime → UTC ISO-8601 string."""
    if dt.tzinfo is None:
        raise DriftValidationError(
            "Datetime must be timezone-aware."
        )
    return dt.astimezone(timezone.utc).isoformat()


def _step_forward(lat: float, lon: float, oil_U: float, oil_V: float, dt: float) -> tuple[float, float]:
    """
    Advance position one timestep forward.
    Contract §37:
      delta_lat = oil_V * dt / 111000
      delta_lon = oil_U * dt / (111000 * cos(lat_rad))
    """
    lat_rad = math.radians(lat)
    new_lat = lat + (oil_V * dt) / M_PER_DEG_LAT
    new_lon = lon + (oil_U * dt) / (M_PER_DEG_LAT * math.cos(lat_rad))
    return new_lat, new_lon


def _step_backward(lat: float, lon: float, oil_U: float, oil_V: float, dt: float) -> tuple[float, float]:
    """
    Rewind position one timestep backward.
    Contract §42:
      new_lat = old_lat - oil_V * dt / 111000
      new_lon = old_lon - oil_U * dt / (111000 * cos(old_lat_rad))
    """
    lat_rad = math.radians(lat)
    new_lat = lat - (oil_V * dt) / M_PER_DEG_LAT
    new_lon = lon - (oil_U * dt) / (M_PER_DEG_LAT * math.cos(lat_rad))
    return new_lat, new_lon


def calculate_hindcast(
    observation_lat: float,
    observation_lon: float,
    observation_timestamp: str,
    environment: dict,
    elapsed_hours: float,
) -> dict:
    """
    Rewind the oil slick from its observed position backward in time.

    Contract §41-43:
      - Starts from observed slick centroid + observation timestamp.
      - Integrates backward using 10-minute timesteps.
      - Partial final step if total duration is not a multiple of 10 min.
      - Returns probable origin lat/lon and origin timestamp.

    Parameters
    ----------
    observation_lat       : geographic latitude of observed slick centroid
    observation_lon       : geographic longitude of observed slick centroid
    observation_timestamp : satellite observation time (UTC ISO-8601)
    environment           : dict with wind/current vectors (see _resolve_environment)
    elapsed_hours         : hindcast / rewind duration in hours (must be >= 0)

    Returns
    -------
    {"origin_lat": float, "origin_lon": float, "origin_timestamp": str}
    Contract §43.
    """
    if elapsed_hours < 0:
        raise DriftValidationError("elapsed_hours must be >= 0.")

    oil_U, oil_V = _resolve_environment(environment)
    obs_dt = _parse_utc_timestamp(observation_timestamp)

    total_seconds = elapsed_hours * 3600.0
    full_steps = int(total_seconds // DT_SECONDS)
    remainder = total_seconds - full_steps * DT_SECONDS  # §39

    lat, lon = observation_lat, observation_lon

    # Full steps
    for _ in range(full_steps):
        lat, lon = _step_backward(lat, lon, oil_U, oil_V, float(DT_SECONDS))

    # Partial final step §39
    if remainder > 0.0:
        lat, lon = _step_backward(lat, lon, oil_U, oil_V, remainder)

    # Origin timestamp §42 final: observation_timestamp - elapsed_hours
    origin_dt = obs_dt - timedelta(seconds=total_seconds)

    return {
        "origin_lat": lat,
        "origin_lon": lon,
        "origin_timestamp": _dt_to_iso(origin_dt),
    }


def calculate_forecast(
    observation_lat: float,
    observation_lon: float,
    observation_timestamp: str,
    environment: dict,
    forecast_hours: int = FORECAST_HOURS,
) -> list[dict]:
    """
    Propagate the oil slick forward from its observed position.

    Contract §44-47:
      - Starts from observed slick centroid + observation timestamp (§45).
      - NOT from hindcast origin (§40, §78).
      - Internal 10-minute timestep.
      - Returns hourly positions for hours 1..forecast_hours.

    Parameters
    ----------
    observation_lat       : geographic latitude of observed slick centroid
    observation_lon       : geographic longitude of observed slick centroid
    observation_timestamp : satellite observation time (UTC ISO-8601)
    environment           : dict with wind/current vectors
    forecast_hours        : number of hours to forecast (MVP = 5)

    Returns
    -------
    List of {"hour": int, "lat": float, "lon": float, "timestamp": str}
    Contract §46.
    """
    if forecast_hours != FORECAST_HOURS:
     raise DriftValidationError(
            f"forecast_hours must be exactly {FORECAST_HOURS} hours for the MVP."
    )

    oil_U, oil_V = _resolve_environment(environment)
    obs_dt = _parse_utc_timestamp(observation_timestamp)

    results: list[dict] = []
    lat, lon = observation_lat, observation_lon
    current_dt = obs_dt

    steps_per_hour = 3600 // DT_SECONDS          # = 6 steps per hour (exact)
    partial_remainder = 3600 % DT_SECONDS         # = 0 (no partial for whole hours)

    for h in range(1, forecast_hours + 1):
        # Integrate from previous position forward one hour
        for _ in range(steps_per_hour):
            lat, lon = _step_forward(lat, lon, oil_U, oil_V, float(DT_SECONDS))
        if partial_remainder > 0:
            lat, lon = _step_forward(lat, lon, oil_U, oil_V, float(partial_remainder))

        # Timestamp for this hour: observation_timestamp + h hours (§47)
        hour_dt = obs_dt + timedelta(hours=h)
        current_dt = hour_dt

        results.append({
            "hour": h,
            "lat": lat,
            "lon": lon,
            "timestamp": _dt_to_iso(hour_dt),
        })

    return results
