from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scraper import ForecastPoint, ScraperParseError, ScraperUnitMismatchError, merge_forecasts, parse_forecast

FIXTURE = Path(__file__).parent / "fixtures" / "sample_response.txt"
AMS = ZoneInfo("Europe/Amsterdam")
T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def pt(hour_offset, duration_hours, model, wind=15.0):
    start = T0 + timedelta(hours=hour_offset)
    end = start + timedelta(hours=duration_hours)
    return ForecastPoint(start=start, end=end, wind_avg_kt=wind, gust_kt=wind + 2, direction="W", model=model)


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


def test_merge_uses_primary_then_switches_to_fallback_after_its_horizon():
    primary = [pt(0, 1, "HARM-NL 2 km"), pt(1, 1, "HARM-NL 2 km")]  # covers hours 0-2
    fallback = [pt(0, 1, "GFS 13 km"), pt(1, 1, "GFS 13 km"), pt(2, 1, "GFS 13 km"), pt(3, 1, "GFS 13 km")]

    merged = merge_forecasts(primary, fallback)

    assert [p.model for p in merged] == ["HARM-NL 2 km", "HARM-NL 2 km", "GFS 13 km", "GFS 13 km"]
    assert merged[2].start == primary[-1].end  # fallback picks up exactly where primary ends


def test_merge_with_empty_primary_returns_fallback_only():
    fallback = [pt(0, 1, "GFS 13 km")]
    assert merge_forecasts([], fallback) == fallback


def test_merge_with_empty_fallback_returns_primary_only():
    primary = [pt(0, 1, "HARM-NL 2 km")]
    assert merge_forecasts(primary, []) == primary
