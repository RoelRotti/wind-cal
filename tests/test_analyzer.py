from datetime import datetime, timedelta, timezone

from analyzer import find_windy_timeslots
from scraper import ForecastPoint

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def pt(hour_offset, duration_hours, wind, gust=None, direction="W"):
    start = T0 + timedelta(hours=hour_offset)
    end = start + timedelta(hours=duration_hours)
    return ForecastPoint(
        start=start,
        end=end,
        wind_avg_kt=wind,
        gust_kt=gust if gust is not None else wind + 2,
        direction=direction,
        model="TEST",
    )


def test_duration_exactly_at_minimum_qualifies():
    points = [pt(0, 1, 20), pt(1, 1, 20), pt(2, 1, 20)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert len(slots) == 1
    assert slots[0].start == points[0].start
    assert slots[0].end == points[-1].end


def test_wind_exactly_at_threshold_qualifies():
    points = [pt(0, 1, 16), pt(1, 1, 16), pt(2, 1, 16), pt(3, 1, 16), pt(4, 1, 16)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert len(slots) == 1
    assert slots[0].avg_wind_kt == 16.0


def test_wind_just_under_threshold_does_not_qualify():
    points = [pt(0, 1, 15.9), pt(1, 1, 15.9), pt(2, 1, 15.9)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert slots == []


def test_too_short_run_does_not_qualify():
    points = [pt(0, 1, 16), pt(1, 1, 16)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert slots == []


def test_sub_threshold_dip_splits_into_two_runs():
    points = [
        pt(0, 1, 16), pt(1, 1, 16), pt(2, 1, 16),
        pt(3, 1, 10),
        pt(4, 1, 16), pt(5, 1, 16), pt(6, 1, 16),
    ]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert len(slots) == 2
    assert slots[0].end == points[2].end
    assert slots[1].start == points[4].start


def test_duration_weighted_average_across_resolution_change():
    p1 = pt(0, 1, 20)  # 1-hour step
    p2 = ForecastPoint(p1.end, p1.end + timedelta(hours=3), 16, 18, "W", "TEST")  # 3-hour step
    p3 = ForecastPoint(p2.end, p2.end + timedelta(hours=3), 16, 18, "W", "TEST")  # 3-hour step
    slots = find_windy_timeslots([p1, p2, p3], min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert len(slots) == 1
    expected_avg = (20 * 1 + 16 * 3 + 16 * 3) / 7
    assert abs(slots[0].avg_wind_kt - expected_avg) < 1e-9
    assert slots[0].end - slots[0].start == timedelta(hours=7)


def test_time_gap_splits_run_even_when_both_sides_qualify():
    p1 = pt(0, 1, 16)
    p2 = ForecastPoint(p1.end, p1.end + timedelta(hours=1), 16, 18, "W", "TEST")
    gap_start = p2.end + timedelta(hours=2)  # 2-hour gap with no data
    p3 = ForecastPoint(gap_start, gap_start + timedelta(hours=1), 16, 18, "W", "TEST")
    p4 = ForecastPoint(p3.end, p3.end + timedelta(hours=1), 16, 18, "W", "TEST")

    slots = find_windy_timeslots([p1, p2, p3, p4], min_avg_wind_kt=16.0, min_duration_hours=2.0)
    assert len(slots) == 2
    assert slots[0].end - slots[0].start == timedelta(hours=2)
    assert slots[1].end - slots[1].start == timedelta(hours=2)
