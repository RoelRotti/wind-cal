from datetime import datetime, timezone

from icalendar import Calendar, Event

from analyzer import Timeslot

PRODID = "-//wind-cal//Wind Forecast Calendar//EN"
WIND_EMOJI = "💨"


def _uid(spot_id: int, start: datetime) -> str:
    start_utc = start.astimezone(timezone.utc)
    return f"windcal-{spot_id}-{start_utc:%Y%m%dT%H%M%SZ}@wind-cal.local"


def _wind_emoji(avg_wind_kt_rounded: int) -> str:
    """1 emoji per 5kt of average wind, starting at 15kt (15-20 -> 1, 20-25 -> 2, ...).
    Takes the already-rounded, displayed value so the emoji count always matches
    what's shown next to it (e.g. 19.5 displayed as "20" must bucket as 20, not 19)."""
    count = max(0, (avg_wind_kt_rounded - 15) // 5 + 1)
    return WIND_EMOJI * count


_DIGIT_EMOJI = {"0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
                "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣"}


def _emoji_number(n: int) -> str:
    return "".join(_DIGIT_EMOJI[digit] for digit in str(n))


def _apply_content(event: Event, slot: Timeslot, spot_id: int, spot_name: str, now: datetime) -> None:
    direction = slot.direction or "?"
    windguru_url = f"https://www.windguru.cz/{spot_id}"
    event.add("dtstart", slot.start.astimezone(timezone.utc))
    event.add("dtend", slot.end.astimezone(timezone.utc))
    event.add("dtstamp", now)
    event.add("status", "CONFIRMED")
    avg_display = round(slot.avg_wind_kt)
    gust_display = round(slot.max_gust_kt)
    event.add(
        "summary",
        f"{_wind_emoji(avg_display)}\n"
        f"{_emoji_number(avg_display)}\n"
        f"{_emoji_number(gust_display)}\n"
        f"{direction}",
    )
    event.add("location", spot_name)
    event.add(
        "description",
        f"Model: {slot.model}. Generated {now:%Y-%m-%d %H:%M} UTC by wind-cal. "
        f"Forecasts change — re-checked hourly. {windguru_url}",
    )
    event.add("x-windcal-avg-kt", f"{round(slot.avg_wind_kt, 1)}")
    event.add("x-windcal-gust-kt", f"{round(slot.max_gust_kt, 1)}")
    event.add("x-windcal-direction", direction)
    event.add("x-windcal-model", slot.model)


def _new_event(uid: str, slot: Timeslot, spot_id: int, spot_name: str, now: datetime) -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("sequence", 0)
    _apply_content(event, slot, spot_id, spot_name, now)
    return event


def _updated_event(existing: Event, slot: Timeslot, spot_id: int, spot_name: str, now: datetime) -> Event:
    event = Event()
    event.add("uid", existing["UID"])
    event.add("sequence", int(existing.get("SEQUENCE", 0)) + 1)
    _apply_content(event, slot, spot_id, spot_name, now)
    return event


def _content_key(event: Event) -> tuple:
    return (
        event["DTEND"].dt,
        str(event["X-WINDCAL-AVG-KT"]),
        str(event["X-WINDCAL-GUST-KT"]),
        str(event["X-WINDCAL-DIRECTION"]),
        str(event.get("X-WINDCAL-MODEL", "")),
    )


def _content_key_from_slot(slot: Timeslot) -> tuple:
    return (
        slot.end.astimezone(timezone.utc),
        f"{round(slot.avg_wind_kt, 1)}",
        f"{round(slot.max_gust_kt, 1)}",
        slot.direction or "?",
        slot.model,
    )


def build_calendar(
    timeslots: list[Timeslot],
    spot_id: int,
    spot_name: str,
    calendar_name: str,
    existing_ics_bytes: bytes | None,
    now: datetime,
) -> bytes:
    """Diff the desired timeslots against any existing calendar and produce the
    new .ics bytes. New slots get SEQUENCE=0, changed slots (same UID, different
    content) get SEQUENCE+1, unchanged slots are carried over untouched (so a
    no-op run produces byte-identical output), and slots no longer present are
    dropped."""
    existing_by_uid: dict[str, Event] = {}
    if existing_ics_bytes:
        for component in Calendar.from_ical(existing_ics_bytes).walk("VEVENT"):
            existing_by_uid[str(component["UID"])] = component

    desired_by_uid = {_uid(spot_id, slot.start): slot for slot in timeslots}

    events = []
    for uid in set(existing_by_uid) | set(desired_by_uid):
        slot = desired_by_uid.get(uid)
        existing = existing_by_uid.get(uid)

        if slot is None:
            continue  # no longer forecast as windy, or scrolled into the past

        if existing is None:
            events.append(_new_event(uid, slot, spot_id, spot_name, now))
        elif _content_key(existing) == _content_key_from_slot(slot):
            events.append(existing)
        else:
            events.append(_updated_event(existing, slot, spot_id, spot_name, now))

    events.sort(key=lambda e: e["DTSTART"].dt)

    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal["X-WR-CALNAME"] = calendar_name
    for event in events:
        cal.add_component(event)

    return cal.to_ical()


def read_existing(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_if_changed(path: str, new_bytes: bytes) -> bool:
    if read_existing(path) == new_bytes:
        return False
    with open(path, "wb") as f:
        f.write(new_bytes)
    return True
