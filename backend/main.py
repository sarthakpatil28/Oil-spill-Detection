from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from accessais_loader import load_vessels
from anomaly_detector import run_anomaly_detection
from drift_engine import calculate_hindcast, calculate_forecast
from suspect_scorer import score_suspects
from alert_dispatcher import dispatch_alert
from osdm_segmentation import segment_oil_spill


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Marine Oil Spill Intelligence API",
    description=(
        "Integrated backend for marine oil-spill detection, "
        "drift reconstruction and AIS vessel attribution."
    ),
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# RUNTIME STATE
# ============================================================

STATE: dict[str, Any] = {
    "vessels": [],
    "anomalies": [],
    "segmentation": None,
    "origin": None,
    "forecast": None,
    "suspects": [],
    "last_alert": None,
}


# ============================================================
# REQUEST MODELS
# ============================================================

class SegmentationRequest(BaseModel):
    image_name: str
    roi_lat: float | None = None
    roi_lon: float | None = None
    timestamp: str | None = None


class DriftRequest(BaseModel):
    centroid_lat: float
    centroid_lon: float
    timestamp: str
    current_speed: float
    current_direction: float
    wind_speed: float
    wind_direction: float


class AlertRequest(BaseModel):
    incident: str
    priority: str | None = None
    vessel: str
    score: float


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health_check():
    return {
        "status": "operational",
        "system": "Marine Oil Spill Intelligence",
        "version": "1.0.0",
        "pipeline": {
            "ais": True,
            "anomaly_detection": True,
            "segmentation": True,
            "drift": True,
            "suspect_scoring": True,
            "alerts": True,
        },
    }


# ============================================================
# VESSEL INTELLIGENCE
# ============================================================

@app.get("/api/vessels")
def get_vessels():
    """
    Load vessel observations from the configured AIS source.

    Default mode uses the local sample AIS dataset.
    """

    try:
        vessels = load_vessels()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"AIS data unavailable: {exc}",
        ) from exc

    # Convert DataFrame/list output into JSON-safe records.
    if hasattr(vessels, "to_dict"):
        records = vessels.to_dict(orient="records")
    elif isinstance(vessels, list):
        records = vessels
    else:
        records = []

    STATE["vessels"] = records

    return {
        "status": "success",
        "count": len(records),
        "data": records,
    }


# ============================================================
# ANOMALY DETECTION
# ============================================================

@app.get("/api/anomalies")
def get_anomalies():
    """
    Run AIS anomaly detection on the available vessel data.
    """

    if not STATE["vessels"]:
        get_vessels()

    try:
        anomalies = run_anomaly_detection(STATE["vessels"])
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Anomaly detection failed: {exc}",
        ) from exc

    if hasattr(anomalies, "to_dict"):
        anomaly_records = anomalies.to_dict(orient="records")
    elif isinstance(anomalies, list):
        anomaly_records = anomalies
    else:
        anomaly_records = []

    STATE["anomalies"] = anomaly_records

    return {
        "status": "success",
        "count": len(anomaly_records),
        "data": anomaly_records,
    }


# ============================================================
# OIL-SPILL SEGMENTATION
# ============================================================

@app.post("/api/segment")
def segment_oil_spill_endpoint(request: SegmentationRequest):
    """
    Run local SAR oil-spill segmentation.

    If roi coordinates are supplied, the segmentation result is
    georeferenced around that ROI.
    """

    image_path = Path(request.image_name)

    if not image_path.is_absolute():
        image_path = Path(__file__).resolve().parent / image_path

    if not image_path.exists():

        # Also support backend/static/<filename>
        static_candidate = (
            Path(__file__).resolve().parent
            / "static"
            / request.image_name
        )

        if static_candidate.exists():
            image_path = static_candidate
        else:
            raise HTTPException(
                status_code=404,
                detail=f"SAR image not found: {request.image_name}",
            )

    try:
        result = segment_oil_spill(str(image_path))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Segmentation failed: {exc}",
        ) from exc

    slicks = result.get("slicks", [])

    if not slicks:
        STATE["segmentation"] = {
            "detected": False,
            "source": request.image_name,
        }

        return {
            "status": "success",
            "source": request.image_name,
            "detection": {
                "detected": False,
                "class": "oil_spill",
            },
            "message": "No oil-slick candidate detected.",
        }

    slick = max(
        slicks,
        key=lambda item: item.get("area_sq_km", 0),
    )

    centroid = slick.get("centroid", {})

    detection = {
        "detected": True,
        "class": "oil_spill",
        "area_km2": slick.get("area_sq_km"),
        "perimeter_km": slick.get("perimeter_km"),
        "circularity": slick.get("circularity"),
        "centroid": centroid,
        "polygon": slick.get("polygon_points", []),
    }

    STATE["segmentation"] = detection

    return {
        "status": "success",
        "source": request.image_name,
        "detection": detection,
        "message": "Local SAR oil-spill segmentation completed.",
    }


# ============================================================
# DRIFT RECONSTRUCTION
# ============================================================

@app.post("/api/drift")
def calculate_drift_endpoint(request: DriftRequest):
    """
    Run physics-based backward hindcast and forward forecast.
    """

    try:
        origin_result = calculate_hindcast(
            centroid_lat=request.centroid_lat,
            centroid_lon=request.centroid_lon,
            timestamp=request.timestamp,
            current_speed=request.current_speed,
            current_direction=request.current_direction,
            wind_speed=request.wind_speed,
            wind_direction=request.wind_direction,
        )

        forecast_result = calculate_forecast(
            centroid_lat=request.centroid_lat,
            centroid_lon=request.centroid_lon,
            timestamp=request.timestamp,
            current_speed=request.current_speed,
            current_direction=request.current_direction,
            wind_speed=request.wind_speed,
            wind_direction=request.wind_direction,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Drift calculation failed: {exc}",
        ) from exc

    STATE["origin"] = origin_result
    STATE["forecast"] = forecast_result

    return {
        "status": "success",
        "model": "Physics-based drift reconstruction",
        "time_step_minutes": 10,
        "wind_factor": 0.03,
        "data": {
            "hindcast": origin_result,
            "forecast": forecast_result,
        },
    }


# ============================================================
# SUSPECT SCORING
# ============================================================

@app.get("/api/suspects")
def get_suspects():
    """
    Rank vessels using AIS behaviour, spatial proximity and
    incident-time correlation.
    """

    if not STATE["origin"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "Run /api/drift first so the suspect engine "
                "has an incident origin."
            ),
        )

    try:
        suspects = score_suspects(
            origin=STATE["origin"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Suspect scoring failed: {exc}",
        ) from exc

    if hasattr(suspects, "to_dict"):
        suspect_records = suspects.to_dict(orient="records")
    elif isinstance(suspects, list):
        suspect_records = suspects
    else:
        suspect_records = []

    STATE["suspects"] = suspect_records

    return {
        "status": "success",
        "disclaimer": (
            "Suspect scores are evidence-based rankings "
            "and do not establish responsibility or guilt."
        ),
        "data": suspect_records,
    }


# ============================================================
# ALERT DISPATCH
# ============================================================

@app.post("/api/alert")
def dispatch_alert_endpoint(request: AlertRequest):
    """
    Dispatch an operational incident alert using the integrated
    Member-4 alert dispatcher.
    """

    payload = {
        "incident": request.incident,
        "priority": request.priority,
        "vessel": request.vessel,
        "score": request.score,
        "origin": STATE.get("origin"),
        "suspects": STATE.get("suspects"),
        "area_sq_km": (
            STATE.get("segmentation", {}) or {}
        ).get("area_km2"),
    }

    try:
        result = dispatch_alert(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Alert dispatch failed: {exc}",
        ) from exc

    STATE["last_alert"] = result

    return {
        "status": "success",
        "alert": result,
        "message": "Emergency incident alert dispatched.",
    }


# ============================================================
# DEBUG / SYSTEM STATE
# ============================================================

@app.get("/api/system/state")
def get_system_state():
    """
    Lightweight integration-state endpoint useful during testing.
    """

    return {
        "status": "success",
        "state": {
            "vessel_count": len(STATE["vessels"]),
            "anomaly_count": len(STATE["anomalies"]),
            "segmentation_ready": STATE["segmentation"] is not None,
            "origin_ready": STATE["origin"] is not None,
            "forecast_ready": STATE["forecast"] is not None,
            "suspect_count": len(STATE["suspects"]),
            "alert_dispatched": STATE["last_alert"] is not None,
        },
    }