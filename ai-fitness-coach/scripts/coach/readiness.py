"""Transparent readiness scoring with data-completeness confidence."""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Iterable

WEIGHTS = {
    "sleep_duration": 20.0,
    "sleep_continuity": 10.0,
    "hrv": 20.0,
    "rhr": 15.0,
    "training_load": 15.0,
    "stress": 7.5,
    "spo2": 7.5,
    "activity": 5.0,
}

TIER_GREEN = "green"
TIER_YELLOW = "yellow"
TIER_RED = "red"
TIER_UNKNOWN = "unknown"


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def median(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.median(clean) if clean else None


def _sleep_duration_score(minutes: float | None) -> float | None:
    if minutes is None:
        return None
    if minutes >= 540:
        return 90.0
    if minutes >= 420:
        return 100.0
    if minutes >= 360:
        return 70.0 + (minutes - 360) / 60.0 * 30.0
    if minutes >= 300:
        return 45.0 + (minutes - 300) / 60.0 * 25.0
    if minutes >= 240:
        return 25.0 + (minutes - 240) / 60.0 * 20.0
    return 15.0


def _sleep_continuity_score(asleep: float | None, duration: float | None) -> float | None:
    if not asleep or not duration:
        return None
    ratio = asleep / duration
    if ratio >= 0.95:
        return 100.0
    if ratio >= 0.90:
        return 80.0 + (ratio - 0.90) / 0.05 * 20.0
    if ratio >= 0.80:
        return 55.0 + (ratio - 0.80) / 0.10 * 25.0
    if ratio >= 0.70:
        return 35.0 + (ratio - 0.70) / 0.10 * 20.0
    return clamp(ratio / 0.70 * 35.0)


def _ratio_score(value: float | None, baseline: float | None) -> float | None:
    if value is None or not baseline:
        return None
    ratio = value / baseline
    if ratio >= 1.0:
        return 100.0
    if ratio >= 0.90:
        return 80.0 + (ratio - 0.90) / 0.10 * 20.0
    if ratio >= 0.80:
        return 55.0 + (ratio - 0.80) / 0.10 * 25.0
    if ratio >= 0.70:
        return 30.0 + (ratio - 0.70) / 0.10 * 25.0
    return clamp((ratio - 0.50) / 0.20 * 30.0)


def _rhr_score(value: float | None, baseline: float | None) -> float | None:
    if value is None or not baseline:
        return None
    delta = value - baseline
    if delta <= 0:
        return 100.0
    if delta <= 2:
        return 85.0 + (2 - delta) / 2 * 15.0
    if delta <= 5:
        return 65.0 + (5 - delta) / 3 * 20.0
    if delta <= 10:
        return 40.0 + (10 - delta) / 5 * 25.0
    return clamp(40.0 - (delta - 10) * 4.0)


def _load_score(load: float | None, baseline: float | None) -> float | None:
    if load is None or baseline is None:
        return None
    if baseline <= 0:
        return 90.0 if load <= 0 else 70.0
    ratio = load / baseline
    if ratio <= 0.5:
        return 95.0
    if ratio <= 1.2:
        return 100.0
    if ratio <= 1.6:
        return 80.0 + (1.6 - ratio) / 0.4 * 15.0
    if ratio <= 2.0:
        return 55.0 + (2.0 - ratio) / 0.4 * 25.0
    if ratio <= 2.5:
        return 30.0 + (2.5 - ratio) / 0.5 * 25.0
    return clamp(30.0 - (ratio - 2.5) * 20.0)


def _stress_score(value: float | None) -> float | None:
    if value is None:
        return None
    return clamp(100.0 - value)


def _spo2_score(value: float | None) -> float | None:
    if value is None:
        return None
    if value >= 97:
        return 100.0
    if value >= 95:
        return 80.0 + (value - 95) / 2 * 20.0
    if value >= 93:
        return 50.0 + (value - 93) / 2 * 30.0
    return clamp((value - 85) / 8 * 50.0)


def _activity_score(steps: float | None, baseline: float | None) -> float | None:
    if steps is None or not baseline:
        return None
    ratio = steps / baseline
    if 0.5 <= ratio <= 1.5:
        return 100.0
    if 0.3 <= ratio < 0.5:
        return 75.0 + (ratio - 0.3) / 0.2 * 25.0
    if 1.5 < ratio <= 2.0:
        return 75.0 + (2.0 - ratio) / 0.5 * 25.0
    return 60.0


def compute_baseline(mi_rows: Iterable[dict[str, Any]], train_loads: dict[str, float] | None = None) -> dict[str, Any]:
    rows = list(mi_rows)
    hrv_values = []
    rhr_values = []
    sleep_values = []
    step_values = []
    for row in rows:
        import json

        hrv = row.get("hrv_json")
        if hrv:
            try:
                hrv = json.loads(hrv) if isinstance(hrv, str) else hrv
                hrv_values.append(float(hrv.get("avg_hrv_ms")))
            except (TypeError, ValueError, AttributeError):
                pass
        if row.get("rhr") is not None:
            rhr_values.append(float(row["rhr"]))
        sleep = row.get("sleep_json")
        if sleep:
            try:
                sleep = json.loads(sleep) if isinstance(sleep, str) else sleep
                value = sleep.get("time_asleep_minutes") or sleep.get("duration_minutes")
                if value is not None:
                    sleep_values.append(float(value))
            except (TypeError, ValueError, AttributeError):
                pass
        activity = row.get("activity_json")
        if activity:
            try:
                activity = json.loads(activity) if isinstance(activity, str) else activity
                if activity.get("steps") is not None:
                    step_values.append(float(activity["steps"]))
            except (TypeError, ValueError, AttributeError):
                pass
    loads = list((train_loads or {}).values())
    return {
        "hrv": median(hrv_values),
        "rhr": median(rhr_values),
        "sleep_minutes": median(sleep_values),
        "steps": median(step_values),
        "training_load": median(loads),
        "days": len(rows),
    }


def assess_readiness(
    *,
    sleep: dict[str, Any] | None,
    hrv: dict[str, Any] | None,
    rhr: float | None,
    stress: dict[str, Any] | None,
    spo2: dict[str, Any] | None,
    activity: dict[str, Any] | None,
    yesterday_load: float | None,
    baseline: dict[str, Any] | None = None,
    abnormal_events: list[dict[str, Any]] | None = None,
    red_flags: list[str] | None = None,
) -> dict[str, Any]:
    baseline = baseline or {}
    duration = None
    asleep = None
    if sleep:
        duration = sleep.get("duration_minutes")
        asleep = sleep.get("time_asleep_minutes")
    hrv_value = None
    if hrv:
        hrv_value = hrv.get("avg_hrv_ms") or hrv.get("hrv_median_ms")
    stress_value = stress.get("avg") if stress else None
    spo2_value = spo2.get("min") if spo2 else None
    steps = activity.get("steps") if activity else None

    scores = {
        "sleep_duration": _sleep_duration_score(duration),
        "sleep_continuity": _sleep_continuity_score(asleep, duration),
        "hrv": _ratio_score(hrv_value, baseline.get("hrv")),
        "rhr": _rhr_score(rhr, baseline.get("rhr")),
        "training_load": _load_score(yesterday_load, baseline.get("training_load")),
        "stress": _stress_score(stress_value),
        "spo2": _spo2_score(spo2_value),
        "activity": _activity_score(steps, baseline.get("steps")),
    }
    components = {}
    available_weight = 0.0
    weighted_total = 0.0
    for key, score in scores.items():
        weight = WEIGHTS[key]
        available = score is not None
        if available:
            available_weight += weight
            weighted_total += score * weight
        components[key] = {
            "score": round(score, 1) if score is not None else None,
            "weight": weight,
            "available": available,
        }
    completeness = available_weight / sum(WEIGHTS.values())
    score = weighted_total / available_weight if available_weight else 0.0
    reasons: list[str] = []
    baseline_days = int(baseline.get("days") or 0)
    if baseline_days and baseline_days < 3:
        completeness = min(completeness, 0.4)
        reasons.append("insufficient_baseline")
    elif baseline_days and baseline_days < 7:
        completeness = min(completeness, 0.6)
        reasons.append("short_baseline")
    elif baseline_days and baseline_days < 14:
        completeness = min(completeness, 0.8)
    safety_flag = bool(abnormal_events)
    if red_flags:
        safety_flag = True
        reasons.append("red_flags")
    if safety_flag and not red_flags:
        reasons.append("abnormal_heart_beat")
    if completeness < 0.6:
        reasons.append("low_data_completeness")
    physiological = any(
        scores.get(key) is not None
        for key in ("sleep_duration", "sleep_continuity", "hrv", "rhr", "stress", "spo2")
    )
    if available_weight == 0 or not physiological:
        tier = TIER_UNKNOWN
    elif score >= 70:
        tier = TIER_GREEN
    elif score >= 40:
        tier = TIER_YELLOW
    else:
        tier = TIER_RED
    if completeness < 0.6 and tier == TIER_GREEN:
        tier = TIER_YELLOW
    if red_flags:
        tier = TIER_RED
    elif abnormal_events and tier == TIER_GREEN:
        tier = TIER_YELLOW
    return {
        "date": None,
        "tier": tier,
        "score": round(score, 1),
        "confidence": round(completeness, 2),
        "components": components,
        "reasons": reasons,
        "safety_flag": safety_flag,
        "inputs": {
            "sleep_duration_minutes": duration,
            "sleep_asleep_minutes": asleep,
            "hrv_ms": hrv_value,
            "rhr_bpm": rhr,
            "stress_avg": stress_value,
            "spo2_min": spo2_value,
            "steps": steps,
            "yesterday_training_load": yesterday_load,
            "baseline": baseline,
        },
    }


def readiness_action(result: dict[str, Any]) -> str:
    tier = result.get("tier")
    if tier == TIER_UNKNOWN:
        return "先同步小米和训记数据；数据补齐前按保守版本，不做高强度或极限组。"
    if tier == TIER_RED:
        return "主动恢复或休息；不做高疲劳复合动作；有红旗症状时停止训练并寻求专业评估。"
    if tier == TIER_YELLOW:
        return "按计划但降一档：减少 1–2 个正式组，或把 RPE 上限降到 7–8；不同时改两个变量。"
    return "按计划推进；可在动作质量稳定的前提下小幅加组或加重。"


def date_window(end: str, days: int) -> tuple[str, str]:
    end_date = date.fromisoformat(end)
    start_date = end_date - timedelta(days=max(1, days) - 1)
    return start_date.isoformat(), end_date.isoformat()
