"""Live mi-health data source.

Xiaomi data is read from the configured mi-health REST endpoint at request
time. Nothing is persisted locally; the only cache is the current process
memory in the client that made the call.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config
from .http import ApiError
from .mi_health import MiHealthClient, _data, _number, hrv_from_sleep
from .normalize import normalize_date


def empty_day(date_value: str) -> dict[str, Any]:
    return {
        "date": date_value,
        "sleep": None,
        "hrv": None,
        "rhr": None,
        "stress": None,
        "spo2": None,
        "activity": None,
        "abnormal": [],
        "body": [],
        "meta": {},
    }


def _empty_row(date_value: str) -> dict[str, Any]:
    return {
        "date": date_value,
        "sleep_json": None,
        "hrv_json": None,
        "rhr": None,
        "stress_json": None,
        "spo2_json": None,
        "activity_json": None,
        "abnormal_json": [],
    }


def _items(payload: Any) -> list[dict[str, Any]]:
    data = _data(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("records", "days", "items", "list", "data"):
        nested = data.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            data = nested
            break
    if any(
        key in data
        for key in (
            "date",
            "datestr",
            "end_at",
            "start_at",
            "timestamp",
            "time",
            "bpm",
            "steps",
            "stress_score",
            "spo2_pct",
        )
    ):
        return [data]
    rows = []
    for key, value in data.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("date", key)
            rows.append(item)
    return rows


def _date_key(value: Any, timezone: ZoneInfo) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        text = str(value).strip()
        try:
            number = float(text)
        except ValueError:
            number = 0.0
        if len(text) == 8 and 19_000_000 <= number <= 29_999_999:
            return normalize_date(text)
        if len(text) >= 10:
            try:
                if number > 10_000_000_000:
                    number /= 1000.0
                return datetime.fromtimestamp(number, timezone).date().isoformat()
            except (OSError, OverflowError, ValueError):
                pass
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return normalize_date(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone)
    return parsed.date().isoformat()


def _row_date(item: dict[str, Any], timezone: ZoneInfo, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if item.get(key) is not None:
            parsed = _date_key(item[key], timezone)
            if parsed:
                return parsed
    return None


class MiHealthSource:
    """Read one day plus a rolling baseline from mi-health, live."""

    def __init__(self, config: Config, client: MiHealthClient | None = None) -> None:
        self.config = config
        self.client = client or MiHealthClient(config)

    def day(self, date_value: str) -> dict[str, Any]:
        payload = self.client.collect_day(date_value)
        payload.setdefault("date", date_value)
        payload.setdefault("meta", {})
        return payload

    def baseline_rows(self, end_date: str, days: int = 28) -> list[dict[str, Any]]:
        end = date.fromisoformat(end_date)
        start = (end - timedelta(days=max(1, days) - 1)).isoformat()

        def load(fetch: Any) -> Any:
            try:
                return fetch()
            except ApiError:
                return {"data": [], "meta": {}}

        sleep_payload = load(lambda: self.client.sleep_range(start, end_date))
        hr_payload = load(lambda: self.client.heart_rate_range(start, end_date))
        summary_payload = load(lambda: self.client.summary_range(start, end_date))

        rows: dict[str, dict[str, Any]] = {}
        sleep_marker: dict[str, str] = {}
        resting: dict[str, list[float]] = {}
        passive: dict[str, list[float]] = {}

        for item in _items(sleep_payload):
            key = _row_date(item, self.config.timezone, ("end_at", "date", "datestr", "start_at"))
            if not key:
                continue
            row = rows.setdefault(key, _empty_row(key))
            marker = str(item.get("end_at") or item.get("date") or "")
            if marker >= sleep_marker.get(key, ""):
                sleep_marker[key] = marker
                row["sleep_json"] = item
                row["hrv_json"] = hrv_from_sleep(item)

        for item in _items(hr_payload):
            key = _row_date(item, self.config.timezone, ("date", "datestr", "timestamp", "time", "start_at"))
            if not key:
                continue
            bpm = _number(item.get("bpm"))
            if bpm is None:
                continue
            row = rows.setdefault(key, _empty_row(key))
            sample_type = str(item.get("sample_type") or item.get("type") or "").lower()
            if sample_type == "resting":
                resting.setdefault(key, []).append(bpm)
            elif sample_type in ("", "passive"):
                passive.setdefault(key, []).append(bpm)
            # Keep the row even when only heart rate exists that day.

        for item in _items(summary_payload):
            key = _row_date(item, self.config.timezone, ("date", "datestr", "start_date", "timestamp"))
            if not key:
                continue
            row = rows.setdefault(key, _empty_row(key))
            row["activity_json"] = item

        if not rows and not resting:
            return []

        result = []
        for key in sorted(rows):
            row = rows[key]
            values = resting.get(key) or []
            if values:
                row["rhr"] = round(statistics.median(values), 1)
            elif passive.get(key):
                row["rhr"] = round(min(passive[key]), 1)
            if not any(
                row.get(field)
                for field in ("sleep_json", "rhr", "activity_json")
            ):
                continue
            result.append(row)
        return result
