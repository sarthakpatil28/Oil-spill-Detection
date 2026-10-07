"""Python native super-resolution fallback client for AquaGuard AI.

Connects to the hosted Hugging Face space 'shivam12119/fire' via gradio_client.Client
to enhance low-resolution SAR satellite imagery, with robust local fallback for offline/isolated environments.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import cv2
from gradio_client import Client, handle_file

logger = logging.getLogger(__name__)

DEFAULT_SPACE = "shivam12119/fire"


def enhance_image(
    image_path: str,
    output_path: str | Path = "static/enhanced_sar_001.png",
    hf_space: str = DEFAULT_SPACE,
    scale: int = 4,
) -> str:
    """Enhance low-resolution SAR image using hosted Gradio Space with fallback.

    Args:
        image_path: Path to the raw SAR satellite image.
        output_path: Destination path for the enhanced image.
        hf_space: Hugging Face space slug (default: "shivam12119/fire").
        scale: Upscale factor (default: 4).

    Returns:
        The output path string of the saved enhanced image.
    """
    input_file = Path(image_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Connecting to Gradio space '%s'...", hf_space)
        client = Client(hf_space)
        result = client.predict(
            image=handle_file(str(input_file)),
            scale=scale,
            api_name="/predict",
        )
        if isinstance(result, (str, Path)) and Path(result).exists():
            shutil.copyfile(result, destination)
            logger.info("Successfully enhanced image via Gradio Space '%s'", hf_space)
            return str(destination)
        elif isinstance(result, (tuple, list)) and len(result) > 0 and Path(result[0]).exists():
            shutil.copyfile(result[0], destination)
            logger.info("Successfully enhanced image via Gradio Space '%s'", hf_space)
            return str(destination)
    except Exception as exc:
        logger.warning(
            "External Gradio space '%s' unavailable (%s). Applying local enhancement fallback.",
            hf_space,
            exc,
        )

    # Local fallback enhancement: bicubic upscaling and unsharp contrast sharpening
    img = cv2.imread(str(input_file), cv2.IMREAD_GRAYSCALE)
    if img is not None:
        h, w = img.shape[:2]
        upscaled = cv2.resize(
            img,
            (w * scale, h * scale),
            interpolation=cv2.INTER_CUBIC,
        )
        gaussian = cv2.GaussianBlur(upscaled, (0, 0), 2.0)
        sharpened = cv2.addWeighted(upscaled, 1.5, gaussian, -0.5, 0)
        cv2.imwrite(str(destination), sharpened)
        logger.info("Enhanced image created via local OpenCV fallback at %s", destination)
    else:
        shutil.copyfile(input_file, destination)

    return str(destination)
