"""Fact collection and Markdown report skeletons for daily coaching."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .config import Config
from .db import (
    get_food_range,
    get_plan_day,
    get_readiness_range,
    get_train_day,
    get_train_range,
    get_weights,
    save_readiness,
    training_load,
)
from .dna import compute_dna
from .http import ApiError
from .mi_source import MiHealthSource, empty_day
from .nutrition import gap, meal_distribution, protein_food_suggestions, target_ranges, totals_for
from .profile import load_profile
from .readiness import TIER_UNKNOWN, assess_readiness, compute_baseline, readiness_action

TIER_CN = {"green": "绿", "yellow": "黄", "red": "红", "unknown": "数据不足"}


def _mi_inputs(day: dict[str, Any] | None) -> dict[str, Any]:
    day = day or {}
    return {
        "sleep": day.get("sleep"),
        "hrv": day.get("hrv"),
        "rhr": day.get("rhr"),
        "stress": day.get("stress"),
        "spo2": day.get("spo2"),
        "activity": day.get("activity"),
        "abnormal": day.get("abnormal") or [],
    }


def _data_quality(mi: dict[str, Any] | None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    mi = mi or empty_day("")
    meta = mi.get("meta") or {}
    present = any(mi.get(key) for key in ("sleep", "hrv", "rhr", "stress", "spo2", "activity", "abnormal"))
    return {
        "mi_present": present,
        "stale": bool(meta.get("stale")) or bool(error) or not present,
        "data_as_of": meta.get("data_as_of"),
        "last_synced_at": meta.get("last_synced_at"),
        "error": error,
    }


def collect_mi_context(
    config: Config,
    date_value: str,
    source: MiHealthSource | None = None,
) -> dict[str, Any]:
    """Read one day and the 28-day baseline live from mi-health."""
    source = source or MiHealthSource(config)
    error: dict[str, Any] | None = None
    try:
        mi = source.day(date_value)
    except ApiError as exc:
        mi = empty_day(date_value)
        error = {"code": exc.code, "message": str(exc)}
    try:
        baseline_rows = source.baseline_rows(date_value, 28)
    except ApiError as exc:
        baseline_rows = []
        if error is None:
            error = {"code": exc.code, "message": str(exc)}
    return {"mi": mi, "baseline_rows": baseline_rows, "error": error}


def latest_or_compute_readiness(
    conn,
    config: Config,
    date_value: str,
    *,
    mi: dict[str, Any] | None = None,
    baseline_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    end = date.fromisoformat(date_value)
    start = (end - timedelta(days=27)).isoformat()
    loads = {row["date"]: row.get("volume_kg") or 0.0 for row in get_train_range(conn, start, date_value)}
    baseline = compute_baseline(baseline_rows or [], loads)
    inputs = _mi_inputs(mi)
    yesterday = (end - timedelta(days=1)).isoformat()
    result = assess_readiness(
        sleep=inputs["sleep"],
        hrv=inputs["hrv"],
        rhr=inputs["rhr"],
        stress=inputs["stress"],
        spo2=inputs["spo2"],
        activity=inputs["activity"],
        yesterday_load=training_load(conn, yesterday).get("volume_kg"),
        baseline=baseline,
        abnormal_events=inputs["abnormal"],
    )
    result["date"] = date_value
    result["inputs"]["freshness"] = (mi or {}).get("meta") or {}
    save_readiness(conn, date_value, result)
    return result


def energy_window(sleep: dict[str, Any] | None, timezone, default: str = "09:30–12:00") -> dict[str, Any]:
    if not sleep:
        return {"window": default, "basis": "无睡眠时间，给通用窗口", "confidence": "low"}
    end_at = sleep.get("end_at")
    if not end_at:
        return {"window": default, "basis": "睡眠记录缺少结束时间", "confidence": "low"}
    try:
        wake = datetime.fromisoformat(str(end_at).replace("Z", "+00:00"))
        if wake.tzinfo is not None:
            wake = wake.astimezone(timezone)
        high_start = wake + timedelta(hours=2)
        high_end = wake + timedelta(hours=4)
        return {
            "window": f"{high_start.strftime('%H:%M')}–{high_end.strftime('%H:%M')}",
            "basis": "起床后 2–4 小时，配合睡眠时长和睡眠惯性",
            "confidence": "medium" if sleep.get("time_awake_minutes", 0) < 30 else "low",
        }
    except ValueError:
        return {"window": default, "basis": "睡眠结束时间无法解析", "confidence": "low"}


def build_morning_facts(
    conn,
    config: Config,
    date_value: str,
    *,
    mi_source: MiHealthSource | None = None,
) -> dict[str, Any]:
    profile = load_profile(config)
    context = collect_mi_context(config, date_value, mi_source)
    mi = _mi_inputs(context["mi"])
    readiness = latest_or_compute_readiness(
        conn,
        config,
        date_value,
        mi=context["mi"],
        baseline_rows=context["baseline_rows"],
    )
    yesterday = (date.fromisoformat(date_value) - timedelta(days=1)).isoformat()
    trains = get_train_day(conn, yesterday)
    food = get_food_range(conn, yesterday, yesterday)
    data_quality = _data_quality(context["mi"], context["error"])
    data_quality["readiness_confidence"] = readiness.get("confidence")
    return {
        "date": date_value,
        "profile": profile,
        "readiness": readiness,
        "action": readiness_action(readiness),
        "sleep": mi["sleep"],
        "hrv": mi["hrv"],
        "rhr": mi["rhr"],
        "stress": mi["stress"],
        "spo2": mi["spo2"],
        "activity": mi["activity"],
        "abnormal": mi["abnormal"],
        "yesterday": {
            "date": yesterday,
            "training_load": training_load(conn, yesterday),
            "trains": [
                {
                    "title": train.get("title"),
                    "volume_kg": train.get("volume_kg"),
                    "sets_completed": train.get("sets_completed"),
                    "body_parts": train.get("body_parts"),
                }
                for train in trains
            ],
            "food": totals_for(food),
        },
        "energy_window": energy_window(mi["sleep"], config.timezone),
        "data_quality": data_quality,
    }


def build_preworkout_facts(
    conn,
    config: Config,
    date_value: str,
    *,
    mi_source: MiHealthSource | None = None,
) -> dict[str, Any]:
    profile = load_profile(config)
    context = collect_mi_context(config, date_value, mi_source)
    readiness = latest_or_compute_readiness(
        conn,
        config,
        date_value,
        mi=context["mi"],
        baseline_rows=context["baseline_rows"],
    )
    today_food = totals_for(get_food_range(conn, date_value, date_value))
    plan = get_plan_day(conn, date_value)
    yesterday = (date.fromisoformat(date_value) - timedelta(days=1)).isoformat()
    return {
        "date": date_value,
        "profile": profile,
        "readiness": readiness,
        "action": readiness_action(readiness),
        "today_food": today_food,
        "plan": plan,
        "yesterday_training": training_load(conn, yesterday),
        "activity": _mi_inputs(context["mi"])["activity"],
        "data_quality": _data_quality(context["mi"], context["error"]),
    }


def build_evening_facts(
    conn,
    config: Config,
    date_value: str,
    *,
    mi_source: MiHealthSource | None = None,
) -> dict[str, Any]:
    profile = load_profile(config)
    context = collect_mi_context(config, date_value, mi_source)
    readiness = latest_or_compute_readiness(
        conn,
        config,
        date_value,
        mi=context["mi"],
        baseline_rows=context["baseline_rows"],
    )
    trains = get_train_day(conn, date_value)
    food = get_food_range(conn, date_value, date_value)
    totals = totals_for(food)
    targets = target_ranges(profile, training_day=bool(trains))
    week_start = (date.fromisoformat(date_value) - timedelta(days=6)).isoformat()
    previous_start = (date.fromisoformat(date_value) - timedelta(days=13)).isoformat()
    previous_end = (date.fromisoformat(date_value) - timedelta(days=7)).isoformat()
    weekly = {
        "current": sum(float(train.get("volume_kg") or 0) for train in get_train_range(conn, week_start, date_value)),
        "previous": sum(float(train.get("volume_kg") or 0) for train in get_train_range(conn, previous_start, previous_end)),
    }
    return {
        "date": date_value,
        "profile": profile,
        "readiness": readiness,
        "data_quality": _data_quality(context["mi"], context["error"]),
        "trains": [
            {
                "title": train.get("title"),
                "volume_kg": train.get("volume_kg"),
                "sets_total": train.get("sets_total"),
                "sets_completed": train.get("sets_completed"),
                "body_parts": train.get("body_parts"),
                "movements": [
                    {
                        "name": movement.get("name"),
                        "sets": len(movement.get("sets") or []),
                        "volume_kg": movement.get("volume_kg"),
                        "body_parts": movement.get("body_parts"),
                    }
                    for movement in train.get("movements") or []
                ],
            }
            for train in trains
        ],
        "food": totals,
        "meal_distribution": meal_distribution(food),
        "targets": targets,
        "gap": gap(totals, targets),
        "protein_options": protein_food_suggestions(gap(totals, targets)["protein"]["gap_to_min_g"]),
        "weekly_volume": weekly,
    }


def build_weekly_facts(conn, config: Config, date_value: str) -> dict[str, Any]:
    profile = load_profile(config)
    end = date.fromisoformat(date_value)
    start = (end - timedelta(days=6)).isoformat()
    trains = get_train_range(conn, start, date_value)
    food = get_food_range(conn, start, date_value)
    readiness = get_readiness_range(conn, start, date_value)
    dna = compute_dna(conn, start, date_value, bodyweight_kg=profile.get("weight_kg"))
    return {
        "window": {"start": start, "end": date_value},
        "profile": profile,
        "training": {
            "sessions": len(trains),
            "volume_kg": round(sum(float(train.get("volume_kg") or 0) for train in trains), 1),
            "sets": sum(int(train.get("sets_total") or 0) for train in trains),
            "body_parts": _merge_parts(trains),
        },
        "nutrition": totals_for(food),
        "readiness": [
            {"date": row.get("date"), "score": row.get("score"), "tier": row.get("tier")}
            for row in readiness
        ],
        "weights": get_weights(conn, start, date_value),
        "dna": dna,
    }


def _merge_parts(trains: list[dict[str, Any]]) -> dict[str, float]:
    parts: dict[str, float] = {}
    for train in trains:
        for key, value in (train.get("body_parts") or {}).items():
            parts[key] = parts.get(key, 0.0) + float(value or 0)
    return {key: round(value, 1) for key, value in sorted(parts.items(), key=lambda item: item[1], reverse=True)}


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "未知"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _fmt_minutes(value: Any) -> str:
    if value is None:
        return "未知"
    minutes = int(float(value))
    if minutes < 60:
        return f"{minutes} 分"
    return f"{minutes // 60} 小时 {minutes % 60} 分"


def _readiness_header(label: str, readiness: dict[str, Any], *, with_confidence: bool = False) -> str:
    tier = TIER_CN.get(readiness.get("tier"), readiness.get("tier"))
    if readiness.get("tier") == TIER_UNKNOWN:
        return f"**{label}：{tier}**"
    suffix = f"，置信度 {_fmt(readiness.get('confidence'))}" if with_confidence else ""
    return f"**{label}：{tier}**（readiness {_fmt(readiness.get('score'))}/100{suffix}）"


def _freshness_line(data_quality: dict[str, Any] | None) -> str | None:
    data_quality = data_quality or {}
    error = data_quality.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        return f"- 数据提示：小米接口不可用（{message}），结论置信度低。"
    if data_quality.get("mi_present") is False:
        return "- 数据提示：今天没有读到小米数据，结论置信度低。"
    if data_quality.get("stale"):
        as_of = data_quality.get("data_as_of") or "未知"
        return f"- 数据提示：小米数据可能不新（data_as_of {as_of}），建议同步；结论置信度低。"
    return None


def render_morning(facts: dict[str, Any]) -> str:
    readiness = facts["readiness"]
    lines = [_readiness_header("今天", readiness, with_confidence=True)]
    sleep = facts.get("sleep") or {}
    if sleep:
        lines.append(
            f"- 睡眠：{_fmt_minutes(sleep.get('time_asleep_minutes'))}睡着，清醒 {_fmt_minutes(sleep.get('time_awake_minutes'))}，睡眠分 {_fmt(sleep.get('sleep_score'))}"
        )
    if facts.get("hrv"):
        lines.append(f"- HRV：平均 {_fmt(facts['hrv'].get('avg_hrv_ms'))} ms，基线 {_fmt((readiness.get('inputs') or {}).get('baseline', {}).get('hrv'))} ms")
    if facts.get("rhr") is not None:
        lines.append(f"- 静息心率：{_fmt(facts['rhr'])} bpm")
    yesterday = facts.get("yesterday", {})
    if yesterday.get("trains"):
        lines.append(f"- 昨日训练：{len(yesterday['trains'])} 次，训练量 {_fmt(yesterday.get('training_load', {}).get('volume_kg'))} kg")
    lines.append(f"**今天怎么做**：{facts.get('action')}")
    window = facts.get("energy_window") or {}
    if window.get("window"):
        lines.append(f"- 高能窗口：{window['window']}（{window.get('basis')}）")
    if readiness.get("safety_flag"):
        lines.append("- 安全提示：检测到异常心搏事件；如有心悸、胸闷、晕厥感，停止训练并寻求专业评估。")
    if any(reason in (readiness.get("reasons") or []) for reason in ("insufficient_baseline", "short_baseline", "low_data_completeness")):
        lines.append("- 数据提示：历史基线或信号不足，分数仅供参考，今天按保守版本执行。")
    freshness = _freshness_line(facts.get("data_quality"))
    if freshness:
        lines.append(freshness)
    lines.append("你今天的训练时间还是原计划吗？")
    return "\n".join(lines)


def render_preworkout(facts: dict[str, Any]) -> str:
    readiness = facts["readiness"]
    plan = facts.get("plan")
    lines = [_readiness_header("训前判断", readiness)]
    if plan:
        day = plan.get("day") or {}
        title = day.get("title") or day.get("name") or "今日计划"
        movements = day.get("movements") or []
        names = [item.get("name") for item in movements if isinstance(item, dict) and item.get("name")]
        lines.append(f"- 今日计划：{title}" + (f"（{', '.join(names[:6])}）" if names else ""))
    else:
        lines.append("- 今日计划：未读到训记官方计划，将按你的常规安排给建议。")
    action = facts.get("action")
    lines.append(f"- 调整：{action}")
    food = facts.get("today_food", {})
    lines.append(f"- 今日已记录：{_fmt(food.get('totals', {}).get('cal'))} kcal，蛋白 {_fmt(food.get('totals', {}).get('protein'))} g")
    lines.append("- 训前 1 小时：优先易消化碳水 + 20–30 g 蛋白；香蕉 + 牛奶/酸奶/乳清是低门槛组合。")
    freshness = _freshness_line(facts.get("data_quality"))
    if freshness:
        lines.append(freshness)
    lines.append("你今天大概几点进健身房？")
    return "\n".join(lines)


def render_evening(facts: dict[str, Any]) -> str:
    lines = ["**今日复盘**"]
    trains = facts.get("trains") or []
    if trains:
        for train in trains:
            lines.append(
                f"- {train.get('title') or '训练'}：{_fmt(train.get('volume_kg'))} kg，完成组 {_fmt(train.get('sets_completed'))}/{_fmt(train.get('sets_total'))}"
            )
    else:
        lines.append("- 今日无训练记录。")
    weekly = facts.get("weekly_volume") or {}
    if weekly:
        lines.append(f"- 近 7 天训练量 {_fmt(weekly.get('current'))} kg，前 7 天 {_fmt(weekly.get('previous'))} kg。")
    gap_data = facts.get("gap") or {}
    protein = gap_data.get("protein") or {}
    lines.append(
        f"- 蛋白：{_fmt(protein.get('actual_g'))} g，目标 {_fmt(protein.get('target_min_g'))}–{_fmt(protein.get('target_max_g'))} g，缺口 {_fmt(protein.get('gap_to_min_g'))} g。"
    )
    if facts.get("protein_options"):
        options = "；".join(f"{item['food']} {item['serving']}（{item['protein_g']} g）" for item in facts["protein_options"][:3])
        lines.append(f"- 睡前快补可选：{options}")
    freshness = _freshness_line(facts.get("data_quality"))
    if freshness:
        lines.append(freshness)
    lines.append("- 明天只改一个变量：优先补蛋白，或用 10–15 分钟低强度活动替代补偿性有氧。")
    return "\n".join(lines)


def render_weekly(facts: dict[str, Any]) -> str:
    training = facts.get("training") or {}
    nutrition = facts.get("nutrition") or {}
    dna = facts.get("dna") or {}
    lines = [
        f"**周报 {facts['window']['start']} → {facts['window']['end']}**",
        f"- 训练 {_fmt(training.get('sessions'))} 次，总组数 {_fmt(training.get('sets'))}，训练量 {_fmt(training.get('volume_kg'))} kg。",
        f"- 蛋白摄入 {_fmt(nutrition.get('totals', {}).get('protein'))} g（{_fmt(nutrition.get('known_records'))} 条可计算记录）。",
        f"- 训练 DNA 置信度：{dna.get('confidence')}；证据：{'；'.join((dna.get('evidence_ledger') or [])[:3])}。",
    ]
    parts = training.get("body_parts") or {}
    if parts:
        lines.append("- 部位分布：" + "，".join(f"{key} {_fmt(value)}" for key, value in list(parts.items())[:5]))
    lines.append("- 下周调整：只选 1–2 个变量，优先补最低有效量或修正被跳过的部位。")
    return "\n".join(lines)
