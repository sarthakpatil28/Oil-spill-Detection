"""FastAPI routes for satellite vision processing, vessel cross-correlation, and digital land masking."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator

from gee_ingestor import download_sentinel1_png
from osdm_segmentation import segment_oil_spill

router = APIRouter()


class InvalidGeoreferenceError(Exception):
    """Raised when the image footprint cannot be georeferenced."""


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != "AQUAGUARD-VISION-SECURE":
        raise HTTPException(status_code=401, detail="Invalid API Key")


def validate_observation_timestamp(timestamp: str) -> str:
    """Validate ISO-8601 observation timestamp with timezone and normalize to UTC."""
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("Invalid observation timestamp")

    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError) as err:
        raise ValueError("Invalid observation timestamp") from err

    if parsed.tzinfo is None:
        raise ValueError("Observation timestamp must include timezone")

    return parsed.astimezone(timezone.utc).isoformat()


def run_segmentation(
    roi_lat: float,
    roi_lon: float,
    timestamp: str,
    raw_image_path: str = None,
    thermal_image_path: str = None,
) -> dict[str, Any]:
    """Download, segment, and georeference a SAR image around a point.

    Args:
        roi_lat: Latitude of region of interest.
        roi_lon: Longitude of region of interest.
        timestamp: Observation timestamp supplied by the integration caller.
        raw_image_path: Optional local raw image path to bypass downloading.
        thermal_image_path: Optional path to thermal validation image for future cross-sensor validation.

    Returns:
        A nested spill result or a specification-defined error response.
    """
    observation_timestamp = validate_observation_timestamp(timestamp)

    try:
        min_lon = roi_lon - 0.1
        max_lon = roi_lon + 0.1
        min_lat = roi_lat - 0.1
        max_lat = roi_lat + 0.1

        if raw_image_path and Path(raw_image_path).exists():
            image_path = raw_image_path
        else:
            image_path = download_sentinel1_png(
                min_lon,
                min_lat,
                max_lon,
                max_lat,
                output_path="static/integrated_sar.png",
            )

        segmentation = segment_oil_spill(image_path)
        slicks = segmentation.get("slicks", [])
        if not slicks:
            return {"success": False, "error": "NO_SPILL_DETECTED"}

        raw_img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if raw_img is None or raw_img.ndim != 2:
            raise InvalidGeoreferenceError

        original_height, original_width = raw_img.shape
        if original_width < 2 or original_height < 2:
            raise InvalidGeoreferenceError

        pixel_width = (max_lon - min_lon) / (original_width - 1)
        pixel_height = (max_lat - min_lat) / (original_height - 1)
        geotransform = (
            min_lon,
            pixel_width,
            0.0,
            max_lat,
            0.0,
            -pixel_height,
        )
        if not all(math.isfinite(value) for value in geotransform):
            raise InvalidGeoreferenceError

        def pixel_to_coordinates(upscaled_x: float, upscaled_y: float) -> list[float]:
            """Map 4x-upscaled pixels through the original image geotransform."""
            original_x = upscaled_x / 4.0
            original_y = upscaled_y / 4.0
            lon = geotransform[0] + original_x * geotransform[1]
            lat = geotransform[3] + original_y * geotransform[5]
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise InvalidGeoreferenceError
            return [float(lon), float(lat)]

        slick = max(slicks, key=lambda detected: detected["area_sq_km"])
        slick_polygon = [
            pixel_to_coordinates(float(x), float(y))
            for x, y in slick["polygon_points"]
        ]
        centroid = slick["centroid"]
        centroid_lon, centroid_lat = pixel_to_coordinates(
            float(centroid["x"]),
            float(centroid["y"]),
        )
        area_sq_km = float(slick["area_sq_km"])
        perimeter_km = float(slick["perimeter_km"])
        if not (
            math.isfinite(centroid_lat)
            and math.isfinite(centroid_lon)
            and -90 <= centroid_lat <= 90
            and -180 <= centroid_lon <= 180
        ):
            raise InvalidGeoreferenceError
    except InvalidGeoreferenceError:
        return {"success": False, "error": "INVALID_GEOREFERENCE"}
    except Exception:
        return {"success": False, "error": "VISION_PROCESSING_FAILED"}

    return {
        "success": True,
        "spill": {
            "polygon": slick_polygon,
            "area_sq_km": area_sq_km,
            "perimeter_km": perimeter_km,
            "centroid": {
                "lat": centroid_lat,
                "lon": centroid_lon,
            },
            "observation_timestamp": observation_timestamp,
            "georeferenced": True,
        },
    }


class VisionProcessRequest(BaseModel):
    """Input required to run integrated SAR segmentation."""

    roi_lat: float
    roi_lon: float
    timestamp: str
    thermal_image_path: str | None = None
    raw_image_path: str | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_field(cls, value: str) -> str:
        return validate_observation_timestamp(value)


@router.post(
    "/api/v1/vision/process",
    dependencies=[Depends(verify_api_key)],
)
def process_vision(request: VisionProcessRequest) -> dict[str, Any]:
    """Run integrated SAR segmentation for the requested region of interest."""
    try:
        result = run_segmentation(
            roi_lat=request.roi_lat,
            roi_lon=request.roi_lon,
            timestamp=request.timestamp,
            thermal_image_path=request.thermal_image_path,
            raw_image_path=request.raw_image_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
