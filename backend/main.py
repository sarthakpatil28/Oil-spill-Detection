"""
AquaGuard AI — FastAPI Backend
Member 2 owns: REST orchestration, anomaly detection, drift engine, integration bridges.

CONTRACT §54-72, §80
"""

from __future__ import annotations

import importlib
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Ensure backend/ is on the path when launched from the project root
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator

from anomaly_detector import run_anomaly_detection
from drift_engine import (
    FORECAST_HOURS,
    WIND_FACTOR,
    DT_SECONDS,
    DriftValidationError,
    EnvironmentConventionError,
    GeoreferencingError,
    calculate_hindcast,
    calculate_forecast,
)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="AquaGuard AI — Backend",
    version="1.0.0",
    description="Marine Oil Spill Detection, Drift Prediction & AIS Vessel Attribution",
)

# CORS — §63: React communicates through HTTP/JSON
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Member 1 Static Files & Vision Router Integration
# ---------------------------------------------------------------------------
_STATIC_DIR = os.path.join(_BACKEND_DIR, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

try:
    from vision_api import router as vision_router
    app.include_router(vision_router)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Runtime state — §68
# ---------------------------------------------------------------------------
latest_vessels: Optional[list] = None
latest_anomalies: Optional[list] = None
latest_segment: Optional[dict] = None   # populated by POST /segment
latest_drift: Optional[dict] = None     # populated by POST /drift
latest_origin: Optional[dict] = None    # from latest_drift
latest_forecast: Optional[list] = None  # from latest_drift
latest_suspects: Optional[list] = None
latest_alert_status: Optional[dict] = None


# ---------------------------------------------------------------------------
# Member-3 AIS Loader adapter — §54, §55, §84 INTEGRATION 1
# ---------------------------------------------------------------------------
def _load_ais() -> list[dict]:
    """
    Attempt to import Member-3's AIS loader.

    Priority:
      1. backend/accessais_loader.py  (AccessAIS-specific)
      2. backend/ais_loader.py        (generic)

    If neither exists → HTTPException 503 (dependency failure, §72).
    Both modules are expected to expose a callable load_vessels() → list[dict]
    or load_vessels() → pandas.DataFrame.
    """
    for module_name in ("accessais_loader", "ais_loader"):
        try:
            mod = importlib.import_module(module_name)
            data = mod.load_vessels()
            # Normalise to list of dicts for JSON serialisation
            if hasattr(data, "to_dict"):  # pandas DataFrame
                import pandas as pd
                df = data
                rows = _safe_df_to_list(df)
            else:
                rows = list(data)
            return rows
        except ModuleNotFoundError:
            continue
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"AIS loader ({module_name}) error: {exc}",
            )

    raise HTTPException(
        status_code=503,
        detail=(
            "AIS loader unavailable. "
            "Member 3 must provide accessais_loader.py or ais_loader.py "
            "in the backend/ directory."
        ),
    )


def _load_ais_as_dataframe():
    """
    Return AIS data as a pandas DataFrame for anomaly detection.
    Tries Member-3 modules; falls back to data/accessais_sample.csv.
    """
    import pandas as pd

    for module_name in ("accessais_loader", "ais_loader"):
        try:
            mod = importlib.import_module(module_name)
            data = mod.load_vessels()
            if hasattr(data, "to_dict"):
                return data
            return pd.DataFrame(data)
        except ModuleNotFoundError:
            continue
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"AIS loader ({module_name}) error: {exc}",
            )

    # Fallback: sample CSV in data/ directory
    csv_candidates = [
        os.path.join(_BACKEND_DIR, "..", "data", "accessais_sample.csv"),
        os.path.join(_BACKEND_DIR, "accessais_sample.csv"),
    ]
    for csv_path in csv_candidates:
        csv_path = os.path.normpath(csv_path)
        if os.path.isfile(csv_path):
            try:
                df = pd.read_csv(csv_path)
                return df
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"Failed to read sample CSV {csv_path}: {exc}",
                )

    raise HTTPException(
        status_code=503,
        detail=(
            "AIS data unavailable. "
            "Member 3 must provide accessais_loader.py or ais_loader.py, "
            "or place accessais_sample.csv in the data/ directory."
        ),
    )


# ---------------------------------------------------------------------------
# Member-1 Segmentation adapter — §56, §84 INTEGRATION 5
# ---------------------------------------------------------------------------
def _call_member1_segment(
    roi_lat: float,
    roi_lon: float,
    timestamp: str | datetime,
    raw_image_path: Optional[str] = None,
    thermal_image_path: Optional[str] = None,
) -> dict:
    """
    Call Member 1's segmentation pipeline.

    Expected interface:
        run_segmentation(roi_lat, roi_lon, timestamp) -> dict

    Member 2 normalises the Member-1 result into the internal slick schema.
    """
    ts_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    try:
        mod = importlib.import_module("vision_api")

        import inspect
        kwargs = {}
        if raw_image_path:
            kwargs["raw_image_path"] = raw_image_path
        if thermal_image_path:
            kwargs["thermal_image_path"] = thermal_image_path

        sig = inspect.signature(mod.run_segmentation)
        call_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

        raw_result = mod.run_segmentation(
            roi_lat=roi_lat,
            roi_lon=roi_lon,
            timestamp=ts_str,
            **call_kwargs,
        )

    except ModuleNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Member-1 segmentation unavailable. "
                "Provide vision_api.py with run_segmentation()."
            ),
        )
    except AttributeError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Member-1 segmentation interface mismatch. "
                "vision_api.py must provide "
                "run_segmentation(roi_lat, roi_lon, timestamp)."
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Member-1 segmentation error: {exc}",
        )

    if isinstance(raw_result, dict) and raw_result.get("success") is False:
        err = raw_result.get("error", "VISION_PROCESSING_FAILED")
        status = 422 if err == "NO_SPILL_DETECTED" else 503
        raise HTTPException(
            status_code=status,
            detail=f"Member-1 segmentation failed: {err}",
        )

    # Extract spill data using Member 1 contract (result["spill"])
    spill = raw_result.get("spill") if (isinstance(raw_result, dict) and "spill" in raw_result) else raw_result

    centroid = None
    c_lat = None
    c_lon = None
    if isinstance(spill, dict):
        if "centroid" in spill and isinstance(spill["centroid"], dict):
            c_lat = spill["centroid"].get("lat")
            c_lon = spill["centroid"].get("lon")
        else:
            c_lat = spill.get("centroid_lat")
            c_lon = spill.get("centroid_lon")

    if c_lat is not None and c_lon is not None:
        try:
            centroid_lat = float(c_lat)
            centroid_lon = float(c_lon)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Member-1 centroid lat/lon must be numeric.",
            ) from exc

        if not math.isfinite(centroid_lat) or not math.isfinite(centroid_lon):
            raise HTTPException(
                status_code=400,
                detail="Member-1 centroid lat/lon must be finite.",
            )

        if not -90.0 <= centroid_lat <= 90.0:
            raise HTTPException(
                status_code=400,
                detail="Member-1 centroid latitude must be between -90 and 90.",
            )

        if not -180.0 <= centroid_lon <= 180.0:
            raise HTTPException(
                status_code=400,
                detail="Member-1 centroid longitude must be between -180 and 180.",
            )

        centroid = {
            "lat": centroid_lat,
            "lon": centroid_lon,
        }

    obs_ts = spill.get("observation_timestamp") if isinstance(spill, dict) else None

    if obs_ts is None:
        raise HTTPException(
            status_code=400,
            detail="Member-1 result missing observation_timestamp.",
        )

    polygon = spill.get("polygon") if (isinstance(spill, dict) and "polygon" in spill) else spill.get("slick_polygon")
    area_sq_km = spill.get("area_sq_km") if isinstance(spill, dict) else None
    perimeter_km = spill.get("perimeter_km") if isinstance(spill, dict) else None
    georeferenced = spill.get("georeferenced", centroid is not None) if isinstance(spill, dict) else (centroid is not None)

    return {
        "polygon": polygon,
        "centroid": centroid,
        "area_sq_km": area_sq_km,
        "perimeter_km": perimeter_km,
        "observation_timestamp": obs_ts,
        "georeferenced": georeferenced,
    }


# ---------------------------------------------------------------------------
# Member-3 Suspect Scorer adapter — §57-58, §84 INTEGRATION 7
# ---------------------------------------------------------------------------
def _call_member3_suspects(origin_lat: float, origin_lon: float, origin_timestamp: str) -> list[dict]:
    """
    Call Member 3's historical AIS suspect scorer.

    Expected module: backend/suspect_scorer.py
    Expected callable: score_suspects(origin_lat, origin_lon, origin_timestamp) -> list[dict]

    Member 2 does NOT implement suspect scoring (§58, §16).
    """
    try:
        mod = importlib.import_module("suspect_scorer")
        return mod.score_suspects(origin_lat, origin_lon, origin_timestamp)
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Member-3 suspect scorer unavailable. "
                "Provide suspect_scorer.py with score_suspects(origin_lat, origin_lon, origin_timestamp)."
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Suspect scorer error: {exc}",
        )


# ---------------------------------------------------------------------------
# Member-4 Alert Dispatcher adapter — §60, §84 INTEGRATION 12
# ---------------------------------------------------------------------------
def _call_member4_alert(suspects: list, origin: dict, area_sq_km: Optional[float]) -> dict:
    """
    Call Member 4's alert dispatcher.

    Expected module: backend/alert_dispatcher.py
    Expected callable: dispatch_alert(payload: dict) -> dict

    Member 2 does NOT implement alert transport (§17, §62).
    """
    try:
        mod = importlib.import_module("alert_dispatcher")
        payload = {
            "suspects": suspects,
            "origin": origin,
        }

        if area_sq_km is not None:
            payload["area_sq_km"] = area_sq_km

        return mod.dispatch_alert(payload)
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Member-4 alert dispatcher unavailable. "
                "Provide alert_dispatcher.py with dispatch_alert(payload)."
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Alert dispatcher error: {exc}",
        )


# ---------------------------------------------------------------------------
# Serialisation helpers — §70
# ---------------------------------------------------------------------------
def _safe_df_to_list(df) -> list[dict]:
    """Convert DataFrame to list of JSON-safe dicts."""
    import math as _math
    import numpy as _np

    records = df.to_dict(orient="records")
    result = []
    for row in records:
        clean = {}
        for k, v in row.items():
            clean[k] = _json_safe(v)
        result.append(clean)
    return result


def _json_safe(v: Any) -> Any:
    """Convert values to JSON-safe Python values."""
    import math as _math
    import numpy as _np

    if isinstance(v, _np.integer):
        return int(v)

    if isinstance(v, _np.floating):
        fv = float(v)
        return fv if _math.isfinite(fv) else None

    if isinstance(v, _np.ndarray):
        return [_json_safe(x) for x in v.tolist()]

    if hasattr(v, "isoformat"):
        return v.isoformat()

    if isinstance(v, float):
        return v if _math.isfinite(v) else None

    return v


def _clean_anomaly_list(anomalies: list[dict]) -> list[dict]:
    """Make all anomaly dicts JSON-safe."""
    return [{k: _json_safe(v) for k, v in a.items()} for a in anomalies]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CentroidModel(BaseModel):
    lat: float
    lon: float


class SlickModel(BaseModel):
    polygon: Any
    centroid: CentroidModel
    area_sq_km: Optional[float] = None
    perimeter_km: Optional[float] = None
    observation_timestamp: str  # UTC ISO-8601


class EnvironmentModel(BaseModel):
    # MODE A
    wind_U: Optional[float] = None
    wind_V: Optional[float] = None
    current_U: Optional[float] = None
    current_V: Optional[float] = None
    # MODE B
    wind_speed: Optional[float] = None
    wind_deg: Optional[float] = None
    current_speed: Optional[float] = None
    current_deg: Optional[float] = None
    convention: Optional[str] = None  # "toward" required for MODE B

    @model_validator(mode="after")
    def check_mode(self):
        mode_a = all(v is not None for v in [self.wind_U, self.wind_V, self.current_U, self.current_V])
        mode_b = all(v is not None for v in [self.wind_speed, self.wind_deg, self.current_speed, self.current_deg])
        if not mode_a and not mode_b:
            raise ValueError(
                "Environment must provide either "
                "(wind_U, wind_V, current_U, current_V) [MODE A] "
                "or (wind_speed, wind_deg, current_speed, current_deg) [MODE B]."
            )
        return self

    def to_engine_dict(self) -> dict:
        d = {}
        if self.wind_U is not None:
            d.update(wind_U=self.wind_U, wind_V=self.wind_V,
                     current_U=self.current_U, current_V=self.current_V)
        else:
            d.update(wind_speed=self.wind_speed, wind_deg=self.wind_deg,
                     current_speed=self.current_speed, current_deg=self.current_deg,
                     convention=self.convention or "unknown")
        return d


class DriftRequest(BaseModel):
    slick: Optional[SlickModel] = None
    environment: EnvironmentModel
    elapsed_hours: float
    forecast_hours: int = FORECAST_HOURS

    @field_validator("elapsed_hours")
    @classmethod
    def validate_elapsed(cls, v):
        if v < 0:
            raise ValueError("elapsed_hours must be >= 0.")
        return v

    @field_validator("forecast_hours")
    @classmethod
    def validate_forecast_hours(cls, v):
        if v != FORECAST_HOURS:
            raise ValueError(f"forecast_hours must be {FORECAST_HOURS} for this MVP.")
        return v


class SegmentRequest(BaseModel):
    roi_lat: float
    roi_lon: float
    timestamp: datetime
    raw_image_path: Optional[str] = None
    thermal_image_path: Optional[str] = None


class AlertRequest(BaseModel):
    suspects: Optional[list] = None
    origin: Optional[dict] = None
    area_sq_km: Optional[float] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/vessels", summary="Return AIS vessel records (§54)")
def get_vessels():
    """
    GET /vessels
    Load AIS data via Member-3 loader and return JSON-safe records.
    """
    global latest_vessels
    df = _load_ais_as_dataframe()
    rows = _safe_df_to_list(df)
    latest_vessels = rows
    return {"status": "success", "count": len(rows), "vessels": rows}


@app.get("/anomalies", summary="Detect AIS anomalies (§55)")
def get_anomalies():
    """
    GET /anomalies
    Load AIS data via Member 3 → detect SOG/COG anomalies via Member 2 detector.
    Does NOT automatically trigger /segment, /drift, /suspects, /alert.
    """
    global latest_anomalies
    df = _load_ais_as_dataframe()
    anomalies = run_anomaly_detection(df)
    anomalies = _clean_anomaly_list(anomalies)
    latest_anomalies = anomalies
    return {"status": "success", "count": len(anomalies), "anomalies": anomalies}


@app.post("/segment", summary="Bridge to Member-1 segmentation (§56)")
def post_segment(req: SegmentRequest):
    """
    POST /segment
    Validate request, call Member-1 segmentation, normalize response.

    Member 2 does NOT implement segmentation.
    Member 1 provides the georeferenced slick result.
    """
    global latest_segment

    # Call Member 1 using the integrated interface
    if req.raw_image_path or req.thermal_image_path:
        raw_result = _call_member1_segment(
            req.roi_lat,
            req.roi_lon,
            req.timestamp,
            raw_image_path=req.raw_image_path,
            thermal_image_path=req.thermal_image_path,
        )
    else:
        raw_result = _call_member1_segment(
            req.roi_lat,
            req.roi_lon,
            req.timestamp,
        )

    # ---------------------------------------------------------------
    # Validate georeferenced centroid
    # ---------------------------------------------------------------
    georeferenced = bool(raw_result.get("georeferenced", False))
    centroid = raw_result.get("centroid")

    if not georeferenced:
        raise HTTPException(
            status_code=400,
            detail=(
                "Segmentation result is not georeferenced. "
                "A non-georeferenced result cannot be used as geographic "
                "latitude/longitude."
            ),
        )

    if not isinstance(centroid, dict):
        raise HTTPException(
            status_code=400,
            detail=(
                "Georeferenced segmentation result must provide a geographic "
                "centroid with lat and lon."
            ),
        )

    if centroid.get("lat") is None or centroid.get("lon") is None:
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid must contain both lat and lon.",
        )

    try:
        centroid_lat = float(centroid["lat"])
        centroid_lon = float(centroid["lon"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid lat/lon must be numeric.",
        ) from exc

    if not math.isfinite(centroid_lat) or not math.isfinite(centroid_lon):
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid lat/lon must be finite.",
        )

    if not -90.0 <= centroid_lat <= 90.0:
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid latitude must be between -90 and 90.",
        )

    if not -180.0 <= centroid_lon <= 180.0:
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid longitude must be between -180 and 180.",
        )

    centroid = {
        "lat": centroid_lat,
        "lon": centroid_lon,
    }

    # ---------------------------------------------------------------
    # Observation timestamp
    # ---------------------------------------------------------------
    obs_ts = raw_result.get("observation_timestamp")

    if obs_ts is None:
        raise HTTPException(
            status_code=400,
            detail="observation_timestamp missing from Member-1 segmentation result.",
        )

    # ---------------------------------------------------------------
    # Build normalized slick object for downstream domains
    # ---------------------------------------------------------------
    slick = {
        "polygon": raw_result.get("polygon"),
        "centroid": centroid,
        "area_sq_km": raw_result.get("area_sq_km"),
        "perimeter_km": raw_result.get("perimeter_km"),
        "observation_timestamp": obs_ts,
    }

    latest_segment = slick

    return {
        "status": "success",
        "slick": slick,
    }


@app.post("/drift", summary="Physics-based drift hindcast + forecast (§52-53)")
def post_drift(req: DriftRequest):
    """
    POST /drift
    Validate, resolve slick, run hindcast and forecast, store state.
    Does NOT automatically call /suspects or /alert.

    Input modes (§49):
      MODE A: slick provided in request → use it
      MODE B: slick not in request → use latest_segment
    Conflict: request provides slick AND latest_segment → request wins (explicit)
    """
    global latest_drift, latest_origin, latest_forecast

    # --- resolve slick (§49) ------------------------------------------------
    if req.slick is not None:
        slick = req.slick.model_dump()
    elif latest_segment is not None:
        slick = latest_segment
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "No slick data provided. "
                "Either include 'slick' in the request body, "
                "or call POST /segment first to populate the latest validated slick."
            ),
        )

    # --- validate centroid (§51) --------------------------------------------
    centroid = slick.get("centroid")
    if centroid is None or centroid.get("lat") is None or centroid.get("lon") is None:
        raise HTTPException(
            status_code=400,
            detail="Geographic centroid unavailable. §51 georeferencing error.",
        )

    obs_ts = slick.get("observation_timestamp")
    if not obs_ts:
        raise HTTPException(
            status_code=400,
            detail="observation_timestamp missing from slick.",
        )

    obs_lat = float(centroid["lat"])
    obs_lon = float(centroid["lon"])
    env_dict = req.environment.to_engine_dict()

    # --- hindcast (§41-43) --------------------------------------------------
    try:
        hindcast_result = calculate_hindcast(
            observation_lat=obs_lat,
            observation_lon=obs_lon,
            observation_timestamp=obs_ts,
            environment=env_dict,
            elapsed_hours=req.elapsed_hours,
        )
    except (DriftValidationError, EnvironmentConventionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # --- forecast — starts from OBSERVED slick, NOT from hindcast (§45) ----
    try:
        forecast_result = calculate_forecast(
            observation_lat=obs_lat,
            observation_lon=obs_lon,
            observation_timestamp=obs_ts,
            environment=env_dict,
            forecast_hours=req.forecast_hours,
        )
    except (DriftValidationError, EnvironmentConventionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    origin = {
        "lat": hindcast_result["origin_lat"],
        "lon": hindcast_result["origin_lon"],
        "timestamp": hindcast_result["origin_timestamp"],
    }

    # --- update runtime state -----------------------------------------------
    latest_origin = origin
    latest_forecast = forecast_result
    latest_drift = {
        "slick": slick,
        "origin": origin,
        "forecast": forecast_result,
        "model": {
            "wind_factor": WIND_FACTOR,
            "timestep_minutes": DT_SECONDS // 60,
            "forecast_hours": req.forecast_hours,
        },
    }

    return {
        "status": "success",
        "slick": slick,
        "origin": origin,
        "forecast": forecast_result,
        "model": {
            "wind_factor": WIND_FACTOR,
            "timestep_minutes": DT_SECONDS // 60,
            "forecast_hours": req.forecast_hours,
        },
    }


@app.get("/suspects", summary="Ranked vessel suspects via Member-3 scorer (§57)")
def get_suspects():
    """
    GET /suspects
    Pass latest probable origin to Member-3 scorer; return ranked suspects.
    If origin is missing → HTTP 400.
    Does NOT fabricate origin.
    """
    global latest_suspects

    if latest_origin is None:
        raise HTTPException(
            status_code=400,
            detail="No drift origin available. Run POST /drift first.",
        )

    suspects = _call_member3_suspects(
        origin_lat=latest_origin["lat"],
        origin_lon=latest_origin["lon"],
        origin_timestamp=latest_origin["timestamp"],
    )
    latest_suspects = suspects
    return {"status": "success", "count": len(suspects), "suspects": suspects}


@app.post("/alert", summary="Bridge to Member-4 alert dispatcher (§60)")
def post_alert(req: AlertRequest):
    """
    POST /alert
    Validate suspects, origin, area; bridge to Member-4 dispatcher.
    Member 2 does NOT implement alert transport.
    """
    global latest_alert_status

    # Use request data if provided; fall back to runtime state
    suspects = req.suspects if req.suspects is not None else latest_suspects
    origin = req.origin if req.origin is not None else latest_origin
    area_sq_km = req.area_sq_km if req.area_sq_km is not None else (
        latest_segment.get("area_sq_km") if latest_segment else None
    )

    # --- validation (§61) ---------------------------------------------------
    if not suspects:
        raise HTTPException(
            status_code=400,
            detail="No suspects available. Run GET /suspects first.",
        )
    if origin is None:
        raise HTTPException(
            status_code=400,
            detail="No drift origin available. Run POST /drift first.",
        )

    result = _call_member4_alert(suspects, origin, area_sq_km)
    latest_alert_status = result
    return {"status": "success", "alert": result}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "AquaGuard AI Backend", "version": "1.0.0"}
