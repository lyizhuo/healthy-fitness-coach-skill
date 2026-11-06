"""Configuration and paths for the Hermes AI fitness coach."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Shanghai"


def _path(value: str | None, default: Path) -> Path:
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class Config:
    home: Path
    db_path: Path
    profile_path: Path
    decisions_path: Path
    raw_dir: Path
    timezone: ZoneInfo
    mi_health_base_url: str
    mi_health_api_key: str
    xunji_train_key: str
    xunji_food_key: str
    xunji_food_search_key: str
    request_timeout: float
    read_delay_seconds: float
    full_read_delay_seconds: float
    write_delay_seconds: float

    @property
    def tz_name(self) -> str:
        return str(self.timezone)


def load_config() -> Config:
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    home = _path(os.environ.get("AI_COACH_HOME"), hermes_home / "data" / "ai-coach")
    tz_name = os.environ.get("AI_COACH_TZ", DEFAULT_TZ)
    try:
        timezone = ZoneInfo(tz_name)
    except Exception:
        timezone = ZoneInfo(DEFAULT_TZ)
    return Config(
        home=home,
        db_path=home / "coach.sqlite",
        profile_path=home / "PROFILE.md",
        decisions_path=home / "DECISIONS.md",
        raw_dir=home / "raw",
        timezone=timezone,
        mi_health_base_url=os.environ.get("MI_HEALTH_BASE_URL", "http://127.0.0.1:8330").rstrip("/"),
        mi_health_api_key=os.environ.get("MI_HEALTH_API_KEY", ""),
        xunji_train_key=os.environ.get("XUNJI_TRAIN_API_KEY", ""),
        xunji_food_key=os.environ.get("XUNJI_FOOD_API_KEY", ""),
        xunji_food_search_key=os.environ.get("XUNJI_FOOD_SEARCH_API_KEY", ""),
        request_timeout=float(os.environ.get("AI_COACH_HTTP_TIMEOUT", "30")),
        read_delay_seconds=float(os.environ.get("AI_COACH_READ_DELAY", "15")),
        full_read_delay_seconds=float(os.environ.get("AI_COACH_FULL_READ_DELAY", "30")),
        write_delay_seconds=float(os.environ.get("AI_COACH_WRITE_DELAY", "45")),
    )


def require(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def ensure_dirs(config: Config) -> None:
    for path in (config.home, config.raw_dir, config.db_path.parent):
        path.mkdir(parents=True, exist_ok=True)
