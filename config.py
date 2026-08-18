import os
import tomllib
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_PATH = "config.toml"


@dataclass(frozen=True)
class Config:
    spot_id: int
    spot_name: str
    timezone: ZoneInfo
    model: str
    min_avg_wind_kt: float
    min_duration_hours: float
    ics_path: str
    status_path: str
    calendar_name: str


class ConfigError(Exception):
    pass


def load_config(path: str | None = None) -> Config:
    path = path or os.environ.get("WINDCAL_CONFIG", DEFAULT_CONFIG_PATH)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}")

    try:
        spot = raw["spot"]
        forecast = raw["forecast"]
        thresholds = raw["thresholds"]
        output = raw["output"]

        tz_name = spot["timezone"]
        try:
            timezone = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise ConfigError(f"unknown IANA timezone: {tz_name!r}")

        min_avg_wind_kt = float(thresholds["min_avg_wind_kt"])
        min_duration_hours = float(thresholds["min_duration_hours"])
        if min_avg_wind_kt <= 0:
            raise ConfigError("thresholds.min_avg_wind_kt must be positive")
        if min_duration_hours <= 0:
            raise ConfigError("thresholds.min_duration_hours must be positive")

        model = str(forecast["model"]).strip()
        if not model:
            raise ConfigError("forecast.model must not be empty")

        return Config(
            spot_id=int(spot["id"]),
            spot_name=str(spot["name"]),
            timezone=timezone,
            model=model,
            min_avg_wind_kt=min_avg_wind_kt,
            min_duration_hours=min_duration_hours,
            ics_path=str(output["ics_path"]),
            status_path=str(output["status_path"]),
            calendar_name=str(output["calendar_name"]),
        )
    except KeyError as e:
        raise ConfigError(f"missing required config key: {e}")
