"""Generate synthetic SAR satellite test fixtures for AquaGuard AI with ship hulls and land masking."""

from pathlib import Path
import cv2
import numpy as np


def generate_synthetic_sar_fixtures() -> None:
    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    np.random.seed(42)

    # 1. Enhanced SAR Image: 500x500 ocean backscatter with:
    #    a) Primary real oil slick: dark rectangle (intensity 35) at y: [210:290], x: [120:380] (260x80 px)
    #    b) Ship hull: bright white metal corner reflector (intensity 255, 5x5 px) at y: [80:85], x: [80:85]
    #    c) Land false positive: dark rectangle (intensity 30, 50x50 px) at corner y: [10:60], x: [10:60]
    enhanced = np.full((500, 500), 195, dtype=np.uint8)
    noise = np.random.normal(0, 3, (500, 500)).astype(np.int16)
    enhanced = np.clip(enhanced.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # Real oil slick
    enhanced[210:290, 120:380] = 35

    # Metal vessel hull (high backscatter, 5x5 px)
    enhanced[80:85, 80:85] = 255

    # Land-based dark false positive patch (50x50 px)
    enhanced[10:60, 10:60] = 30

    enhanced_path = static_dir / "enhanced_sar_001.png"
    cv2.imwrite(str(enhanced_path), enhanced)
    print(f"Created enhanced SAR fixture at: {enhanced_path}")

    # 2. Raw SAR Image: 500x500 with higher speckle noise
    raw = np.full((500, 500), 190, dtype=np.uint8)
    speckle = np.random.normal(0, 12, (500, 500)).astype(np.int16)
    raw = np.clip(raw.astype(np.int16) + speckle, 0, 255).astype(np.uint8)
    raw[210:290, 120:380] = 45
    raw[80:85, 80:85] = 255
    raw[10:60, 10:60] = 35

    raw_path = static_dir / "raw_sar_001.png"
    cv2.imwrite(str(raw_path), raw)
    print(f"Created raw SAR fixture at: {raw_path}")

    # 3. Digital Water/Land Mask: 500x500 binary mask
    #    White (255) = water, Black (0) = land
    #    Black rectangle over the land corner [0:70, 0:70] covering the [10:60, 10:60] false positive
    water_mask = np.full((500, 500), 255, dtype=np.uint8)
    water_mask[0:70, 0:70] = 0

    water_mask_path = static_dir / "water_mask_001.png"
    cv2.imwrite(str(water_mask_path), water_mask)
    print(f"Created digital water/land mask at: {water_mask_path}")

    # 4. Thermal validation fixture
    thermal = np.full((500, 500), 150, dtype=np.uint8)
    thermal[210:290, 120:380] = 80
    thermal_path = static_dir / "thermal_sar_001.png"
    cv2.imwrite(str(thermal_path), thermal)
    print(f"Created thermal validation fixture at: {thermal_path}")


if __name__ == "__main__":
    generate_synthetic_sar_fixtures()
