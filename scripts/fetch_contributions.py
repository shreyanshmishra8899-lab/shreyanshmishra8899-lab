#!/usr/bin/env python3
"""Fetch a GitHub user's public contribution calendar and save it as JSON.

Primary source: the public, unauthenticated HTML fragment GitHub serves at
``https://github.com/users/<username>/contributions``. This is the same
markup GitHub's own profile page renders client-side, so it reflects real
data with no token required -- but it is unversioned HTML we don't control,
so every field we depend on is validated before anything is written.

Fallback: if a ``GH_CONTRIB_TOKEN`` (or ``GITHUB_TOKEN``) environment
variable is present, the authenticated GraphQL API
(``contributionsCollection.contributionCalendar``) is used instead. It is
more stable across GitHub frontend changes and is the recommended path for
the scheduled workflow once a token is available; see README.md for how to
add one as a repository secret. No token is required for this script to
work, and none is ever written to disk.

Either way, a fetch/parse failure NEVER overwrites a previously saved,
valid ``data/contributions.json`` -- the old file is left untouched and the
script exits non-zero so the workflow step can be inspected.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_config import load_profile_config  # noqa: E402

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(levelname)s %(message)s",
)
log = logging.getLogger("fetch_contributions")

HTML_URL = "https://github.com/users/{username}/contributions"
GRAPHQL_URL = "https://api.github.com/graphql"
REQUEST_TIMEOUT = 20
MIN_EXPECTED_DAYS = 300  # a full year is ~365; tolerate partial history


class ContributionFetchError(RuntimeError):
    """Raised when contribution data cannot be reliably obtained."""


@dataclass(frozen=True)
class Day:
    date: str  # ISO yyyy-mm-dd
    count: int
    level: int  # 0-4 intensity, as GitHub buckets it


# --------------------------------------------------------------------------
# HTML scrape (no auth required)
# --------------------------------------------------------------------------

_COUNT_RE = re.compile(r"([\d,]+)\s+contributions?\s+on", re.IGNORECASE)
_NO_CONTRIB_RE = re.compile(r"No contributions on", re.IGNORECASE)
_TOTAL_RE = re.compile(r"([\d,]+)\s*\n?\s*contributions?\s+in the last year", re.IGNORECASE)


def fetch_html(username: str, session: Optional[requests.Session] = None) -> str:
    sess = session or requests.Session()
    url = HTML_URL.format(username=username)
    headers = {"User-Agent": "profile-readme-contrib-fetcher/1.0 (+github actions)"}
    try:
        resp = sess.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout as exc:
        raise ContributionFetchError(f"Timed out requesting {url}") from exc
    except requests.exceptions.RequestException as exc:
        raise ContributionFetchError(f"Network error requesting {url}: {exc}") from exc

    if resp.status_code == 404:
        raise ContributionFetchError(
            f"GitHub returned 404 for '{username}'. Is the username correct "
            "and does the account have a public profile?"
        )
    if resp.status_code == 429:
        raise ContributionFetchError(
            "GitHub rate-limited the anonymous contributions request (HTTP 429). "
            "Retry later, or set GH_CONTRIB_TOKEN to use the GraphQL fallback."
        )
    if resp.status_code != 200:
        raise ContributionFetchError(
            f"Unexpected HTTP {resp.status_code} fetching {url}"
        )
    if not resp.text or len(resp.text) < 500:
        raise ContributionFetchError("Contributions page response was empty or truncated")
    return resp.text


def parse_html(html: str) -> tuple[list[Day], Optional[int]]:
    soup = BeautifulSoup(html, "html.parser")

    day_cells = soup.find_all("td", attrs={"data-date": True})
    if len(day_cells) < MIN_EXPECTED_DAYS:
        raise ContributionFetchError(
            "Expected GitHub's contribution calendar markup (<td data-date=...>) "
            f"but only found {len(day_cells)} day cells (need >= {MIN_EXPECTED_DAYS}). "
            "GitHub likely changed its HTML structure -- update the parser in "
            "scripts/fetch_contributions.py, or set GH_CONTRIB_TOKEN to use the "
            "GraphQL fallback instead."
        )

    tooltip_text_by_id: dict[str, str] = {}
    for tip in soup.find_all("tool-tip"):
        target_id = tip.get("for")
        if target_id:
            tooltip_text_by_id[target_id] = tip.get_text(strip=True)

    days: list[Day] = []
    missing_level = 0
    for cell in day_cells:
        iso_date = cell.get("data-date")
        cell_id = cell.get("id")
        level_raw = cell.get("data-level")
        if level_raw is None:
            missing_level += 1
            level = 0
        else:
            try:
                level = int(level_raw)
            except ValueError:
                level = 0

        count = 0
        tooltip = tooltip_text_by_id.get(cell_id, "") if cell_id else ""
        if tooltip and not _NO_CONTRIB_RE.search(tooltip):
            m = _COUNT_RE.search(tooltip)
            if m:
                count = int(m.group(1).replace(",", ""))
        elif cell.get("aria-label") and "no contributions" not in cell["aria-label"].lower():
            m = _COUNT_RE.search(cell["aria-label"])
            if m:
                count = int(m.group(1).replace(",", ""))

        days.append(Day(date=iso_date, count=count, level=level))

    if missing_level > len(days) * 0.5:
        raise ContributionFetchError(
            "More than half of day cells are missing a 'data-level' attribute; "
            "treating this as an unreliable/changed page structure."
        )

    days.sort(key=lambda d: d.date)

    total: Optional[int] = None
    m = _TOTAL_RE.search(soup.get_text(" ", strip=False))
    if m:
        total = int(m.group(1).replace(",", ""))

    return days, total


# --------------------------------------------------------------------------
# GraphQL fallback (requires a token with no special scopes)
# --------------------------------------------------------------------------

_GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            color
          }
        }
      }
    }
  }
}
"""


def fetch_via_graphql(username: str, token: str) -> tuple[list[Day], Optional[int]]:
    headers = {"Authorization": f"bearer {token}"}
    try:
        resp = requests.post(
            GRAPHQL_URL,
            json={"query": _GRAPHQL_QUERY, "variables": {"login": username}},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise ContributionFetchError(f"GraphQL request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ContributionFetchError(
            f"GraphQL API returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    payload = resp.json()
    if payload.get("errors"):
        raise ContributionFetchError(f"GraphQL API errors: {payload['errors']}")

    try:
        calendar = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        weeks = calendar["weeks"]
        total = calendar["totalContributions"]
    except (KeyError, TypeError) as exc:
        raise ContributionFetchError(
            f"Unexpected GraphQL response shape: missing {exc}"
        ) from exc

    flat: list[tuple[str, int, str]] = []
    for week in weeks:
        for d in week["contributionDays"]:
            flat.append((d["date"], d["contributionCount"], d["color"]))

    if len(flat) < MIN_EXPECTED_DAYS:
        raise ContributionFetchError(
            f"GraphQL returned only {len(flat)} days (need >= {MIN_EXPECTED_DAYS})"
        )

    # GitHub's GraphQL API returns a per-day hex `color` rather than an
    # explicit 0-4 level. Levels are derived by ranking the distinct
    # non-zero colors that actually appear (darkest = highest level),
    # which matches GitHub's own calendar regardless of the viewer's
    # light/dark palette.
    distinct_colors = sorted({c for _, cnt, c in flat if cnt > 0})
    color_rank = {c: i + 1 for i, c in enumerate(distinct_colors)}
    max_rank = max(color_rank.values()) if color_rank else 0

    days = []
    for iso_date, count, color in flat:
        if count == 0:
            level = 0
        elif max_rank <= 4:
            level = color_rank[color]
        else:
            # More than 4 distinct shades (rare): rescale into 1-4.
            level = max(1, round(color_rank[color] / max_rank * 4))
        days.append(Day(date=iso_date, count=count, level=level))

    days.sort(key=lambda d: d.date)
    return days, total


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------


def compute_stats(days: list[Day]) -> dict:
    if not days:
        raise ContributionFetchError("No contribution days to compute stats from")

    total = sum(d.count for d in days)

    # Longest streak: longest run of consecutive calendar days with count > 0.
    longest = 0
    running = 0
    prev_date: Optional[date] = None
    for d in days:
        cur_date = datetime.strptime(d.date, "%Y-%m-%d").date()
        if d.count > 0:
            if prev_date is not None and cur_date == prev_date + timedelta(days=1):
                running += 1
            else:
                running = 1
            longest = max(longest, running)
        else:
            running = 0
        prev_date = cur_date

    # Current streak: consecutive non-zero days ending at the most recent
    # day. If the very last day has 0 contributions, it may simply be "not
    # over yet" in the user's timezone, so we start counting from the day
    # before it instead of treating the streak as broken by that day alone.
    ordered = sorted(days, key=lambda d: d.date)
    end_idx = len(ordered) - 1
    if ordered[end_idx].count == 0:
        end_idx -= 1
    current = 0
    idx = end_idx
    prev_date = None
    while idx >= 0 and ordered[idx].count > 0:
        cur_date = datetime.strptime(ordered[idx].date, "%Y-%m-%d").date()
        if prev_date is None or prev_date - cur_date == timedelta(days=1):
            current += 1
            prev_date = cur_date
            idx -= 1
        else:
            break

    best = max(days, key=lambda d: (d.count, d.date))

    monthly: dict[str, int] = {}
    for d in days:
        key = d.date[:7]  # YYYY-MM
        monthly[key] = monthly.get(key, 0) + d.count

    return {
        "total_contributions": total,
        "current_streak_days": current,
        "longest_streak_days": longest,
        "best_day": {"date": best.date, "count": best.count},
        "monthly_totals": monthly,
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def build_dataset(username: str, token: Optional[str]) -> dict:
    source = "html"
    total_from_page: Optional[int] = None

    if token:
        log.info("GH_CONTRIB_TOKEN present; using authenticated GraphQL API")
        days, total_from_page = fetch_via_graphql(username, token)
        source = "graphql"
    else:
        log.info("No token found; using anonymous HTML scrape")
        html = fetch_html(username)
        days, total_from_page = parse_html(html)

    stats = compute_stats(days)

    if total_from_page is not None and abs(total_from_page - stats["total_contributions"]) > 2:
        log.warning(
            "Parsed day counts sum to %d but the page reports %d contributions; "
            "keeping the summed value and flagging the discrepancy.",
            stats["total_contributions"],
            total_from_page,
        )

    return {
        "username": username,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "days": [asdict(d) for d in days],
        "stats": stats,
    }


def save_dataset(dataset: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(out_path)  # atomic on both POSIX and Windows


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=None, help="GitHub username to fetch")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "data" / "contributions.json"),
        help="Output JSON path (default: data/contributions.json)",
    )
    args = parser.parse_args(argv)

    cfg = load_profile_config()
    username = args.username or cfg.github_username
    token = os.environ.get("GH_CONTRIB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    out_path = Path(args.out)

    try:
        dataset = build_dataset(username, token)
    except ContributionFetchError as exc:
        log.error("Fetch failed, leaving existing data untouched: %s", exc)
        return 1

    save_dataset(dataset, out_path)
    log.info(
        "Saved %d days (%d total contributions, current streak %d, longest %d) -> %s",
        len(dataset["days"]),
        dataset["stats"]["total_contributions"],
        dataset["stats"]["current_streak_days"],
        dataset["stats"]["longest_streak_days"],
        out_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
