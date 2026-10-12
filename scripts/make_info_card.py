#!/usr/bin/env python3
"""Generate a neofetch-inspired SVG info card from profile_config.py.

Rows fade in and slide up slightly, staggered to look like a terminal
printing its output. Set STATIC=1 in the environment to disable all
animation (useful for previews/screenshots and for clients that don't
run SVG animation).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_config import ProfileConfig, load_profile_config  # noqa: E402

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("make_info_card")

WIDTH = 760
TITLEBAR_H = 32
PADDING_X = 22
LINE_H = 20
FONT_SIZE = 13
WRAP_CHARS = 54  # characters per value line at FONT_SIZE in the value column

BG = "#0d1117"
TITLEBAR_BG = "#161b22"
BORDER = "#30363d"
FG = "#c9d1d9"
MUTED = "#8b949e"
ACCENT = "#39d353"
DOT_COLORS = ("#ff5f56", "#ffbd2e", "#27c93f")


def wrap_items(items: tuple[str, ...], width: int) -> list[str]:
    joined = ", ".join(items)
    return textwrap.wrap(joined, width=width) or [""]


def build_rows(cfg: ProfileConfig) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = [
        ("user", [f"{cfg.display_name}@github"]),
        ("status", textwrap.wrap(cfg.role, width=WRAP_CHARS) or [cfg.role]),
        ("experience", textwrap.wrap(cfg.experience, width=WRAP_CHARS) or [cfg.experience]),
    ]
    for cat in cfg.tech_categories:
        rows.append((cat.label.lower(), wrap_items(cat.items, WRAP_CHARS)))
    if cfg.highlights:
        rows.append(("projects", list(cfg.highlights)))
    return rows


def render_svg(cfg: ProfileConfig, static: bool) -> str:
    rows = build_rows(cfg)

    label_col_w = max(len(label) for label, _ in rows) * 8 + PADDING_X + 10
    total_lines = sum(len(values) for _, values in rows)
    body_h = total_lines * LINE_H + len(rows) * 6 + 20
    height = TITLEBAR_H + body_h + 16

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="card-title card-desc">'
    )
    parts.append(f'<title id="card-title">{xml_escape(cfg.display_name)} info card</title>')
    parts.append(
        f'<desc id="card-desc">Terminal-style profile card for {xml_escape(cfg.display_name)}: '
        f'{xml_escape(cfg.role)}.</desc>'
    )

    anim_css = "" if static else """
  .row {
    opacity: 0;
    transform: translateY(4px);
    animation: row-in 0.4s ease-out forwards;
  }
  @keyframes row-in {
    to { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .row { animation: none; opacity: 1; transform: none; }
  }
""".rstrip()
    static_css = "" if not static else "\n  .row { opacity: 1; }"

    parts.append(f"""
<style>
  .bg {{ fill: {BG}; }}
  .titlebar {{ fill: {TITLEBAR_BG}; }}
  .border {{ fill: none; stroke: {BORDER}; stroke-width: 1; }}
  .mono {{ font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; font-size: {FONT_SIZE}px; }}
  .label {{ fill: {ACCENT}; font-weight: 600; }}
  .value {{ fill: {FG}; }}
  .muted {{ fill: {MUTED}; }}{anim_css}{static_css}
</style>
""".strip())

    parts.append(f'<rect class="bg" x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="8"/>')
    parts.append(f'<path class="titlebar" d="M0.5,8.5 a8,8 0 0 1 8,-8 h{WIDTH - 17} a8,8 0 0 1 8,8 v{TITLEBAR_H - 8} h-{WIDTH - 1} z"/>')
    for i, color in enumerate(DOT_COLORS):
        parts.append(f'<circle cx="{18 + i * 18}" cy="{TITLEBAR_H / 2}" r="5" fill="{color}"/>')
    parts.append(
        f'<text class="mono muted" x="{WIDTH / 2}" y="{TITLEBAR_H / 2 + 4}" text-anchor="middle">'
        f"whoami.sh</text>"
    )
    parts.append(
        f'<rect class="border" x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="8"/>'
    )
    parts.append(f'<line class="border" x1="0" y1="{TITLEBAR_H}" x2="{WIDTH}" y2="{TITLEBAR_H}"/>')

    y = TITLEBAR_H + 26
    delay_step = 0.0 if static else 0.09
    for row_idx, (label, values) in enumerate(rows):
        delay = row_idx * delay_step
        label_text = f"{label}:"
        for line_idx, value in enumerate(values):
            style = "" if static else f' style="animation-delay:{delay:.3f}s"'
            label_cell = (
                f'<tspan class="label">{xml_escape(label_text)}</tspan>' if line_idx == 0 else ""
            )
            parts.append(
                f'<text class="row mono" x="{PADDING_X}" y="{y}"{style}>'
                f'{label_cell}<tspan class="value" x="{label_col_w}">{xml_escape(value)}</tspan>'
                f"</text>"
            )
            y += LINE_H
        y += 6

    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--out", default=str(repo_root / "info-card.svg"))
    args = parser.parse_args(argv)

    static = os.environ.get("STATIC", "") == "1"
    cfg = load_profile_config()
    svg = render_svg(cfg, static=static)
    Path(args.out).write_text(svg, encoding="utf-8")
    log.info("Wrote %s (static=%s)", args.out, static)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
