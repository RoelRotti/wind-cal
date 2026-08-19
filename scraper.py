import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_URL = "http://micro.windguru.cz/"
USER_AGENT = "wind-cal/1.0 (personal wind-forecast calendar; single spot, hourly polling)"
TIMEOUT_SECONDS = 15
VARIABLES = "WSPD,GUST,WDIRN,APCP,APCP1,HCLD,MCLD,LCLD"

MODEL_HEADER_RE = re.compile(r"^(?P<model>.+?)\s*\(init:\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<hour>\d{2})\s*UTC\)\s*$")
COLUMN_HEADER_RE = re.compile(r"^\s*Date\s+(?P<names>.+)$")
DATE_PREFIX_RE = re.compile(r"^\s*[A-Za-z]{3}\s+(?P<day>\d{1,2})\.\s+(?P<hour>\d{2})h\s*(?P<rest>.*)$")


@dataclass(frozen=True)
class ForecastPoint:
    start: datetime
    end: datetime
    wind_avg_kt: float
    gust_kt: float
    direction: str | None
    model: str
    rain_mm: float = 0.0
    cloud_cover_pct: float | None = None


class ScraperError(Exception):
    pass


class ScraperFetchError(ScraperError):
    pass


class ScraperParseError(ScraperError):
    pass


class ScraperUnitMismatchError(ScraperError):
    pass


def fetch_forecast(spot_id: int, model: str, timezone: ZoneInfo) -> list[ForecastPoint]:
    text = _fetch_raw(spot_id, model)
    return parse_forecast(text, timezone)


def merge_forecasts(primary: list[ForecastPoint], fallback: list[ForecastPoint]) -> list[ForecastPoint]:
    """Use `primary` for whatever horizon it covers, then `fallback` for the
    remaining horizon beyond that (e.g. a short-range high-res model followed
    by a longer-range one)."""
    if not primary:
        return fallback
    cutover = primary[-1].end
    return primary + [p for p in fallback if p.start >= cutover]


def _fetch_raw(spot_id: int, model: str) -> str:
    url = f"{BASE_URL}?s={spot_id}&m={model}&v={VARIABLES}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ScraperFetchError(f"failed to fetch forecast for spot {spot_id}, model {model}: {e}") from e


def _extract_rain_mm(values: dict) -> float:
    """windguru reports rain as APCP (mm/3h) or APCP1 (mm/1h) depending on
    that row's own resolution, not the model overall — e.g. GFS's hourly rows
    only populate APCP1, its 3-hourly rows populate APCP (the one that
    actually matches the row's time window), and HARM-NL (always hourly)
    never returns an APCP column at all. Prefer APCP since it's the one that
    covers this row's full time span when both are present."""
    for key in ("APCP", "APCP1"):
        raw = values.get(key)
        if raw not in (None, "-"):
            return float(raw)
    return 0.0


def _extract_cloud_cover_pct(values: dict) -> float | None:
    """Combine the three cloud layers into one overall cover % via the
    standard random-overlap approximation, treating layers as independent."""
    clear_sky = 1.0
    found = False
    for key in ("HCLD", "MCLD", "LCLD"):
        raw = values.get(key)
        if raw not in (None, "-"):
            clear_sky *= 1.0 - float(raw) / 100.0
            found = True
    return round((1.0 - clear_sky) * 100, 1) if found else None


def parse_forecast(html: str, timezone: ZoneInfo) -> list[ForecastPoint]:
    pre_start = html.find("<pre>")
    pre_end = html.find("</pre>")
    if pre_start == -1 or pre_end == -1:
        raise ScraperParseError("could not find <pre> forecast block in response")
    body = html[pre_start + len("<pre>") : pre_end]

    if "knots" not in body:
        raise ScraperUnitMismatchError("expected 'knots' unit label not found in forecast response")

    model_name = None
    init_year = init_month = init_day = None
    column_names: list[str] = []
    rows_raw = []  # list of (day, hour, {column_name: raw_value})

    for line in body.splitlines():
        header_match = MODEL_HEADER_RE.match(line.strip())
        if header_match:
            model_name = header_match.group("model").strip()
            init_year, init_month, init_day = (int(x) for x in header_match.group("date").split("-"))
            continue

        column_match = COLUMN_HEADER_RE.match(line)
        if column_match:
            column_names = column_match.group("names").split()
            continue

        row_match = DATE_PREFIX_RE.match(line)
        if row_match and column_names:
            tokens = row_match.group("rest").split()
            if len(tokens) != len(column_names):
                continue  # unexpected row shape (e.g. a non-data line) — skip rather than misalign
            rows_raw.append((int(row_match.group("day")), int(row_match.group("hour")), dict(zip(column_names, tokens))))

    if model_name is None:
        raise ScraperParseError("no model/init header found in forecast response")
    if not rows_raw:
        raise ScraperParseError("no forecast data rows found in forecast response")

    return _build_points(rows_raw, init_year, init_month, init_day, timezone, model_name)


def _build_points(rows_raw, init_year, init_month, init_day, timezone, model_name) -> list[ForecastPoint]:
    starts = []
    cursor_year, cursor_month = init_year, init_month
    prev_day = init_day
    for day, hour, _ in rows_raw:
        if day < prev_day:
            cursor_month += 1
            if cursor_month > 12:
                cursor_month = 1
                cursor_year += 1
        prev_day = day
        naive_local = datetime(cursor_year, cursor_month, day, hour, 0, 0)
        starts.append(naive_local.replace(tzinfo=timezone))

    points: list[ForecastPoint] = []
    for i, (start, (_, _, values)) in enumerate(zip(starts, rows_raw)):
        if i + 1 < len(starts):
            end = starts[i + 1]
        else:
            prev_step = start - starts[i - 1] if i > 0 else timedelta(hours=1)
            end = start + prev_step

        wspd, gust, wdirn = values.get("WSPD"), values.get("GUST"), values.get("WDIRN")
        if wspd in (None, "-") or gust in (None, "-"):
            continue  # missing forecast value — treat as a gap, not zero wind

        points.append(
            ForecastPoint(
                start=start,
                end=end,
                wind_avg_kt=float(wspd),
                gust_kt=float(gust),
                direction=None if wdirn in (None, "-") else wdirn,
                model=model_name,
                rain_mm=_extract_rain_mm(values),
                cloud_cover_pct=_extract_cloud_cover_pct(values),
            )
        )

    return points
