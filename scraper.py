import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_URL = "http://micro.windguru.cz/"
USER_AGENT = "wind-cal/1.0 (personal wind-forecast calendar; single spot, hourly polling)"
TIMEOUT_SECONDS = 15

MODEL_HEADER_RE = re.compile(r"^(?P<model>.+?)\s*\(init:\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<hour>\d{2})\s*UTC\)\s*$")
ROW_RE = re.compile(
    r"^\s*[A-Za-z]{3}\s+(?P<day>\d{1,2})\.\s+(?P<hour>\d{2})h"
    r"\s+(?P<wspd>[\d.\-]+)"
    r"\s+(?P<gust>[\d.\-]+)"
    r"\s+(?P<wdirn>\S+)\s*$"
)


@dataclass(frozen=True)
class ForecastPoint:
    start: datetime
    end: datetime
    wind_avg_kt: float
    gust_kt: float
    direction: str | None
    model: str


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


def _fetch_raw(spot_id: int, model: str) -> str:
    url = f"{BASE_URL}?s={spot_id}&m={model}&v=WSPD,GUST,WDIRN"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise ScraperFetchError(f"failed to fetch forecast for spot {spot_id}, model {model}: {e}") from e


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
    rows_raw = []

    for line in body.splitlines():
        header_match = MODEL_HEADER_RE.match(line.strip())
        if header_match:
            model_name = header_match.group("model").strip()
            init_year, init_month, init_day = (int(x) for x in header_match.group("date").split("-"))
            continue
        row_match = ROW_RE.match(line)
        if row_match:
            rows_raw.append(row_match.groupdict())

    if model_name is None:
        raise ScraperParseError("no model/init header found in forecast response")
    if not rows_raw:
        raise ScraperParseError("no forecast data rows found in forecast response")

    starts = []
    cursor_year, cursor_month = init_year, init_month
    prev_day = init_day
    for raw in rows_raw:
        day = int(raw["day"])
        if day < prev_day:
            cursor_month += 1
            if cursor_month > 12:
                cursor_month = 1
                cursor_year += 1
        prev_day = day
        naive_local = datetime(cursor_year, cursor_month, day, int(raw["hour"]), 0, 0)
        starts.append(naive_local.replace(tzinfo=timezone))

    points: list[ForecastPoint] = []
    for i, (start, raw) in enumerate(zip(starts, rows_raw)):
        if i + 1 < len(starts):
            end = starts[i + 1]
        else:
            prev_step = start - starts[i - 1] if i > 0 else timedelta(hours=1)
            end = start + prev_step

        wspd, gust, wdirn = raw["wspd"], raw["gust"], raw["wdirn"]
        if wspd == "-" or gust == "-":
            continue  # missing forecast value — treat as a gap, not zero wind

        points.append(
            ForecastPoint(
                start=start,
                end=end,
                wind_avg_kt=float(wspd),
                gust_kt=float(gust),
                direction=None if wdirn == "-" else wdirn,
                model=model_name,
            )
        )

    return points
