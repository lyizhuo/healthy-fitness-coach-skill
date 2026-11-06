"""Read-only client for the mi-health REST API."""

from __future__ import annotations

import statistics
from typing import Any

from .config import Config
from .http import ApiError, bearer, get_json


def _data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(payload: Any) -> list[dict[str, Any]]:
    data = _data(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    if any(
        key in data
        for key in ("date", "datestr", "end_at", "start_at", "timestamp", "bpm", "steps", "stress_score", "spo2_pct")
    ):
        return [data]
    return [dict(value, date=value.get("date") or key) for key, value in data.items() if isinstance(value, dict)]


def _meta(payloads: Any) -> dict[str, Any]:
    """Merge freshness metadata from several mi-health responses.

    ``stale`` is true when any source is stale. Timestamps use the newest value
    because each endpoint carries its own sync cursor.
    """
    metas = [
        payload.get("meta")
        for payload in payloads
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict)
    ]
    if not metas:
        return {}
    merged: dict[str, Any] = {
        "stale": any(bool(meta.get("stale")) for meta in metas),
        "sources": len(metas),
    }
    for key in ("data_as_of", "last_synced_at", "next_sync_at", "sync_status"):
        values = [str(meta[key]) for meta in metas if meta.get(key) is not None]
        if values:
            merged[key] = max(values) if key != "sync_status" else values[0]
    errors = [str(meta["sync_error"]) for meta in metas if meta.get("sync_error")]
    if errors:
        merged["sync_error"] = errors[0]
    return merged


def hrv_from_sleep(sleep: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sleep:
        return None
    values = {
        key: sleep.get(key)
        for key in (
            "avg_hrv_ms",
            "min_hrv_ms",
            "max_hrv_ms",
            "hrv_median_ms",
            "hrv_std_ms",
            "hrv_lower_quantile_ms",
            "hrv_upper_quantile_ms",
            "hrv_base_min_ms",
            "hrv_base_max_ms",
            "hrv_analysis_at",
        )
        if sleep.get(key) is not None
    }
    return values or None


class MiHealthClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.config.mi_health_api_key:
            raise ApiError("missing MI_HEALTH_API_KEY", code="missing_key")
        response = get_json(
            f"{self.config.mi_health_base_url}{path}",
            headers=bearer(self.config.mi_health_api_key),
            params=params,
            timeout=self.config.request_timeout,
        )
        if not isinstance(response, dict):
            raise ApiError("mi-health returned a non-object response")
        return response

    def status(self) -> dict[str, Any]:
        return self._get("/api/status", {})

    def coverage(self) -> dict[str, Any]:
        return self._get("/api/coverage", {})

    def sleep(self, date_value: str, *, include_naps: bool = False) -> dict[str, Any]:
        return self._get("/api/sleep", {"start_date": date_value, "end_date": date_value, "include_naps": include_naps})

    def heart_rate(self, date_value: str, sample_type: str | None = None) -> dict[str, Any]:
        params = {"start_date": date_value, "end_date": date_value, "limit": 10000}
        if sample_type:
            params["sample_type"] = sample_type
        return self._get("/api/heart-rate", params)

    def summary(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/summary", {"start_date": date_value, "end_date": date_value})

    def stress(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/stress", {"start_date": date_value, "end_date": date_value, "limit": 10000})

    def spo2(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/spo2", {"start_date": date_value, "end_date": date_value, "limit": 10000})

    def abnormal(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/abnormal-heart-beat", {"start_date": date_value, "end_date": date_value})

    def body(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/body-measurements", {"start_date": date_value, "end_date": date_value})

    def workouts(self, date_value: str) -> dict[str, Any]:
        return self._get("/api/workouts", {"start_date": date_value, "end_date": date_value})

    def sleep_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get("/api/sleep", {"start_date": start_date, "end_date": end_date, "include_naps": False})

    def heart_rate_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get("/api/heart-rate", {"start_date": start_date, "end_date": end_date, "limit": 100000})

    def summary_range(self, start_date: str, end_date: str) -> dict[str, Any]:
        return self._get("/api/summary", {"start_date": start_date, "end_date": end_date})

    def collect_day(self, date_value: str) -> dict[str, Any]:
        sleep_payload = self.sleep(date_value)
        hr_payload = self.heart_rate(date_value)
        summary_payload = self.summary(date_value)
        stress_payload = self.stress(date_value)
        spo2_payload = self.spo2(date_value)
        abnormal_payload = self.abnormal(date_value)
        body_payload = self.body(date_value)

        sleeps = _rows(sleep_payload)
        sleeps.sort(key=lambda item: str(item.get("end_at") or ""), reverse=True)
        sleep = sleeps[0] if sleeps else None
        hrv = hrv_from_sleep(sleep)

        samples = _rows(hr_payload)
        resting = [_number(item.get("bpm")) for item in samples if item.get("sample_type") == "resting"]
        resting = [value for value in resting if value is not None]
        passive = [_number(item.get("bpm")) for item in samples if item.get("sample_type") == "passive"]
        passive = [value for value in passive if value is not None]
        rhr = statistics.median(resting) if resting else (min(passive) if passive else None)

        summary_rows = _rows(summary_payload)
        activity = summary_rows[0] if summary_rows else None

        stress_rows = _rows(stress_payload)
        stress_values = [_number(item.get("stress_score")) for item in stress_rows]
        stress_values = [value for value in stress_values if value is not None]
        stress = None
        if stress_values:
            stress = {
                "avg": round(statistics.mean(stress_values), 1),
                "max": max(stress_values),
                "min": min(stress_values),
                "samples": len(stress_values),
            }

        spo2_rows = _rows(spo2_payload)
        spo2_values = [_number(item.get("spo2_pct")) for item in spo2_rows]
        spo2_values = [value for value in spo2_values if value is not None]
        spo2 = None
        if spo2_values:
            spo2 = {
                "avg": round(statistics.mean(spo2_values), 1),
                "min": min(spo2_values),
                "samples": len(spo2_values),
            }

        abnormal = _rows(abnormal_payload)
        body = _rows(body_payload)

        return {
            "date": date_value,
            "sleep": sleep,
            "hrv": hrv,
            "rhr": round(rhr, 1) if rhr is not None else None,
            "stress": stress,
            "spo2": spo2,
            "activity": activity,
            "abnormal": abnormal,
            "body": body,
            "meta": _meta(
                [
                    sleep_payload,
                    hr_payload,
                    summary_payload,
                    stress_payload,
                    spo2_payload,
                    abnormal_payload,
                    body_payload,
                ]
            ),
            "raw": {
                "sleep": sleep_payload,
                "heart_rate": hr_payload,
                "summary": summary_payload,
                "stress": stress_payload,
                "spo2": spo2_payload,
                "abnormal": abnormal_payload,
                "body": body_payload,
            },
        }
