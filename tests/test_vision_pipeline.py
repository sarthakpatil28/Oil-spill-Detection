"""Comprehensive Verification & Runtime Test Suite for AquaGuard AI Vision Pipeline.

Verifies:
1. 4x Super-Resolution via upscale_sar_image().
2. Digital land masking via cv2.bitwise_and() with static/water_mask_001.png.
3. Otsu binarization and morphological smoothing.
4. Circularity look-alike filter:
   - Circularity quotient = (4 * pi * area) / (perimeter ** 2)
   - Discards contours with circularity >= 0.70 (algal blooms / calm zones)
   - Retains only the largest true elongated slick (circularity < 0.70).
5. Thermal validation optional placeholder parameter (thermal_image_path).
6. Strict timestamp validation & UTC normalization (Tests 1 - 7).
7. Frozen nested dictionary contract and accurate 4x scaled georeferencing math.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Add backend directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import cv2
from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from osdm_segmentation import segment_oil_spill, upscale_sar_image
from vision_api import (
    router,
    run_segmentation,
    validate_observation_timestamp,
)


def test_4x_super_resolution() -> None:
    """Verify that upscale_sar_image scales SAR images by exactly 4x."""
    src = BACKEND_DIR / "static" / "enhanced_sar_001.png"
    assert src.exists(), f"Source image missing: {src}"

    raw_img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
    orig_h, orig_w = raw_img.shape[:2]

    upscaled_path = upscale_sar_image(str(src))
    upscaled_img = cv2.imread(upscaled_path, cv2.IMREAD_GRAYSCALE)
    assert upscaled_img is not None, "Failed to load upscaled image"

    up_h, up_w = upscaled_img.shape[:2]
    assert up_h == orig_h * 4, f"Expected height {orig_h * 4}, got {up_h}"
    assert up_w == orig_w * 4, f"Expected width {orig_w * 4}, got {up_w}"

    print("  [PASS] 4x Super-Resolution Test:")
    print(f"         - Raw Dimensions: {orig_w}x{orig_h}")
    print(f"         - Upscaled Dimensions: {up_w}x{up_h} (Exact 4x scale)")


def test_digital_land_masking_and_circularity_filter() -> None:
    """Verify digital land masking zeroes out terrain and circularity filter discards round look-alikes."""
    src = BACKEND_DIR / "static" / "enhanced_sar_001.png"
    mask_path = BACKEND_DIR / "static" / "water_mask_001.png"

    res = segment_oil_spill(str(src), land_mask_path=str(mask_path))
    slicks = res.get("slicks", [])

    # Exactly 1 true elongated slick must be returned (land patch masked out, round look-alikes discarded)
    assert len(slicks) == 1, f"Expected exactly 1 true elongated slick, got {len(slicks)}"

    slick = slicks[0]
    assert slick["circularity"] < 0.70, f"Expected circularity < 0.70, got {slick['circularity']}"
    assert slick["is_likely_lookalike"] is False
    assert slick["area_sq_km"] > 0.01

    print("  [PASS] Digital Land Masking & Circularity Filter Test:")
    print(f"         - Slicks Retained: {len(slicks)} (largest elongated slick)")
    print(f"         - Circularity: {slick['circularity']:.4f} (< 0.70 threshold)")
    print(f"         - Area: {slick['area_sq_km']:.4f} sq km")
    print(f"         - Perimeter: {slick['perimeter_km']:.4f} km")


def test_compact_lookalike_rejection() -> None:
    """Verify that a compact circular contour (circularity >= 0.70) is explicitly discarded."""
    test_file = BACKEND_DIR / "static" / "test_round_slick.png"
    # Create test image with ONLY a round circle (simulating algal bloom)
    img = np.full((500, 500), 200, dtype=np.uint8)
    cv2.circle(img, (250, 250), 60, 30, -1)
    cv2.imwrite(str(test_file), img)

    try:
        res = segment_oil_spill(str(test_file))
        slicks = res.get("slicks", [])
        # Round feature should be filtered out by circularity >= 0.70
        assert len(slicks) == 0, f"Expected round algal bloom to be rejected, but got {len(slicks)} slicks"
        print("  [PASS] Compact Look-Alike Rejection Test:")
        print("         - Successfully discarded contour with circularity >= 0.70")
    finally:
        if test_file.exists():
            test_file.unlink()
        upscaled_test = BACKEND_DIR / "static" / "upscaled_test_round_slick.png"
        if upscaled_test.exists():
            upscaled_test.unlink()


# ============================================================
# TIMESTAMP VALIDATION & NORMALIZATION TESTS (TESTS 1 - 7)
# ============================================================


def test_timestamp_1_utc() -> None:
    """TEST 1 - UTC TIMESTAMP: 2025-05-01T12:00:00+00:00 preserved."""
    ts = "2025-05-01T12:00:00+00:00"
    normalized = validate_observation_timestamp(ts)
    assert normalized == "2025-05-01T12:00:00+00:00"
    print("  [PASS] Test 1 — UTC Timestamp: 2025-05-01T12:00:00+00:00 ->", normalized)


def test_timestamp_2_z() -> None:
    """TEST 2 - Z TIMESTAMP: 2025-05-01T12:00:00Z normalized to +00:00."""
    ts = "2025-05-01T12:00:00Z"
    normalized = validate_observation_timestamp(ts)
    assert normalized == "2025-05-01T12:00:00+00:00"
    print("  [PASS] Test 2 — Z Timestamp: 2025-05-01T12:00:00Z ->", normalized)


def test_timestamp_3_non_utc_offset() -> None:
    """TEST 3 - NON-UTC OFFSET: 2025-05-01T17:30:00+05:30 normalized to 12:00:00+00:00."""
    ts = "2025-05-01T17:30:00+05:30"
    normalized = validate_observation_timestamp(ts)
    assert normalized == "2025-05-01T12:00:00+00:00"
    print("  [PASS] Test 3 — Non-UTC Offset: 2025-05-01T17:30:00+05:30 ->", normalized)


def test_timestamp_4_timezone_less() -> None:
    """TEST 4 - TIMEZONE-LESS TIMESTAMP: 2025-05-01T12:00:00 rejected."""
    ts = "2025-05-01T12:00:00"
    with pytest.raises(ValueError) as excinfo:
        validate_observation_timestamp(ts)
    assert "timezone" in str(excinfo.value).lower()
    print("  [PASS] Test 4 — Timezone-less Rejected:", excinfo.value)


def test_timestamp_5_invalid_string() -> None:
    """TEST 5 - INVALID STRING: not-a-timestamp and 2025-99-99 rejected."""
    for invalid in ["not-a-timestamp", "2025-99-99", "", "   "]:
        with pytest.raises(ValueError):
            validate_observation_timestamp(invalid)
    print("  [PASS] Test 5 — Invalid Strings Rejected Successfully")


def test_timestamp_6_no_current_time_substitution() -> None:
    """TEST 6 - NO CURRENT-TIME SUBSTITUTION: invalid timestamps never fall back to current time."""
    raw_fixture = str(BACKEND_DIR / "static" / "enhanced_sar_001.png")
    # Calling run_segmentation with invalid or missing timezone MUST raise ValueError
    with pytest.raises(ValueError):
        run_segmentation(19.5, 71.4, "2025-05-01T12:00:00", raw_image_path=raw_fixture)
    with pytest.raises(ValueError):
        run_segmentation(19.5, 71.4, "not-a-timestamp", raw_image_path=raw_fixture)
    print("  [PASS] Test 6 — No Current-Time Substitution Verified")


def test_frozen_contract_and_georeferencing() -> None:
    """TEST 7 - FINAL JSON CONTRACT: verify all keys, georeferencing, and normalized timestamp."""
    raw_fixture = str(BACKEND_DIR / "static" / "enhanced_sar_001.png")
    thermal_fixture = str(BACKEND_DIR / "static" / "thermal_sar_001.png")

    result = run_segmentation(
        roi_lat=19.5,
        roi_lon=71.4,
        timestamp="2025-05-01T17:30:00+05:30",
        thermal_image_path=thermal_fixture,
        raw_image_path=raw_fixture,
    )

    assert set(result) == {"success", "spill"}
    assert result["success"] is True
    spill = result["spill"]
    assert set(spill) == {
        "polygon",
        "area_sq_km",
        "perimeter_km",
        "centroid",
        "observation_timestamp",
        "georeferenced",
    }
    assert "confidence" not in result and "geometry" not in result
    assert "area_km2" not in spill and "timestamp" not in spill
    assert "lat" not in spill and "lon" not in spill

    # Timestamp normalized to UTC
    assert spill["observation_timestamp"] == "2025-05-01T12:00:00+00:00"

    # Georeferencing assertions
    centroid = spill["centroid"]
    assert 19.4 <= centroid["lat"] <= 19.6
    assert 71.3 <= centroid["lon"] <= 71.5
    assert spill["georeferenced"] is True
    assert len(spill["polygon"]) > 0, "Expected non-empty polygon"
    for pt in spill["polygon"]:
        assert 71.3 <= pt[0] <= 71.5, f"Polygon lon out of bounds: {pt[0]}"
        assert 19.4 <= pt[1] <= 19.6, f"Polygon lat out of bounds: {pt[1]}"

    print("  [PASS] Test 7 — Frozen Dictionary Contract & Georeferencing Test:")
    print(f"         - Centroid Coordinates: ({centroid['lat']:.4f}, {centroid['lon']:.4f})")
    print(f"         - Area: {spill['area_sq_km']:.4f} sq km | Perimeter: {spill['perimeter_km']:.4f} km")
    print(f"         - Normalized Observation Timestamp: {spill['observation_timestamp']}")


class _SimpleMonkeyPatch:
    """Lightweight patcher for running outside pytest."""

    def __init__(self):
        self._originals = []

    def setattr(self, target: str, value: object):
        mod_name, attr_name = target.rsplit(".", 1)
        mod = sys.modules[mod_name]
        self._originals.append((mod, attr_name, getattr(mod, attr_name)))
        setattr(mod, attr_name, value)

    def undo(self):
        for mod, attr_name, orig in reversed(self._originals):
            setattr(mod, attr_name, orig)
        self._originals.clear()


def test_strict_error_states(monkeypatch=None) -> None:
    """Verify the three exact pipeline error responses."""
    raw_fixture = str(BACKEND_DIR / "static" / "enhanced_sar_001.png")
    valid_ts = "2025-05-01T12:00:00Z"

    patcher = None
    if monkeypatch is None:
        patcher = _SimpleMonkeyPatch()
        mp = patcher
    else:
        mp = monkeypatch

    try:
        mp.setattr("vision_api.segment_oil_spill", lambda _: {"slicks": []})
        assert run_segmentation(19.5, 71.4, valid_ts, raw_image_path=raw_fixture) == {
            "success": False,
            "error": "NO_SPILL_DETECTED",
        }

        mp.setattr(
            "vision_api.segment_oil_spill",
            lambda _: {"slicks": [{"area_sq_km": 1, "perimeter_km": 1, "polygon_points": [], "centroid": {"x": float("nan"), "y": 1}}]},
        )
        assert run_segmentation(19.5, 71.4, valid_ts, raw_image_path=raw_fixture) == {
            "success": False,
            "error": "INVALID_GEOREFERENCE",
        }

        mp.setattr("vision_api.segment_oil_spill", lambda _: (_ for _ in ()).throw(RuntimeError))
        assert run_segmentation(19.5, 71.4, valid_ts, raw_image_path=raw_fixture) == {
            "success": False,
            "error": "VISION_PROCESSING_FAILED",
        }
    finally:
        if patcher:
            patcher.undo()

    print("  [PASS] Strict Error States (NO_SPILL_DETECTED, INVALID_GEOREFERENCE, VISION_PROCESSING_FAILED)")


def test_fastapi_http_endpoint() -> None:
    """Verify the FastAPI route enforces the API key, validates timestamps, and returns the frozen contract."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1. Test missing API key
    fail_res = client.post(
        "/api/v1/vision/process",
        json={"roi_lat": 19.5, "roi_lon": 71.4, "timestamp": "2025-05-01T12:00:00Z"},
    )
    assert fail_res.status_code in (401, 422)

    # 2. Test valid API key but timezone-less timestamp (must be rejected with HTTP 422)
    headers = {"X-API-Key": "AQUAGUARD-VISION-SECURE"}
    bad_ts_payload = {
        "roi_lat": 19.5,
        "roi_lon": 71.4,
        "timestamp": "2025-05-01T12:00:00",
        "raw_image_path": str(BACKEND_DIR / "static" / "enhanced_sar_001.png"),
    }
    tz_fail = client.post("/api/v1/vision/process", headers=headers, json=bad_ts_payload)
    assert tz_fail.status_code == 422, f"Expected 422 for timezone-less timestamp, got {tz_fail.status_code}"

    # 3. Test valid API key and valid timestamp (non-UTC normalized to UTC)
    payload = {
        "roi_lat": 19.5,
        "roi_lon": 71.4,
        "timestamp": "2025-05-01T17:30:00+05:30",
        "thermal_image_path": str(BACKEND_DIR / "static" / "thermal_sar_001.png"),
        "raw_image_path": str(BACKEND_DIR / "static" / "enhanced_sar_001.png"),
    }
    success_res = client.post("/api/v1/vision/process", headers=headers, json=payload)
    assert success_res.status_code == 200, f"Expected 200, got {success_res.status_code}: {success_res.text}"

    data = success_res.json()
    assert set(data) == {"success", "spill"}
    assert data["success"] is True
    assert set(data["spill"]) == {
        "polygon",
        "area_sq_km",
        "perimeter_km",
        "centroid",
        "observation_timestamp",
        "georeferenced",
    }
    assert data["spill"]["observation_timestamp"] == "2025-05-01T12:00:00+00:00"
    assert "confidence" not in data and "geometry" not in data

    print("  [PASS] FastAPI HTTP 200 Endpoint Test:")
    print(f"         - HTTP Status: {success_res.status_code}")
    print(f"         - Observation Timestamp Normalized: {data['spill']['observation_timestamp']}")
    print(f"         - Frozen Contract Verified: {list(data['spill'].keys())}")


def main() -> None:
    print("=" * 70)
    print("AQUAGUARD AI - CLASSICAL CV PIPELINE VERIFICATION SUITE")
    print("=" * 70)

    print("\n[1/12] Running 4x Super-Resolution Test...")
    test_4x_super_resolution()

    print("\n[2/12] Running Digital Land Masking & Circularity Filter Test...")
    test_digital_land_masking_and_circularity_filter()

    print("\n[3/12] Running Compact Look-Alike (Algal Bloom) Rejection Test...")
    test_compact_lookalike_rejection()

    print("\n[4/12] Running Timestamp Test 1 (UTC Timestamp)...")
    test_timestamp_1_utc()

    print("\n[5/12] Running Timestamp Test 2 (Z Timestamp)...")
    test_timestamp_2_z()

    print("\n[6/12] Running Timestamp Test 3 (Non-UTC Offset Normalization)...")
    test_timestamp_3_non_utc_offset()

    print("\n[7/12] Running Timestamp Test 4 (Timezone-less Rejection)...")
    test_timestamp_4_timezone_less()

    print("\n[8/12] Running Timestamp Test 5 (Invalid String Rejection)...")
    test_timestamp_5_invalid_string()

    print("\n[9/12] Running Timestamp Test 6 (No Current-Time Substitution)...")
    test_timestamp_6_no_current_time_substitution()

    print("\n[10/12] Running Timestamp Test 7 (Frozen Contract & 4x Georeferencing)...")
    test_frozen_contract_and_georeferencing()

    print("\n[11/12] Running Strict Error State Tests...")
    test_strict_error_states()

    print("\n[12/12] Running FastAPI HTTP Endpoint Tests...")
    test_fastapi_http_endpoint()

    print("\n" + "=" * 70)
    print("ALL VERIFICATION TESTS COMPLETED SUCCESSFULLY (STATUS: PASS)")
    print("=" * 70)


if __name__ == "__main__":
    main()
