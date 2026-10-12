#!/usr/bin/env python3
"""Convert a preprocessed photo (see prep_photo.py) into an animated ASCII SVG.

Each pixel block of the source image is mapped to a character from a
brightness-to-density ramp, then rendered as monospace <text> rows. Rows
reveal left-to-right in a staggered sequence via CSS animation and settle
into a complete, static portrait (the animation does not loop).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("make_ascii_svg")

# Dark-to-light density ramp; index chosen by pixel brightness.
RAMP = " .`:-=+*cs#%@"

# Typical monospace glyphs are taller than they are wide (~0.5 aspect).
# This corrects row sampling so the ASCII portrait isn't vertically
# stretched relative to the source photo.
CHAR_ASPECT = 0.5

BG = "#0d1117"
FG = "#39d353"


class AsciiSvgError(RuntimeError):
    pass


def image_to_ascii_grid(img: Image.Image, columns: int) -> list[str]:
    if columns < 10:
        raise AsciiSvgError("columns must be >= 10")

    gray = img.convert("L")
    w, h = gray.size
    cell_w = w / columns
    cell_h = cell_w / CHAR_ASPECT
    rows = max(1, round(h / cell_h))

    arr = np.array(gray, dtype=np.float32)
    grid: list[str] = []
    ramp_len = len(RAMP)
    for r in range(rows):
        y0 = int(r * cell_h)
        y1 = max(y0 + 1, int((r + 1) * cell_h))
        row_chars = []
        for c in range(columns):
            x0 = int(c * cell_w)
            x1 = max(x0 + 1, int((c + 1) * cell_w))
            block = arr[y0:y1, x0:x1]
            brightness = float(block.mean()) if block.size else 255.0
            # Dark pixel (low brightness) -> dense glyph; invert index.
            idx = int((1.0 - brightness / 255.0) * (ramp_len - 1))
            idx = max(0, min(ramp_len - 1, idx))
            row_chars.append(RAMP[idx])
        grid.append("".join(row_chars))
    return grid


def _xml_escape_char(ch: str) -> str:
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(ch, ch)


def render_svg(
    grid: list[str],
    font_size: float = 9.0,
    stagger_seconds: float = 0.012,
    row_duration: float = 0.35,
) -> str:
    if not grid:
        raise AsciiSvgError("Empty ASCII grid")

    columns = len(grid[0])
    rows = len(grid)
    char_w = font_size * 0.6
    char_h = font_size * (1.0 / CHAR_ASPECT) * 0.6
    width = round(columns * char_w + 20)
    height = round(rows * char_h + 20)

    total_duration = rows * stagger_seconds + row_duration

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="ascii-title">'
    )
    parts.append('<title id="ascii-title">ASCII portrait</title>')
    parts.append(f"""
<style>
  .ascii-bg {{ fill: {BG}; }}
  .ascii-row {{
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    font-size: {font_size}px;
    fill: {FG};
    white-space: pre;
    opacity: 0;
    animation: ascii-type {row_duration}s steps(1, end) forwards;
  }}
  @keyframes ascii-type {{
    0% {{ opacity: 0; }}
    1% {{ opacity: 1; }}
    100% {{ opacity: 1; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .ascii-row {{ animation: none; opacity: 1; }}
  }}
</style>
""".strip())
    parts.append(f'<rect class="ascii-bg" x="0" y="0" width="{width}" height="{height}" rx="6"/>')

    for i, row in enumerate(grid):
        y = 16 + i * char_h
        delay = i * stagger_seconds
        escaped = "".join(_xml_escape_char(c) for c in row)
        parts.append(
            f'<text class="ascii-row" x="10" y="{y:.2f}" '
            f'style="animation-delay:{delay:.3f}s" xml:space="preserve">{escaped}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--source",
        default=str(repo_root / "source-prepped.png"),
        help="Preprocessed input image (see prep_photo.py)",
    )
    parser.add_argument("--out", default=str(repo_root / "avi-ascii.svg"))
    parser.add_argument("--columns", type=int, default=100, help="Character grid width")
    parser.add_argument("--speed", type=float, default=0.012, help="Per-row reveal delay (s)")
    args = parser.parse_args(argv)

    source_path = Path(args.source)
    if not source_path.exists():
        log.error(
            "%s not found. Run scripts/prep_photo.py first (see README 'ASCII portrait').",
            source_path,
        )
        return 1

    img = Image.open(source_path)
    try:
        grid = image_to_ascii_grid(img, args.columns)
        svg = render_svg(grid, stagger_seconds=args.speed)
    except AsciiSvgError as exc:
        log.error("%s", exc)
        return 1

    Path(args.out).write_text(svg, encoding="utf-8")
    log.info("Wrote %s (%d cols x %d rows)", args.out, args.columns, len(grid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
