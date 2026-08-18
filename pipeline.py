import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from analyzer import find_windy_timeslots
from config import ConfigError, load_config
from ics_writer import build_calendar, read_existing, write_if_changed
from scraper import ScraperError, fetch_forecast, merge_forecasts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wind-cal")


def _read_status(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_status(path: str, status: dict) -> None:
    with open(path, "w") as f:
        json.dump(status, f, indent=2, sort_keys=True)
        f.write("\n")


def run() -> int:
    now = datetime.now(timezone.utc)
    try:
        config = load_config()
    except ConfigError as e:
        logger.error("config error: %s", e)
        return 1

    previous_status = _read_status(config.status_path)
    status = {
        "last_run_at_utc": now.isoformat(),
        "spot_id": config.spot_id,
        "primary_model": config.primary_model,
        "fallback_model": config.fallback_model,
        "last_success_at_utc": previous_status.get("last_success_at_utc"),
    }

    try:
        try:
            primary_points = fetch_forecast(config.spot_id, config.primary_model, config.timezone)
        except ScraperError as e:
            logger.warning(
                "primary model (%s) fetch failed, using %s for the full horizon: %s",
                config.primary_model, config.fallback_model, e,
            )
            primary_points = []

        fallback_points = fetch_forecast(config.spot_id, config.fallback_model, config.timezone)
        points = merge_forecasts(primary_points, fallback_points)

        timeslots = find_windy_timeslots(points, config.min_avg_wind_kt, config.min_duration_hours)
        existing_ics = read_existing(config.ics_path)
        new_ics = build_calendar(
            timeslots,
            config.spot_id,
            config.spot_name,
            config.calendar_name,
            existing_ics,
            now,
        )
        changed = write_if_changed(config.ics_path, new_ics)

        status["last_run_status"] = "ok"
        status["last_success_at_utc"] = now.isoformat()
        status["qualifying_timeslots_count"] = len(timeslots)
        status["ics_changed"] = changed
        status["error_message"] = None
        _write_status(config.status_path, status)

        logger.info(
            "ok: %d forecast points, %d qualifying timeslots, ics_changed=%s",
            len(points), len(timeslots), changed,
        )
        return 0

    except ScraperError as e:
        logger.error("scrape failed: %s", e)
        status["last_run_status"] = "scrape_failed"
        status["error_message"] = str(e)
        _write_status(config.status_path, status)
        return 1

    except Exception as e:
        logger.error("unexpected error: %s\n%s", e, traceback.format_exc())
        status["last_run_status"] = "error"
        status["error_message"] = str(e)
        _write_status(config.status_path, status)
        return 1


if __name__ == "__main__":
    sys.exit(run())
