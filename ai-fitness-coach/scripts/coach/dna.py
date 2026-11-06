"""Training DNA: repeated, evidence-linked patterns from normalized history."""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from typing import Any

from .db import get_readiness_range, get_train_range, get_weights, latest_dna


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _week_start(value: str) -> str:
    current = date.fromisoformat(value)
    return (current - timedelta(days=current.weekday())).isoformat()


def _confidence(weeks: int, data_quality: float) -> str:
    if weeks < 2 or data_quality < 0.4:
        return "insufficient"
    if weeks < 4 or data_quality < 0.6:
        return "low"
    if weeks < 8 or data_quality < 0.8:
        return "medium"
    return "high"


def compute_dna(conn, start: str, end: str, *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    trains = get_train_range(conn, start, end)
    readiness = get_readiness_range(conn, start, end)
    weights = get_weights(conn, start, end)
    weeks = sorted({_week_start(train["date"]) for train in trains if train.get("date")})
    week_count = max(1, len(weeks))

    sessions = len(trains)
    total_sets = sum(int(train.get("sets_total") or 0) for train in trains)
    completed_sets = sum(int(train.get("sets_completed") or 0) for train in trains)
    volume = sum(float(train.get("volume_kg") or 0) for train in trains)
    body_parts: dict[str, float] = {}
    lifts: dict[str, dict[str, Any]] = {}
    aerobic_minutes = 0.0
    warnings: list[str] = []

    for train in trains:
        for part, part_volume in (train.get("body_parts") or {}).items():
            body_parts[part] = body_parts.get(part, 0.0) + float(part_volume or 0)
        if train.get("warnings"):
            warnings.extend(train["warnings"])
        for movement in train.get("movements") or []:
            if movement.get("aerobic"):
                metrics = movement.get("metrics") or {}
                for key in ("workoutTime", "duration_s", "duration", "time"):
                    value = metrics.get(key) if isinstance(metrics, dict) else None
                    if value is not None:
                        try:
                            number = float(value)
                            aerobic_minutes += number / 60.0 if number > 300 else number
                            break
                        except (TypeError, ValueError):
                            pass
                else:
                    for item in movement.get("sets") or []:
                        if item.get("time_s"):
                            aerobic_minutes += float(item["time_s"]) / 60.0
                continue
            name = movement.get("name") or "unknown"
            lift = lifts.setdefault(
                name,
                {"name": name, "sessions": 0, "sets": 0, "reps": 0.0, "volume_kg": 0.0, "best_weight": 0.0, "body_parts": [], "points": []},
            )
            lift["sessions"] += 1
            lift["body_parts"] = sorted(set(lift["body_parts"]) | set(movement.get("body_parts") or []))
            point_weight = 0.0
            point_volume = 0.0
            for item in movement.get("sets") or []:
                lift["sets"] += 1
                lift["reps"] += float(item.get("reps") or 0)
                lift["volume_kg"] += float(item.get("volume_kg") or 0)
                lift["best_weight"] = max(lift["best_weight"], float(item.get("weight") or 0))
                point_weight = max(point_weight, float(item.get("weight") or 0))
                point_volume += float(item.get("volume_kg") or 0)
            lift["points"].append({"date": train.get("date"), "best_weight": point_weight, "volume_kg": point_volume})

    adherence = (completed_sets / total_sets) if total_sets else None
    readiness_scores = []
    for row in readiness:
        components = _loads(row.get("components_json")) or {}
        score = row.get("score")
        if score is not None:
            readiness_scores.append(float(score))
    readiness_mean = round(statistics.mean(readiness_scores), 1) if readiness_scores else None
    readiness_low_days = sum(1 for value in readiness_scores if value < 40)

    weight_values = [float(row["weight_kg"]) for row in weights if row.get("weight_kg") is not None]
    weight_trend = None
    if len(weight_values) >= 2:
        weight_trend = {
            "first_kg": round(weight_values[0], 1),
            "last_kg": round(weight_values[-1], 1),
            "change_kg": round(weight_values[-1] - weight_values[0], 1),
            "samples": len(weight_values),
        }

    main_lifts = sorted(lifts.values(), key=lambda item: item["volume_kg"], reverse=True)[:8]
    for lift in main_lifts:
        points = sorted(
            [point for point in lift.pop("points", []) if point.get("date")],
            key=lambda point: point["date"],
        )
        if len(points) >= 4:
            middle = len(points) // 2
            first = [point["best_weight"] for point in points[:middle] if point["best_weight"]]
            second = [point["best_weight"] for point in points[middle:] if point["best_weight"]]
            if first and second:
                change = (statistics.mean(second) - statistics.mean(first)) / max(statistics.mean(first), 1)
                lift["trend"] = "improving" if change > 0.02 else "declining" if change < -0.02 else "stable"
                lift["trend_change_pct"] = round(change * 100, 1)
            else:
                lift["trend"] = "insufficient_weight_data"
        else:
            lift["trend"] = "insufficient"
        lift["volume_kg"] = round(lift["volume_kg"], 1)
        lift["reps"] = round(lift["reps"], 1)
        lift["best_weight"] = round(lift["best_weight"], 1)

    data_quality = 1.0
    if not sessions:
        data_quality = 0.0
    elif adherence is None:
        data_quality = 0.4
    elif adherence < 0.8:
        data_quality = 0.6
    if warnings:
        data_quality = min(data_quality, 0.7)
    confidence = _confidence(week_count, data_quality)

    dimensions = {
        "frequency": {
            "status": "observed" if sessions else "unknown",
            "sessions": sessions,
            "sessions_per_week": round(sessions / week_count, 2),
            "evidence": [f"{start} 至 {end} 共 {sessions} 次训练，{week_count} 个自然周"],
        },
        "volume": {
            "status": "observed" if total_sets else "unknown",
            "total_volume_kg": round(volume, 1),
            "sets": total_sets,
            "evidence": [f"总训练量 {round(volume, 1)} kg，总组数 {total_sets}"],
        },
        "body_distribution": {
            "status": "observed" if body_parts else "unknown",
            "parts": {key: round(value, 1) for key, value in sorted(body_parts.items(), key=lambda item: item[1], reverse=True)},
        },
        "main_lift_response": {
            "status": "observed" if main_lifts else "unknown",
            "lifts": main_lifts,
        },
        "aerobic_response": {
            "status": "observed" if aerobic_minutes else "unknown",
            "minutes": round(aerobic_minutes, 1),
            "minutes_per_week": round(aerobic_minutes / week_count, 1),
        },
        "recovery": {
            "status": "observed" if readiness_scores else "unknown",
            "readiness_mean": readiness_mean,
            "low_days": readiness_low_days,
            "samples": len(readiness_scores),
        },
        "adherence": {
            "status": "observed" if adherence is not None else "unknown",
            "completed_set_rate": round(adherence, 2) if adherence is not None else None,
        },
        "risk_boundaries": {
            "status": "observed" if warnings else "no_flags",
            "warnings": sorted(set(warnings)),
        },
    }

    evidence = [
        f"窗口 {start} 至 {end}，{week_count} 周",
        f"训练 {sessions} 次，总组数 {total_sets}，完成组 {completed_sets}",
        f"估算训练量 {round(volume, 1)} kg",
    ]
    if body_parts:
        evidence.append("部位分布：" + "，".join(f"{key} {round(value, 1)}" for key, value in sorted(body_parts.items(), key=lambda item: item[1], reverse=True)))
    if readiness_mean is not None:
        evidence.append(f"readiness 均值 {readiness_mean}，低分天数 {readiness_low_days}")
    if weight_trend:
        evidence.append(f"体重样本 {weight_trend['samples']} 次，变化 {weight_trend['change_kg']} kg")

    previous = latest_dna(conn)
    diff = None
    if previous:
        old = previous.get("payload") or {}
        old_metrics = old.get("metrics") or {}
        diff = {
            "previous_generated_at": previous.get("generated_at"),
            "sessions": sessions - int(old_metrics.get("sessions") or 0),
            "volume_kg": round(volume - float(old_metrics.get("volume_kg") or 0), 1),
            "confidence_before": previous.get("confidence"),
            "confidence_after": confidence,
        }

    return {
        "schema_version": "1.0",
        "window": {"start": start, "end": end, "weeks": week_count},
        "confidence": confidence,
        "data_quality": round(data_quality, 2),
        "metrics": {
            "sessions": sessions,
            "training_days": len({train["date"] for train in trains}),
            "sets": total_sets,
            "completed_sets": completed_sets,
            "volume_kg": round(volume, 1),
            "adherence": round(adherence, 2) if adherence is not None else None,
        },
        "dimensions": dimensions,
        "weights": {"trend": weight_trend},
        "evidence_ledger": evidence,
        "version_diff": diff,
        "limitations": [
            "单窗口只标观察；2–3 个可比窗口后才提高置信度。",
            "训练量只统计可解析的重量×次数；自重和计时动作需人工确认。",
            "不做医学结论；异常心搏和红旗另走安全分流。",
        ],
    }
