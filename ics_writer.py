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


_ARROWS = ["⬆️", "↗️", "➡️", "↘️", "⬇️", "↙️", "⬅️", "↖️"]  # pointing N, NE, E, ...


def _direction_arrow(direction_deg: float | None) -> str:
    """Arrow points downwind (where the wind blows to), like Windguru: wind from W -> ➡️."""
    if direction_deg is None:
        return ""
    return _ARROWS[round(((direction_deg + 180) % 360) / 45) % 8]


def _direction_display(slot: Timeslot) -> str:
    label = slot.direction or "?"
    arrow = _direction_arrow(slot.direction_deg)
    return f"{label} {arrow}" if arrow else label


def _temperature_display(slot: Timeslot) -> str:
    """Air and sea temperature on one line, e.g. "17°C / 🌊16°C"; either part is omitted if unknown."""
    parts = []
    if slot.avg_temp_c is not None:
        parts.append(f"{_whole_degrees(slot.avg_temp_c)}°C")
    if slot.sea_temp_c is not None:
        parts.append(f"🌊{_whole_degrees(slot.sea_temp_c)}°C")
    return " / ".join(parts)


RAIN_THRESHOLD_MM = 0.5  # below this, treat as negligible/trace rather than "rain expected"


def _weather_emoji(total_rain_mm: float, avg_cloud_cover_pct: float | None) -> str:
    if total_rain_mm >= RAIN_THRESHOLD_MM:
        return "🌧️"
    if avg_cloud_cover_pct is None:
        return ""  # no cloud data available for this slot — omit rather than guess
    if avg_cloud_cover_pct < 30:
        return "☀️"
    if avg_cloud_cover_pct < 70:
        return "⛅"
    return "☁️"


def _apply_content(event: Event, slot: Timeslot, spot_id: int, spot_name: str, now: datetime) -> None:
    direction = _direction_display(slot)
    windguru_url = f"https://www.windguru.cz/{spot_id}"
    event.add("dtstart", slot.start.astimezone(timezone.utc))
    event.add("dtend", slot.end.astimezone(timezone.utc))
    event.add("dtstamp", now)
    event.add("status", "CONFIRMED")
    avg_display = round(slot.avg_wind_kt)
    gust_display = round(slot.max_gust_kt)
    weather_emoji = _weather_emoji(slot.total_rain_mm, slot.avg_cloud_cover_pct)
    summary_lines = [_wind_emoji(avg_display), _emoji_number(avg_display), _emoji_number(gust_display), direction]
    if weather_emoji:
        summary_lines.append(weather_emoji)
    temperature = _temperature_display(slot)
    if temperature:
        summary_lines.append(temperature)
    event.add("summary", "\n".join(summary_lines))
    event.add("location", spot_name)

    cloud_text = f"{slot.avg_cloud_cover_pct:.0f}% cloud cover" if slot.avg_cloud_cover_pct is not None else "cloud cover unknown"
    temp_text = f"{_whole_degrees(slot.avg_temp_c)}°C" if slot.avg_temp_c is not None else "temperature unknown"
    sea_text = f"sea {_whole_degrees(slot.sea_temp_c)}°C" if slot.sea_temp_c is not None else "sea temperature unknown"
    rain_text = f"{slot.total_rain_mm:.1f}mm rain expected" if slot.total_rain_mm >= RAIN_THRESHOLD_MM else "no significant rain expected"
    event.add(
        "description",
        f"{rain_text}, {cloud_text}, {temp_text}, {sea_text}. Model: {slot.model}. Generated {now:%Y-%m-%d %H:%M} UTC by wind-cal. "
        f"Forecasts change — re-checked hourly. {windguru_url}",
    )
    event.add("x-windcal-avg-kt", f"{round(slot.avg_wind_kt, 1)}")
    event.add("x-windcal-gust-kt", f"{round(slot.max_gust_kt, 1)}")
    event.add("x-windcal-direction", direction)
    event.add("x-windcal-model", slot.model)
    event.add("x-windcal-rain-mm", f"{round(slot.total_rain_mm, 1)}")
    event.add("x-windcal-cloud-pct", f"{round(slot.avg_cloud_cover_pct, 1)}" if slot.avg_cloud_cover_pct is not None else "")
    event.add("x-windcal-temp-c", _whole_degrees(slot.avg_temp_c))
    event.add("x-windcal-sea-temp-c", _whole_degrees(slot.sea_temp_c))


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


def _whole_degrees(temp_c: float | None) -> str:
    # whole degrees, matching the title, so sub-degree forecast drift doesn't bump SEQUENCE
    return f"{round(temp_c)}" if temp_c is not None else ""


def _content_key(event: Event) -> tuple:
    return (
        event["DTEND"].dt,
        str(event["X-WINDCAL-AVG-KT"]),
        str(event["X-WINDCAL-GUST-KT"]),
        str(event["X-WINDCAL-DIRECTION"]),
        str(event.get("X-WINDCAL-MODEL", "")),
        str(event.get("X-WINDCAL-RAIN-MM", "")),
        str(event.get("X-WINDCAL-CLOUD-PCT", "")),
        str(event.get("X-WINDCAL-TEMP-C", "")),
        str(event.get("X-WINDCAL-SEA-TEMP-C", "")),
    )


def _content_key_from_slot(slot: Timeslot) -> tuple:
    return (
        slot.end.astimezone(timezone.utc),
        f"{round(slot.avg_wind_kt, 1)}",
        f"{round(slot.max_gust_kt, 1)}",
        _direction_display(slot),
        slot.model,
        f"{round(slot.total_rain_mm, 1)}",
        f"{round(slot.avg_cloud_cover_pct, 1)}" if slot.avg_cloud_cover_pct is not None else "",
        _whole_degrees(slot.avg_temp_c),
        _whole_degrees(slot.sea_temp_c),
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
