"""Load the private profile from ``profile.json``."""

from __future__ import annotations

import json
from typing import Any

from .config import Config

DEFAULT_PROFILE: dict[str, Any] = {
    "weight_kg": None,
    "goal": "hypertrophy",
    "training_days_per_week": 5,
    "training_time": "18:30",
    "timezone": "Asia/Shanghai",
    "training_venue": "gym",
    "diet_context": "canteen / takeout",
}


def load_profile(config: Config) -> dict[str, Any]:
    profile = dict(DEFAULT_PROFILE)
    json_path = config.home / "profile.json"
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                profile.update(loaded)
                return profile
        except (OSError, ValueError):
            pass
    return profile
