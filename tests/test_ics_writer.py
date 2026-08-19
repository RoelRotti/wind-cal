from datetime import datetime, timedelta, timezone

from icalendar import Calendar

from analyzer import Timeslot
from ics_writer import build_calendar

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def slot(hour_offset, duration_hours, avg=17.0, gust=20.0, direction="W", model="TEST", rain_mm=0.0, cloud_pct=None):
    start = T0 + timedelta(hours=hour_offset)
    end = start + timedelta(hours=duration_hours)
    return Timeslot(
        start=start, end=end, avg_wind_kt=avg, max_gust_kt=gust, direction=direction, model=model,
        total_rain_mm=rain_mm, avg_cloud_cover_pct=cloud_pct,
    )


def _summary(ics_bytes):
    return str(list(Calendar.from_ical(ics_bytes).walk("VEVENT"))[0]["SUMMARY"])


def _description(ics_bytes):
    return str(list(Calendar.from_ical(ics_bytes).walk("VEVENT"))[0]["DESCRIPTION"])


def test_weather_emoji_is_last_line_of_title_when_rain_expected():
    slots = [slot(0, 3, rain_mm=2.0, cloud_pct=80.0)]
    summary = _summary(build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0))
    assert summary.endswith("\n🌧️")


def test_weather_emoji_is_sun_when_clear_and_dry():
    slots = [slot(0, 3, rain_mm=0.0, cloud_pct=10.0)]
    summary = _summary(build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0))
    assert summary.endswith("\n☀️")


def test_weather_emoji_omitted_when_no_cloud_data_and_no_rain():
    slots = [slot(0, 3, rain_mm=0.0, cloud_pct=None)]
    summary = _summary(build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0))
    assert "☀️" not in summary and "⛅" not in summary and "☁️" not in summary and "🌧️" not in summary
    assert summary.endswith(slots[0].direction or "?")  # title ends at direction, no trailing weather line


def test_description_states_rain_and_cloud_details():
    slots = [slot(0, 3, rain_mm=3.2, cloud_pct=64.0)]
    description = _description(build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0))
    assert "3.2mm rain expected" in description
    assert "64% cloud cover" in description


def test_description_says_no_significant_rain_below_threshold():
    slots = [slot(0, 3, rain_mm=0.1, cloud_pct=50.0)]
    description = _description(build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0))
    assert "no significant rain expected" in description


def test_rain_only_change_bumps_sequence():
    original = [slot(0, 3, rain_mm=0.0, cloud_pct=50.0)]
    ics1 = build_calendar(original, 1, "Test Spot", "Test Cal", None, T0)

    rainier = [slot(0, 3, rain_mm=5.0, cloud_pct=50.0)]
    ics2 = build_calendar(rainier, 1, "Test Spot", "Test Cal", ics1, T0 + timedelta(hours=1))

    events1 = list(Calendar.from_ical(ics1).walk("VEVENT"))
    events2 = list(Calendar.from_ical(ics2).walk("VEVENT"))
    assert int(events1[0]["SEQUENCE"]) == 0
    assert int(events2[0]["SEQUENCE"]) == 1


def test_wind_emoji_count_matches_displayed_rounded_number():
    # 19.5 rounds to "20" for display (Python's round-half-to-even) -> must
    # bucket as 20 (2 emoji), not floor to the raw 19.5 (which would be 1)
    slots = [slot(0, 3, avg=19.5)]
    ics_bytes = build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0)
    summary = str(list(Calendar.from_ical(ics_bytes).walk("VEVENT"))[0]["SUMMARY"])
    assert summary.startswith("💨💨\n2️⃣0️⃣")


def test_round_trip():
    slots = [slot(0, 3)]
    ics_bytes = build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0)
    events = list(Calendar.from_ical(ics_bytes).walk("VEVENT"))
    assert len(events) == 1
    assert events[0]["DTSTART"].dt == slots[0].start
    assert events[0]["DTEND"].dt == slots[0].end
    assert int(events[0]["SEQUENCE"]) == 0


def test_idempotent_rerun_is_byte_identical():
    slots = [slot(0, 3), slot(10, 4)]
    ics1 = build_calendar(slots, 1, "Test Spot", "Test Cal", None, T0)
    ics2 = build_calendar(slots, 1, "Test Spot", "Test Cal", ics1, T0 + timedelta(hours=1))
    assert ics1 == ics2


def test_changed_slot_bumps_sequence_and_keeps_uid():
    original = [slot(0, 3, avg=17.0)]
    ics1 = build_calendar(original, 1, "Test Spot", "Test Cal", None, T0)

    changed = [slot(0, 3, avg=25.0)]  # same start, different wind reading
    ics2 = build_calendar(changed, 1, "Test Spot", "Test Cal", ics1, T0 + timedelta(hours=1))

    events1 = list(Calendar.from_ical(ics1).walk("VEVENT"))
    events2 = list(Calendar.from_ical(ics2).walk("VEVENT"))
    assert len(events2) == 1
    assert str(events1[0]["UID"]) == str(events2[0]["UID"])
    assert int(events1[0]["SEQUENCE"]) == 0
    assert int(events2[0]["SEQUENCE"]) == 1


def test_model_only_change_bumps_sequence():
    original = [slot(0, 3, model="HARM-NL 2 km")]
    ics1 = build_calendar(original, 1, "Test Spot", "Test Cal", None, T0)

    same_numbers_different_model = [slot(0, 3, model="HARM-NL 2 km, GFS 13 km")]
    ics2 = build_calendar(same_numbers_different_model, 1, "Test Spot", "Test Cal", ics1, T0 + timedelta(hours=1))

    events1 = list(Calendar.from_ical(ics1).walk("VEVENT"))
    events2 = list(Calendar.from_ical(ics2).walk("VEVENT"))
    assert int(events1[0]["SEQUENCE"]) == 0
    assert int(events2[0]["SEQUENCE"]) == 1
    assert "GFS" in str(events2[0]["DESCRIPTION"])


def test_removed_slot_drops_from_output():
    both = [slot(0, 3), slot(10, 4)]
    ics1 = build_calendar(both, 1, "Test Spot", "Test Cal", None, T0)

    only_first = [slot(0, 3)]
    ics2 = build_calendar(only_first, 1, "Test Spot", "Test Cal", ics1, T0 + timedelta(hours=1))

    events2 = list(Calendar.from_ical(ics2).walk("VEVENT"))
    assert len(events2) == 1
    assert events2[0]["DTSTART"].dt == only_first[0].start
