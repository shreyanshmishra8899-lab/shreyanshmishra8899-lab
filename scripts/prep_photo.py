#!/usr/bin/env python3
"""Preprocess a source photograph for the ASCII-portrait pipeline.

Pipeline: background removal (rembg) -> grayscale -> CLAHE contrast
enhancement (OpenCV) -> composite onto pure white -> resize.

This script and `rembg`/`opencv-python` are intentionally kept out of the
daily GitHub Actions workflow (see .github/workflows/update-profile-art.yml)
-- they're only needed when a human regenerates the portrait locally.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("prep_photo")


class PhotoPrepError(RuntimeError):
    pass


# A human-segmentation-specific model: smaller (~176MB) and more reliable
# to download than rembg's current general-purpose default (bria-rmbg,
# ~1GB, which repeatedly times out on slow/flaky connections), and better
# suited to a single-subject portrait than a generic matting model.
REMBG_MODEL = "u2net_human_seg"


def remove_background(image: Image.Image) -> Image.Image:
    """Returns an RGBA image with the subject cut out, or raises PhotoPrepError.

    rembg's first run downloads an ONNX model to ~/.u2net -- this can fail
    with no internet access, a corporate proxy, disk space issues, or (as
    observed with rembg's current default model) a slow/unreliable download.
    Callers should catch PhotoPrepError and fall back to using the original
    image uncut (see `main`).
    """
    try:
        from rembg import new_session, remove  # local import: heavy, optional dependency
    except ImportError as exc:
        raise PhotoPrepError(
            "rembg is not installed. Install scripts/requirements.txt, "
            "or rerun with --no-bg-removal to skip this step."
        ) from exc

    try:
        session = new_session(REMBG_MODEL)
        result = remove(image, session=session)
    except Exception as exc:  # noqa: BLE001 - rembg can raise many error types
        raise PhotoPrepError(
            f"Background removal failed ({exc.__class__.__name__}: {exc}). "
            "This is often a one-time model download issue -- check network "
            "access, or rerun with --no-bg-removal."
        ) from exc

    if result.mode != "RGBA":
        result = result.convert("RGBA")
    return result


def enhance_contrast_grayscale(rgba: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Returns (enhanced_gray_uint8, alpha_mask_uint8), both HxW arrays."""
    arr = np.array(rgba)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3] if arr.shape[2] == 4 else np.full(arr.shape[:2], 255, dtype=np.uint8)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return enhanced, alpha


def composite_on_white(gray: np.ndarray, alpha: np.ndarray) -> Image.Image:
    white = np.full_like(gray, 255)
    alpha_f = alpha.astype(np.float32) / 255.0
    composited = (gray.astype(np.float32) * alpha_f + white.astype(np.float32) * (1 - alpha_f))
    return Image.fromarray(composited.astype(np.uint8), mode="L")


def resize_keep_aspect(img: Image.Image, target_width: int) -> Image.Image:
    w, h = img.size
    if w == 0:
        raise PhotoPrepError("Source image has zero width")
    new_h = max(1, round(h * (target_width / w)))
    return img.resize((target_width, new_h), Image.LANCZOS)


def prep_photo(
    source: Path,
    target_width: int = 900,
    skip_bg_removal: bool = False,
) -> Image.Image:
    if not source.exists():
        raise PhotoPrepError(f"Source photo not found: {source}")

    original = Image.open(source).convert("RGB")

    if skip_bg_removal:
        log.info("Skipping background removal (--no-bg-removal)")
        rgba = original.convert("RGBA")
    else:
        try:
            rgba = remove_background(original)
        except PhotoPrepError as exc:
            log.warning("%s -- continuing without background removal.", exc)
            rgba = original.convert("RGBA")

    gray, alpha = enhance_contrast_grayscale(rgba)
    composited = composite_on_white(gray, alpha)
    resized = resize_keep_aspect(composited, target_width)
    return resized


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Path to the source photograph")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "source-prepped.png"),
        help="Output PNG path (default: source-prepped.png, git-ignored)",
    )
    parser.add_argument("--width", type=int, default=900, help="Target width in pixels")
    parser.add_argument(
        "--no-bg-removal", action="store_true", help="Skip rembg background removal"
    )
    args = parser.parse_args(argv)

    try:
        result = prep_photo(Path(args.source), args.width, args.no_bg_removal)
    except PhotoPrepError as exc:
        log.error("%s", exc)
        return 1

    out_path = Path(args.out)
    result.save(out_path)
    log.info("Saved prepped photo (%dx%d) -> %s", *result.size, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
