from datetime import datetime, timedelta, timezone

from analyzer import find_windy_timeslots
from scraper import ForecastPoint

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def pt(hour_offset, duration_hours, wind, gust=None, direction="W", model="TEST", rain_mm=0.0, cloud_cover_pct=None):
    start = T0 + timedelta(hours=hour_offset)
    end = start + timedelta(hours=duration_hours)
    return ForecastPoint(
        start=start,
        end=end,
        wind_avg_kt=wind,
        gust_kt=gust if gust is not None else wind + 2,
        direction=direction,
        model=model,
        rain_mm=rain_mm,
        cloud_cover_pct=cloud_cover_pct,
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


def test_lone_three_hour_block_at_threshold_does_not_qualify():
    # A single GFS-resolution (3-hour) point spans only 3 real hours, which is
    # under the 4-hour minimum even though its wind meets the threshold alone.
    points = [pt(0, 3, 15)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=15.0, min_duration_hours=4.0)
    assert slots == []


def test_total_rain_mm_sums_across_the_run():
    points = [pt(0, 1, 18, rain_mm=0.5), pt(1, 1, 18, rain_mm=1.2), pt(2, 1, 18, rain_mm=0.0)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert slots[0].total_rain_mm == 1.7


def test_avg_cloud_cover_is_duration_weighted_and_skips_missing():
    p1 = pt(0, 1, 18, cloud_cover_pct=100.0)      # 1-hour step
    p2 = ForecastPoint(p1.end, p1.end + timedelta(hours=3), 18, 20, "W", "TEST", 0.0, 0.0)  # 3-hour step, 0% cloud
    p3 = ForecastPoint(p2.end, p2.end + timedelta(hours=1), 18, 20, "W", "TEST", 0.0, None)  # missing -> excluded

    slots = find_windy_timeslots([p1, p2, p3], min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert len(slots) == 1
    # weighted by duration: (100*1 + 0*3) / (1+3) = 25, the missing point contributes nothing
    assert slots[0].avg_cloud_cover_pct == 25.0


def test_avg_cloud_cover_is_none_when_entirely_missing():
    points = [pt(0, 1, 18), pt(1, 1, 18), pt(2, 1, 18)]  # cloud_cover_pct defaults to None
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert slots[0].avg_cloud_cover_pct is None


def test_run_spanning_two_models_labels_both_in_order():
    points = [pt(0, 1, 18, model="HARM-NL 2 km"), pt(1, 1, 18, model="GFS 13 km")]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=2.0)
    assert len(slots) == 1
    assert slots[0].model == "HARM-NL 2 km, GFS 13 km"


def test_run_within_single_model_labels_just_that_model():
    points = [pt(0, 1, 18), pt(1, 1, 18), pt(2, 1, 18)]
    slots = find_windy_timeslots(points, min_avg_wind_kt=16.0, min_duration_hours=3.0)
    assert slots[0].model == "TEST"


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
