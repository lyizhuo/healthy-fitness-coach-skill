"""Sync Xunji data into the local coach database.

Xiaomi data is not stored locally; it is read live from mi-health by
``coach.mi_source`` when facts/readiness are requested.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any

from .config import Config
from .db import (
    save_food_day,
    save_plan,
    save_train_day,
)
from .http import ApiError
from .normalize import normalize_food_day, normalize_train_day
from .profile import load_profile
from .xunji import XunjiClient


def sync_day(conn, config: Config, client: XunjiClient, date_value: str, *, full: bool = True, delay: bool = True, parallel: bool = True) -> dict[str, Any]:
    profile = load_profile(config)
    bodyweight = profile.get("weight_kg")
    try:
        bodyweight_value = float(bodyweight) if bodyweight else None
    except (TypeError, ValueError):
        bodyweight_value = None
    if parallel:
        with ThreadPoolExecutor(max_workers=2) as pool:
            train_future = pool.submit(client.fetch_train_day, date_value, full=full, delay=delay)
            food_future = pool.submit(client.fetch_food_day, date_value, delay=delay)
            raw_train = train_future.result()
            raw_food = food_future.result()
    else:
        raw_train = client.fetch_train_day(date_value, full=full, delay=delay)
        raw_food = client.fetch_food_day(date_value, delay=delay)
    trains = normalize_train_day(raw_train, date_value=date_value, bodyweight_kg=bodyweight_value)
    save_train_day(conn, date_value, trains, raw_train)
    records = normalize_food_day(raw_food, date_value=date_value)
    save_food_day(conn, date_value, records, raw_food)
    return {
        "date": date_value,
        "trains": len(trains),
        "sets": sum(int(item.get("sets_total") or 0) for item in trains),
        "food_records": len(records),
        "food_known": sum(1 for item in records if item.get("macro_known")),
        "warnings": sorted({warning for item in trains for warning in item.get("warnings") or []}),
    }


def backfill(
    conn,
    config: Config,
    *,
    days: int = 90,
    end: date | None = None,
    full: bool = False,
    delay: bool = True,
) -> dict[str, Any]:
    client = XunjiClient(config)
    end_date = end or datetime.now(config.timezone).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)
    synced: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        date_value = current.isoformat()
        try:
            synced.append(sync_day(conn, config, client, date_value, full=full, delay=delay))
        except ApiError as exc:
            errors.append({"date": date_value, "error": str(exc), "code": exc.code})
            if exc.code in ("auth_error", "vip_required"):
                break
        current += timedelta(days=1)
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days": (end_date - start_date).days + 1,
        "synced": synced,
        "errors": errors,
    }


def sync_plan(conn, config: Config, *, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    client = XunjiClient(config)
    listing = client.fetch_plan_list()
    plans = []
    if isinstance(listing, dict):
        plans = listing.get("plans") or listing.get("res") or []
    if not isinstance(plans, list):
        plans = []
    saved = 0
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        plan_ref = plan.get("plan_ref") or plan.get("ref") or plan.get("id")
        if not plan_ref:
            continue
        result = client.fetch_plan(str(plan_ref), start_date, end_date)
        days = result.get("days") if isinstance(result, dict) else None
        if isinstance(days, dict):
            days = [
                dict(value, date=key) if isinstance(value, dict) else {"date": key, "value": value}
                for key, value in days.items()
            ]
        if isinstance(days, list):
            saved += save_plan(conn, str(plan_ref), days)
    return {"plans": len(plans), "days_saved": saved}


def status(conn, config: Config) -> dict[str, Any]:
    trains = conn.execute("SELECT COUNT(*) AS count, MIN(date) AS first, MAX(date) AS last FROM trains").fetchone()
    foods = conn.execute("SELECT COUNT(*) AS count, MIN(date) AS first, MAX(date) AS last FROM food_records").fetchone()
    readiness = conn.execute("SELECT COUNT(*) AS count, MIN(date) AS first, MAX(date) AS last FROM readiness").fetchone()
    profile = load_profile(config)
    profile_json = (config.home / "profile.json").exists()
    return {
        "home": str(config.home),
        "db": str(config.db_path),
        "profile": {
            "exists": profile_json,
            "markdown_exists": config.profile_path.exists(),
            "weight_kg": profile.get("weight_kg"),
            "goal": profile.get("goal"),
            "training_time": profile.get("training_time"),
        },
        "trains": dict(trains),
        "food": dict(foods),
        "readiness": dict(readiness),
        "mi_health": {
            "mode": "live",
            "base_url": config.mi_health_base_url,
            "api_key": bool(config.mi_health_api_key),
        },
        "env": {
            "MI_HEALTH_BASE_URL": bool(config.mi_health_base_url),
            "MI_HEALTH_API_KEY": bool(config.mi_health_api_key),
            "XUNJI_TRAIN_API_KEY": bool(config.xunji_train_key),
            "XUNJI_FOOD_API_KEY": bool(config.xunji_food_key),
            "XUNJI_FOOD_SEARCH_API_KEY": bool(config.xunji_food_search_key),
        },
    }


PROFILE_REQUIRED = (
    "weight_kg",
    "height_cm",
    "age",
    "sex",
    "goal",
    "training_days_per_week",
    "training_time",
    "training_venue",
    "available_equipment",
    "injury_or_medical_constraints",
    "diet_context",
    "timezone",
)

PROFILE_POSITIVE = {"weight_kg", "height_cm", "age", "training_days_per_week"}


def _missing(key: str, value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        if value.strip().lower() in ("", "todo", "unknown", "未知", "null"):
            return True
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    if key in PROFILE_POSITIVE:
        try:
            return float(value) <= 0
        except (TypeError, ValueError):
            return True
    return False


def preflight(conn, config: Config) -> dict[str, Any]:
    import os

    profile_path = config.home / "profile.json"
    profile_exists = profile_path.exists()
    if profile_exists:
        try:
            raw_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw_profile = {}
        if not isinstance(raw_profile, dict):
            raw_profile = {}
        missing_profile = [key for key in PROFILE_REQUIRED if _missing(key, raw_profile.get(key))]
    else:
        missing_profile = list(PROFILE_REQUIRED)
    missing_env = [
        name
        for name, present in (
            ("MI_HEALTH_API_KEY", bool(config.mi_health_api_key)),
            ("XUNJI_TRAIN_API_KEY", bool(config.xunji_train_key)),
            ("XUNJI_FOOD_API_KEY", bool(config.xunji_food_key)),
            ("XUNJI_FOOD_SEARCH_API_KEY", bool(config.xunji_food_search_key)),
        )
        if not present
    ]
    base_url_defaulted = not bool(os.environ.get("MI_HEALTH_BASE_URL"))
    counts = {
        "trains": conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0],
        "food_records": conn.execute("SELECT COUNT(*) FROM food_records").fetchone()[0],
        "readiness": conn.execute("SELECT COUNT(*) FROM readiness").fetchone()[0],
        "plan_days": conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0],
    }
    questions: list[str] = []
    if missing_env:
        questions.append("把这些 key 写入 ~/.hermes/.env（不要发在聊天里）：" + "、".join(missing_env))
    if base_url_defaulted:
        questions.append("mi-health 用云端地址还是本机 http://127.0.0.1:8330？脚本走同源 REST /api/*，MCP 走 /mcp/。")
    if missing_profile:
        field_text = "、".join(missing_profile)
        questions.append(f"补个人档案（每批最多 6 个，未知写 null）：{field_text}。我写入 profile.json。")
    questions.append("晨间、训前提前量、晚间、周报的 cron 时间要设成几点？默认 07:30 / 训练前 2 小时 / 21:00 / 周日 21:00。")
    if counts["plan_days"] == 0:
        questions.append("你是否在使用训记官方计划？如果是，我先 sync-plan 再读今天计划。")
    if config.mi_health_api_key:
        questions.append(f"小米数据实时读取自 {config.mi_health_base_url}；确认 Hermes 主机能访问该地址。")
    status_value = "ready" if not missing_env and not missing_profile else "needs_input"
    return {
        "status": status_value,
        "missing_profile": missing_profile,
        "missing_env": missing_env,
        "mi_health_base_url": {
            "value": config.mi_health_base_url,
            "defaulted": base_url_defaulted,
        },
        "counts": counts,
        "data_ready": bool(counts["trains"] or counts["food_records"] or counts["readiness"] or counts["plan_days"]),
        "questions": questions,
    }
