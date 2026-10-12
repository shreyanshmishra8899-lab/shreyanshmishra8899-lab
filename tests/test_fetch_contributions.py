from datetime import date, timedelta

import pytest

from fetch_contributions import (
    ContributionFetchError,
    Day,
    compute_stats,
    parse_html,
)


def _make_contribution_html(day_counts: dict[str, int]) -> str:
    """Builds a minimal fragment that mimics GitHub's real markup closely
    enough for parse_html(): a <td data-date data-level> per day plus a
    matching <tool-tip for=...> with the human-readable count, and an <h2>
    with the yearly total -- the same shapes observed on
    https://github.com/users/<name>/contributions.
    """
    cells = []
    tooltips = []
    total = 0
    for i, (iso_date, count) in enumerate(sorted(day_counts.items())):
        cell_id = f"contribution-day-component-0-{i}"
        level = 0 if count == 0 else min(4, (count // 2) + 1)
        cells.append(
            f'<td class="ContributionCalendar-day" data-date="{iso_date}" '
            f'data-level="{level}" id="{cell_id}"></td>'
        )
        d = date.fromisoformat(iso_date)
        pretty = f"{d.strftime('%B')} {d.day}"
        if count == 0:
            text = f"No contributions on {pretty}."
        else:
            noun = "contribution" if count == 1 else "contributions"
            text = f"{count} {noun} on {pretty}."
            total += count
        tooltips.append(f'<tool-tip for="{cell_id}">{text}</tool-tip>')

    return f"""
    <html><body>
    <h2>{total} contributions in the last year</h2>
    <table>{''.join(cells)}</table>
    {''.join(tooltips)}
    </body></html>
    """


def _year_of_days(start: date, n: int, pattern: dict[int, int] | None = None) -> dict[str, int]:
    pattern = pattern or {}
    out = {}
    for i in range(n):
        d = start + timedelta(days=i)
        out[d.isoformat()] = pattern.get(i, 0)
    return out


class TestParseHtml:
    def test_valid_page_parses_all_days(self):
        days_map = _year_of_days(date(2025, 1, 1), 365, {10: 3, 11: 1, 12: 5})
        html = _make_contribution_html(days_map)
        days, total = parse_html(html)
        assert len(days) == 365
        assert total == 9
        by_date = {d.date: d for d in days}
        assert by_date["2025-01-11"].count == 3
        assert by_date["2025-01-11"].level >= 1
        assert by_date["2025-01-01"].count == 0

    def test_too_few_day_cells_raises(self):
        html = _make_contribution_html(_year_of_days(date(2025, 1, 1), 50))
        with pytest.raises(ContributionFetchError, match="only found"):
            parse_html(html)

    def test_malformed_html_missing_table_raises(self):
        with pytest.raises(ContributionFetchError):
            parse_html("<html><body>GitHub changed everything</body></html>")

    def test_days_are_sorted_ascending(self):
        days_map = _year_of_days(date(2025, 1, 1), 320)
        html = _make_contribution_html(days_map)
        days, _ = parse_html(html)
        dates = [d.date for d in days]
        assert dates == sorted(dates)


class TestComputeStats:
    def test_current_and_longest_streak(self):
        # 5 non-zero, 1 zero, 3 non-zero (ending the series)
        counts = [2, 1, 1, 1, 3, 0, 1, 1, 4]
        start = date(2025, 1, 1)
        days = [
            Day(date=(start + timedelta(days=i)).isoformat(), count=c, level=min(4, c))
            for i, c in enumerate(counts)
        ]
        stats = compute_stats(days)
        assert stats["longest_streak_days"] == 5
        assert stats["current_streak_days"] == 3
        assert stats["total_contributions"] == sum(counts)
        assert stats["best_day"]["count"] == 4

    def test_current_streak_ignores_unfinished_today(self):
        # Last day (today) has 0 -- shouldn't zero out an active streak.
        start = date(2025, 1, 1)
        counts = [1, 1, 1, 0]
        days = [
            Day(date=(start + timedelta(days=i)).isoformat(), count=c, level=min(4, c))
            for i, c in enumerate(counts)
        ]
        stats = compute_stats(days)
        assert stats["current_streak_days"] == 3

    def test_all_zero_days_gives_zero_streaks(self):
        start = date(2025, 1, 1)
        days = [
            Day(date=(start + timedelta(days=i)).isoformat(), count=0, level=0)
            for i in range(10)
        ]
        stats = compute_stats(days)
        assert stats["current_streak_days"] == 0
        assert stats["longest_streak_days"] == 0

    def test_empty_days_raises(self):
        with pytest.raises(ContributionFetchError):
            compute_stats([])

    def test_monthly_totals_grouped_by_month(self):
        days = [
            Day(date="2025-01-30", count=2, level=1),
            Day(date="2025-01-31", count=3, level=1),
            Day(date="2025-02-01", count=5, level=2),
        ]
        stats = compute_stats(days)
        assert stats["monthly_totals"]["2025-01"] == 5
        assert stats["monthly_totals"]["2025-02"] == 5
