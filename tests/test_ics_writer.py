from datetime import datetime, timedelta, timezone

from icalendar import Calendar

from analyzer import Timeslot
from ics_writer import build_calendar

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def slot(hour_offset, duration_hours, avg=17.0, gust=20.0, direction="W", model="TEST"):
    start = T0 + timedelta(hours=hour_offset)
    end = start + timedelta(hours=duration_hours)
    return Timeslot(start=start, end=end, avg_wind_kt=avg, max_gust_kt=gust, direction=direction, model=model)


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
