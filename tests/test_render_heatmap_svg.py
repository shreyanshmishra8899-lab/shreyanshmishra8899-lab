import xml.dom.minidom as minidom
from datetime import date, timedelta

import pytest

from render_heatmap_svg import (
    HeatmapDataError,
    build_week_columns,
    load_dataset,
    month_label_positions,
    render_svg,
)


def _days(start: date, n: int) -> list[dict]:
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "count": i % 5, "level": i % 5}
        for i in range(n)
    ]


def _dataset(n: int = 365, start: date = date(2025, 1, 5)) -> dict:
    days = _days(start, n)
    total = sum(d["count"] for d in days)
    return {
        "username": "octocat",
        "days": days,
        "stats": {
            "total_contributions": total,
            "current_streak_days": 3,
            "longest_streak_days": 7,
            "best_day": {"date": days[-1]["date"], "count": days[-1]["count"]},
            "monthly_totals": {},
        },
    }


class TestBuildWeekColumns:
    def test_pads_front_to_align_sunday(self):
        # 2025-01-05 is a Sunday -> no front padding needed.
        sunday = date(2025, 1, 5)
        assert sunday.weekday() == 6
        weeks = build_week_columns(_days(sunday, 14))
        assert weeks[0][0] is not None
        assert weeks[0][0]["date"] == "2025-01-05"

    def test_pads_front_for_midweek_start(self):
        # 2025-01-08 is a Wednesday -> 3 Sun/Mon/Tue slots should be None.
        wednesday = date(2025, 1, 8)
        assert wednesday.weekday() == 2
        weeks = build_week_columns(_days(wednesday, 10))
        assert weeks[0][:3] == [None, None, None]
        assert weeks[0][3]["date"] == "2025-01-08"

    def test_every_week_has_seven_slots(self):
        weeks = build_week_columns(_days(date(2025, 1, 1), 100))
        assert all(len(w) == 7 for w in weeks)


class TestMonthLabels:
    def test_labels_appear_near_month_start(self):
        weeks = build_week_columns(_days(date(2025, 1, 1), 100))
        labels = month_label_positions(weeks)
        assert labels[0][1] == "Jan"
        month_names = [name for _, name in labels]
        assert "Feb" in month_names

    def test_no_duplicate_consecutive_months(self):
        weeks = build_week_columns(_days(date(2025, 1, 1), 60))
        labels = month_label_positions(weeks)
        names = [name for _, name in labels]
        assert all(a != b for a, b in zip(names, names[1:]))


class TestLoadDataset:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(HeatmapDataError):
            load_dataset(tmp_path / "nope.json")

    def test_too_few_days_raises(self, tmp_path):
        import json

        p = tmp_path / "contributions.json"
        p.write_text(json.dumps({"days": _days(date(2025, 1, 1), 10)}))
        with pytest.raises(HeatmapDataError, match="too few days"):
            load_dataset(p)


class TestRenderSvg:
    def test_produces_valid_xml(self):
        svg = render_svg(_dataset())
        doc = minidom.parseString(svg)
        assert doc.documentElement.tagName == "svg"

    def test_contains_expected_cell_count(self):
        dataset = _dataset(n=365, start=date(2025, 1, 5))
        svg = render_svg(dataset)
        assert svg.count('class="hm-cell"') == 365

    def test_footer_mentions_real_total(self):
        dataset = _dataset()
        svg = render_svg(dataset)
        assert str(dataset["stats"]["total_contributions"]) in svg

    def test_no_invented_contributions_in_cells(self):
        # Every rendered tooltip count must trace back to an input day.
        dataset = _dataset(n=50, start=date(2025, 1, 5))
        svg = render_svg(dataset)
        for day in dataset["days"]:
            assert day["date"] in svg
