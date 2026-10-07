"""Satellite oil spill segmentation and vessel detection using OpenCV, NumPy, and Gradio."""

from __future__ import annotations

import math
from pathlib import Path

from typing import Any

import cv2

import numpy as np

def upscale_sar_image(
    image_path: str,
    output_path: str | None = None,
    scale: int = 4,
) -> str:
    """Locally upscale a SAR image using OpenCV."""

    src = Path(image_path)

    if not src.exists():
        raise FileNotFoundError(
            f"Source SAR image not found: {image_path}"
        )

    if output_path is None:
        dest = src.with_name(f"upscaled_{src.name}")
    else:
        dest = Path(output_path)

    dest.parent.mkdir(parents=True, exist_ok=True)

    raw_img = cv2.imread(
        str(src),
        cv2.IMREAD_GRAYSCALE
    )

    if raw_img is None:
        raise ValueError(
            f"Unable to read image for upscaling: {src}"
        )

    height, width = raw_img.shape[:2]

    upscaled = cv2.resize(
        raw_img,
        (width * scale, height * scale),
        interpolation=cv2.INTER_CUBIC,
    )

    gaussian = cv2.GaussianBlur(
        upscaled,
        (0, 0),
        2.0,
    )

    sharpened = cv2.addWeighted(
        upscaled,
        1.5,
        gaussian,
        -0.5,
        0,
    )

    if not cv2.imwrite(str(dest), sharpened):
        raise IOError(
            f"Failed to write upscaled image: {dest}"
        )

    return str(dest)



def resolve_water_mask_path(explicit_path: str | None = None) -> Path | None:
    """Find the digital water mask fixture across common relative locations."""
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            return candidate

    search_paths = [
        Path("static/water_mask_001.png"),
        Path("backend/static/water_mask_001.png"),
        Path(__file__).resolve().parent / "static" / "water_mask_001.png",
    ]
    for p in search_paths:
        if p.exists():
            return p
    return None


def segment_oil_spill(
    image_path: str,
    km_per_pixel: float = 0.0025,
    lookalike_circularity_threshold: float = 0.70,
    land_mask_path: str | None = None,
    minimum_area_sq_km: float = 0.001,
) -> dict[str, list[dict[str, Any]]]:
    """Segment dark oil patches with 4x super-resolution, land masking, and circularity filtering.

    Args:
        image_path: Path to the satellite SAR image to analyze.
        km_per_pixel: Ground distance represented by one pixel of the raw image.
        lookalike_circularity_threshold: Threshold above which compact contours (>=0.70)
            are discarded as natural look-alikes.
        land_mask_path: Optional path to binary land/water mask (255=water, 0=land).
        minimum_area_sq_km: Minimum area filter in square kilometers.

    Returns:
        A dictionary with "slicks" (largest true elongated slick) and "ships".
    """
    if km_per_pixel <= 0:
        raise ValueError("km_per_pixel must be greater than zero")

    # Step 1: 4x Super-Resolution Upscaling before OpenCV processing
    upscaled_path = upscale_sar_image(image_path)
    sar_image = cv2.imread(upscaled_path, cv2.IMREAD_GRAYSCALE)
    if sar_image is None:
        raise ValueError(f"Unable to read upscaled image: {upscaled_path}")

    # Step 2: Digital Land Masking
    mask_file = resolve_water_mask_path(land_mask_path)
    water_mask: np.ndarray | None = None
    if mask_file is not None and mask_file.exists():
        raw_mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
        if raw_mask is not None:
            if raw_mask.shape != sar_image.shape:
                water_mask = cv2.resize(
                    raw_mask,
                    (sar_image.shape[1], sar_image.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )
            else:
                water_mask = raw_mask
            _, water_mask = cv2.threshold(water_mask, 127, 255, cv2.THRESH_BINARY)
            # Apply cv2.bitwise_and(sar_image, sar_image, mask=water_mask)
            sar_image = cv2.bitwise_and(sar_image, sar_image, mask=water_mask)

    # Step 3: Otsu Binarization Engine
    _, thresh = cv2.threshold(
        sar_image,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    # Ensure zeroed-out land pixels do not become inverted foreground
    if water_mask is not None:
        thresh = cv2.bitwise_and(thresh, thresh, mask=water_mask)

    # Morphological smoothing to eliminate speckle noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    smoothed = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    smoothed = cv2.morphologyEx(smoothed, cv2.MORPH_CLOSE, kernel)

    # Find external contours
    contours, _ = cv2.findContours(
        smoothed,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    # Ground resolution adjustment for 4x upscaled image
    effective_km_per_pixel = km_per_pixel / 4.0
    pixel_area_to_sq_km = float(np.square(effective_km_per_pixel))

    candidate_slicks: list[dict[str, Any]] = []

    # Step 4: Circularity Look-Alike Filter
    for c in contours:
        area = cv2.contourArea(c)
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue

        # Isoperimetric circularity quotient: (4 * pi * area) / (perimeter^2)
        circularity = (4.0 * math.pi * area) / (perimeter ** 2)

        # Filter out compact natural look-alikes (algal blooms): discard if circularity >= 0.70
        if circularity >= lookalike_circularity_threshold:
            continue

        area_sq_km = float(area * pixel_area_to_sq_km)
        if area_sq_km < minimum_area_sq_km:
            continue

        moments = cv2.moments(c)
        if moments["m00"] == 0:
            continue

        perimeter_km = float(perimeter * effective_km_per_pixel)
        centroid = {
            "x": float(moments["m10"] / moments["m00"]),
            "y": float(moments["m01"] / moments["m00"]),
        }
        polygon_points = [
            [int(point[0][0]), int(point[0][1])] for point in c
        ]

        candidate_slicks.append(
            {
                "centroid": centroid,
                "area_sq_km": area_sq_km,
                "perimeter_km": perimeter_km,
                "polygon_points": polygon_points,
                "circularity": float(circularity),
                "is_likely_lookalike": False,
                "raw_area": area,
            }
        )

    # Keep only the largest contour where circularity < 0.70 (true elongated oil slicks)
    slicks: list[dict[str, Any]] = []
    if candidate_slicks:
        largest_slick = max(candidate_slicks, key=lambda s: s["raw_area"])
        slicks.append(largest_slick)

    # Step 5: Bright metal vessel hull detection (> 240)
    _, ship_mask = cv2.threshold(sar_image, 240, 255, cv2.THRESH_BINARY)
    if water_mask is not None:
        ship_mask = cv2.bitwise_and(ship_mask, water_mask)

    ship_contours, _ = cv2.findContours(
        ship_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    ships: list[dict[str, Any]] = []
    for sc in ship_contours:
        moments = cv2.moments(sc)
        if moments["m00"] > 0:
            cx = float(moments["m10"] / moments["m00"])
            cy = float(moments["m01"] / moments["m00"])
        else:
            rect = cv2.boundingRect(sc)
            cx = float(rect[0] + rect[2] / 2.0)
            cy = float(rect[1] + rect[3] / 2.0)
        ships.append({"centroid": {"x": cx, "y": cy}})

    return {
        "slicks": slicks,
        "ships": ships,
    }