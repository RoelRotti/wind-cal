from dataclasses import dataclass
from datetime import datetime, timedelta

from scraper import ForecastPoint


@dataclass(frozen=True)
class Timeslot:
    start: datetime
    end: datetime
    avg_wind_kt: float
    max_gust_kt: float
    direction: str | None
    model: str


def find_windy_timeslots(
    points: list[ForecastPoint],
    min_avg_wind_kt: float,
    min_duration_hours: float,
) -> list[Timeslot]:
    """Find contiguous runs of points that are each >= min_avg_wind_kt and span
    >= min_duration_hours. A run breaks on either a sub-threshold point or a time
    gap between points (missing data can't be claimed as sustained wind)."""
    min_duration = timedelta(hours=min_duration_hours)
    runs: list[list[ForecastPoint]] = []
    current_run: list[ForecastPoint] = []

    for point in points:
        if point.wind_avg_kt >= min_avg_wind_kt:
            if current_run and current_run[-1].end == point.start:
                current_run.append(point)
            else:
                if current_run:
                    runs.append(current_run)
                current_run = [point]
        else:
            if current_run:
                runs.append(current_run)
            current_run = []

    if current_run:
        runs.append(current_run)

    timeslots = []
    for run in runs:
        start, end = run[0].start, run[-1].end
        if end - start >= min_duration:
            timeslots.append(_summarize(run, start, end))

    return timeslots


def _summarize(run: list[ForecastPoint], start: datetime, end: datetime) -> Timeslot:
    total_seconds = sum((p.end - p.start).total_seconds() for p in run)
    weighted_wind = sum(p.wind_avg_kt * (p.end - p.start).total_seconds() for p in run)
    peak_point = max(run, key=lambda p: p.wind_avg_kt)

    return Timeslot(
        start=start,
        end=end,
        avg_wind_kt=weighted_wind / total_seconds,
        max_gust_kt=max(p.gust_kt for p in run),
        direction=peak_point.direction,
        model=run[0].model,
    )
