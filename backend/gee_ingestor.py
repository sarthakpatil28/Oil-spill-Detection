"""Download server-cropped Sentinel-1 imagery using Google Earth Engine."""

from pathlib import Path

import ee
import requests


def download_sentinel1_png(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    output_path: str = "static/live_sar_001.png",
) -> str:
    """Download the latest Sentinel-1 VV/IW thumbnail for a bounding box."""
    try:
        ee.Initialize(project='aquaguard-ai-510902')
    except ee.EEException as exc:
        raise RuntimeError(
            "Google Earth Engine is not authenticated. Run "
            "`earthengine authenticate` and try again."
        ) from exc

    region = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
    collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(region)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .sort("system:time_start", False)
    )
    image = ee.Image(collection.first())
    thumbnail_url = image.getThumbURL(
        {
            "region": region,
            "dimensions": 512,
            "min": -25,
            "max": 0,
            "format": "png",
        }
    )

    response = requests.get(thumbnail_url, timeout=60)
    response.raise_for_status()

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return str(destination)


if __name__ == "__main__":
    output_file = download_sentinel1_png(71.2, 19.3, 71.6, 19.7)
    print(f"Downloaded Sentinel-1 thumbnail to {output_file}")
