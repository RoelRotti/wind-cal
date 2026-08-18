from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scraper import ScraperParseError, ScraperUnitMismatchError, parse_forecast

FIXTURE = Path(__file__).parent / "fixtures" / "sample_response.txt"
AMS = ZoneInfo("Europe/Amsterdam")


def test_parses_fixture_into_points():
    points = parse_forecast(FIXTURE.read_text(), AMS)
    assert len(points) > 100
    first = points[0]
    assert first.model == "GFS 13 km"
    assert first.wind_avg_kt == 17.0
    assert first.gust_kt == 19.0
    assert first.direction == "W"


def test_points_are_sorted_ascending():
    points = parse_forecast(FIXTURE.read_text(), AMS)
    for a, b in zip(points, points[1:]):
        assert a.start < b.start


def test_month_rollover_handled():
    points = parse_forecast(FIXTURE.read_text(), AMS)
    months = {p.start.month for p in points}
    assert 8 in months and 9 in months  # fixture spans Aug -> Sep


def test_missing_pre_block_raises_parse_error():
    with pytest.raises(ScraperParseError):
        parse_forecast("<html><body>nothing here</body></html>", AMS)


def test_missing_knots_label_raises_unit_mismatch():
    html = (
        "<pre>GFS 13 km (init: 2026-01-01 00 UTC)\n"
        "Date WSPD\n(UTC+1) km/h\n Wed 1. 00h 10\n</pre>"
    )
    with pytest.raises(ScraperUnitMismatchError):
        parse_forecast(html, AMS)
