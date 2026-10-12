#!/usr/bin/env python3
"""Render data/contributions.json into a terminal-styled contribution heatmap SVG.

Deterministic: the same JSON input always produces byte-identical SVG output
(no timestamps, random ids, or wall-clock values are embedded), which keeps
the daily workflow's diffs meaningful -- a commit only happens when the
underlying data actually changed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_config import load_profile_config  # noqa: E402

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("render_heatmap_svg")

CELL = 11
GAP = 3
STEP = CELL + GAP
WEEKDAY_LABEL_W = 28
MARGIN_TOP = 42
MARGIN_BOTTOM = 42
MARGIN_RIGHT = 16

LEVEL_COLORS = {
    0: "#161b22",
    1: "#0e4429",
    2: "#006d32",
    3: "#26a641",
    4: "#39d353",
}
BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#6e7681"
ACCENT = "#39d353"
BORDER = "#30363d"

MONTH_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


class HeatmapDataError(RuntimeError):
    pass


def load_dataset(path: Path) -> dict:
    if not path.exists():
        raise HeatmapDataError(
            f"{path} does not exist. Run scripts/fetch_contributions.py first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    days = data.get("days")
    if not days or len(days) < 300:
        raise HeatmapDataError(
            f"{path} has too few days ({len(days) if days else 0}); refusing to "
            "render a misleading heatmap."
        )
    return data


def build_week_columns(days: list[dict]) -> list[list[Optional[dict]]]:
    """Group sorted days into Sun-Sat columns, padding the first/last week."""
    ordered = sorted(days, key=lambda d: d["date"])
    first = datetime.strptime(ordered[0]["date"], "%Y-%m-%d").date()
    # Python: Monday=0..Sunday=6. GitHub's grid: Sunday=0..Saturday=6.
    sunday_indexed_weekday = (first.weekday() + 1) % 7

    cells: list[Optional[dict]] = [None] * sunday_indexed_weekday + list(ordered)
    while len(cells) % 7 != 0:
        cells.append(None)

    weeks = [cells[i : i + 7] for i in range(0, len(cells), 7)]
    return weeks


def month_label_positions(weeks: list[list[Optional[dict]]]) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    last_month: Optional[int] = None
    for week_idx, week in enumerate(weeks):
        first_real = next((d for d in week if d is not None), None)
        if first_real is None:
            continue
        d = datetime.strptime(first_real["date"], "%Y-%m-%d").date()
        if d.day <= 7 and d.month != last_month:
            labels.append((week_idx, MONTH_ABBR[d.month - 1]))
            last_month = d.month
    return labels


def render_svg(dataset: dict) -> str:
    cfg = load_profile_config()
    weeks = build_week_columns(dataset["days"])
    n_weeks = len(weeks)
    stats = dataset["stats"]

    grid_w = n_weeks * STEP - GAP
    width = WEEKDAY_LABEL_W + grid_w + MARGIN_RIGHT
    height = MARGIN_TOP + 7 * STEP - GAP + MARGIN_BOTTOM

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="hm-title hm-desc">'
    )
    total = stats["total_contributions"]
    parts.append(
        f'<title id="hm-title">{xml_escape(cfg.github_username)} GitHub contribution heatmap</title>'
    )
    parts.append(
        f'<desc id="hm-desc">{total} contributions in the last year, '
        f'current streak {stats["current_streak_days"]} days, '
        f'longest streak {stats["longest_streak_days"]} days.</desc>'
    )

    parts.append(f"""
<style>
  .hm-bg {{ fill: {BG}; }}
  .hm-mono {{ font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace; }}
  .hm-title {{ fill: {ACCENT}; font-size: 13px; }}
  .hm-muted {{ fill: {MUTED}; font-size: 10px; }}
  .hm-fg {{ fill: {FG}; font-size: 11px; }}
  .hm-cell {{
    opacity: 0;
    transform-box: fill-box;
    transform-origin: center;
    transform: scale(0.4);
    animation: hm-reveal 0.45s ease-out forwards;
  }}
  @keyframes hm-reveal {{
    to {{ opacity: 1; transform: scale(1); }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .hm-cell {{ animation: none; opacity: 1; transform: scale(1); }}
  }}
</style>
""".strip())

    parts.append(f'<rect class="hm-bg" x="0" y="0" width="{width}" height="{height}" rx="6"/>')

    parts.append(
        f'<text class="hm-mono hm-title" x="14" y="20">$ cat contributions.log'
        f' <tspan fill="{FG}">--last-53-weeks</tspan></text>'
    )

    # Month labels
    for week_idx, label in month_label_positions(weeks):
        x = WEEKDAY_LABEL_W + week_idx * STEP
        parts.append(f'<text class="hm-mono hm-muted" x="{x}" y="{MARGIN_TOP - 8}">{label}</text>')

    # Weekday labels (Mon/Wed/Fri, GitHub convention)
    for wd, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = MARGIN_TOP + wd * STEP + CELL - 2
        parts.append(f'<text class="hm-mono hm-muted" x="0" y="{y}">{label}</text>')

    # Cells, diagonal staggered reveal: delay keyed on (week + weekday)
    max_delay_key = n_weeks + 6
    for week_idx, week in enumerate(weeks):
        for wd, day in enumerate(week):
            if day is None:
                continue
            x = WEEKDAY_LABEL_W + week_idx * STEP
            y = MARGIN_TOP + wd * STEP
            level = max(0, min(4, int(day.get("level", 0))))
            color = LEVEL_COLORS[level]
            delay = (week_idx + wd) / max_delay_key * 1.1
            count = day["count"]
            iso = day["date"]
            label = f"{count} contribution{'s' if count != 1 else ''} on {iso}"
            parts.append(
                f'<rect class="hm-cell" x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
                f'rx="2.5" ry="2.5" fill="{color}" style="animation-delay:{delay:.3f}s">'
                f"<title>{xml_escape(label)}</title></rect>"
            )

    # Legend
    legend_y = height - 24
    legend_x = WEEKDAY_LABEL_W
    parts.append(f'<text class="hm-mono hm-muted" x="{legend_x}" y="{legend_y + 8}">Less</text>')
    lx = legend_x + 32
    for level in range(5):
        parts.append(
            f'<rect x="{lx}" y="{legend_y}" width="{CELL}" height="{CELL}" rx="2.5" '
            f'fill="{LEVEL_COLORS[level]}"/>'
        )
        lx += STEP
    parts.append(f'<text class="hm-mono hm-muted" x="{lx + 2}" y="{legend_y + 8}">More</text>')

    footer = f"{total} contributions in the last year  //  current streak {stats['current_streak_days']}d  //  longest {stats['longest_streak_days']}d"
    parts.append(
        f'<text class="hm-mono hm-fg" x="{WEEKDAY_LABEL_W}" y="{height - 6}">{xml_escape(footer)}</text>'
    )

    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--data", default=str(repo_root / "data" / "contributions.json"))
    parser.add_argument("--out", default=str(repo_root / "contrib-heatmap.svg"))
    args = parser.parse_args(argv)

    try:
        dataset = load_dataset(Path(args.data))
        svg = render_svg(dataset)
    except HeatmapDataError as exc:
        log.error("%s", exc)
        return 1

    Path(args.out).write_text(svg, encoding="utf-8")
    log.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
