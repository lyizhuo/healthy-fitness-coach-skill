"""Command line entry point for the Hermes AI fitness coach."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import ensure_dirs, load_config, require
from .db import add_decision, get_plan_day, init_db, save_dna, save_weight
from .dna import compute_dna
from .normalize import food_totals, normalize_food_record
from .profile import load_profile
from .report import (
    build_evening_facts,
    build_morning_facts,
    build_preworkout_facts,
    build_weekly_facts,
    render_evening,
    render_morning,
    render_preworkout,
    render_weekly,
)
from .sync import backfill, preflight, status as sync_status, sync_day, sync_plan
from .writeback import confirm_custom_food, confirm_food, confirm_train, preview_custom_food, preview_food, preview_train
from .xunji import XunjiClient

PROFILE_TEMPLATE = """# AI Fitness Coach Profile

`profile.json` 是唯一档案来源；这个 Markdown 只是人读的备份。
把下面各项填成你的真实信息，或让 agent 用 onboarding 写入 `profile.json`。
不要提交真实个人信息到公开仓库。

- weight_kg: TODO
- height_cm: TODO
- age: TODO
- sex: TODO
- goal: hypertrophy
- training_days_per_week: 5
- training_time: 18:30
- timezone: Asia/Shanghai
- training_venue: gym
- available_equipment: TODO
- injury_or_medical_constraints: none
- diet_context: canteen / takeout
"""

DECISIONS_TEMPLATE = """# AI Coach Decisions

每条记录包含：日期、证据、判断、行动、下一次验证。`coach decision` 会自动追加。

"""


def _json_dump(value, stream=sys.stdout) -> None:
    json.dump(value, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def _date_arg(value: str | None) -> str:
    if value:
        return date.fromisoformat(value).isoformat()
    config = load_config()
    return datetime.now(config.timezone).date().isoformat()


def cmd_init(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    if not config.profile_path.exists():
        config.profile_path.write_text(PROFILE_TEMPLATE, encoding="utf-8")
    if not config.decisions_path.exists():
        config.decisions_path.write_text(DECISIONS_TEMPLATE, encoding="utf-8")
    _json_dump({"status": "initialized", "home": str(config.home), "db": str(config.db_path)})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    _json_dump(sync_status(conn, config))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    _json_dump(preflight(conn, config))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    end = date.fromisoformat(args.end) if args.end else date.fromisoformat(_date_arg(None))
    result = backfill(
        conn,
        config,
        days=args.days,
        end=end,
        full=args.full,
        delay=not args.no_delay,
    )
    _json_dump(result)
    return 0


def cmd_sync_day(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    client = XunjiClient(config)
    _json_dump(sync_day(conn, config, client, _date_arg(args.date), full=not args.light, delay=not args.no_delay))
    return 0


def cmd_sync_plan(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    _json_dump(sync_plan(conn, config, start_date=args.start, end_date=args.end))
    return 0


def cmd_search_food(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    client = XunjiClient(config)
    _json_dump(client.search_food(args.keyword, limit=args.limit, delay=not args.no_delay))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    plan = get_plan_day(conn, _date_arg(args.date))
    _json_dump(plan or {"status": "not_found", "date": _date_arg(args.date), "hint": "先运行 sync-plan"})
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    date_value = _date_arg(args.date)
    if args.kind == "morning":
        facts = build_morning_facts(conn, config, date_value)
        text = render_morning(facts)
    elif args.kind == "preworkout":
        facts = build_preworkout_facts(conn, config, date_value)
        text = render_preworkout(facts)
    elif args.kind == "evening":
        facts = build_evening_facts(conn, config, date_value)
        text = render_evening(facts)
    else:
        facts = build_weekly_facts(conn, config, date_value)
        text = render_weekly(facts)
    if args.format == "json":
        _json_dump(facts)
    else:
        print(text)
    return 0


def cmd_readiness(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    facts = build_morning_facts(conn, config, _date_arg(args.date))
    _json_dump(facts["readiness"])
    return 0


def cmd_dna(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    end = date.fromisoformat(args.end) if args.end else date.fromisoformat(_date_arg(None))
    start = end - timedelta(days=max(1, args.weeks) * 7 - 1)
    profile = load_profile(config)
    dna = compute_dna(conn, start.isoformat(), end.isoformat(), bodyweight_kg=profile.get("weight_kg"))
    save_dna(conn, dna)
    _json_dump(dna)
    return 0


def cmd_photo(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else json.load(sys.stdin)
    date_value = payload.get("date") or _date_arg(args.date)
    meal_type = payload.get("meal_type") or "lunch"
    items = payload.get("items") or payload.get("foods") or []
    records = []
    for item in items:
        record = normalize_food_record(
            {
                "date": date_value,
                "meal_type": meal_type,
                **item,
            }
        )
        records.append(record)
    totals = food_totals(records)
    _json_dump({"date": date_value, "meal_type": meal_type, "records": records, "totals": totals})
    return 0


def cmd_weight(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    save_weight(conn, _date_arg(args.date), float(args.kg), source=args.source, note=args.note)
    _json_dump({"status": "saved", "date": _date_arg(args.date), "weight_kg": float(args.kg)})
    return 0


def cmd_decision(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    evidence = json.loads(args.evidence) if args.evidence else None
    decision_id = add_decision(
        conn,
        date_value=_date_arg(args.date),
        kind=args.kind,
        summary=args.summary,
        evidence=evidence,
        action=args.action,
        verification=args.verification,
        decisions_path=config.decisions_path,
    )
    _json_dump({"status": "saved", "id": decision_id})
    return 0


def cmd_writeback(args: argparse.Namespace) -> int:
    config = load_config()
    ensure_dirs(config)
    conn = init_db(config.db_path)
    client = XunjiClient(config)
    if args.action in ("preview-train", "preview-food", "preview-custom-food"):
        payload = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else json.load(sys.stdin)
        if args.action == "preview-train":
            records = payload.get("trains") if isinstance(payload, dict) else payload
            result = preview_train(conn, client, records)
        elif args.action == "preview-food":
            records = payload.get("foods") if isinstance(payload, dict) else payload
            result = preview_food(conn, client, records)
        else:
            food = payload.get("food") if isinstance(payload, dict) else payload
            result = preview_custom_food(conn, client, food)
        _json_dump(result)
        return 0 if result.get("status") == "preview" else 1
    if args.action == "confirm-train":
        result = confirm_train(conn, client, require(args.preview_id, "--preview-id"))
    elif args.action == "confirm-food":
        result = confirm_food(conn, client, require(args.preview_id, "--preview-id"))
    else:
        result = confirm_custom_food(conn, client, require(args.preview_id, "--preview-id"))
    _json_dump(result)
    return 0 if result.get("status") == "confirmed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-coach", description="Hermes AI fitness coach data tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="initialize the coach data directory")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="show local data and env status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("preflight", help="check profile, keys, and data before onboarding")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("sync", help="backfill Xunji training and food data")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--end")
    p.add_argument("--full", action="store_true", help="use full training reads (slower, includes RPE/notes)")
    p.add_argument("--no-delay", action="store_true", help="skip rate-limit sleeps (tests only)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("sync-day")
    p.add_argument("--date")
    p.add_argument("--light", action="store_true")
    p.add_argument("--no-delay", action="store_true")
    p.set_defaults(func=cmd_sync_day)

    p = sub.add_parser("sync-plan")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(func=cmd_sync_plan)

    p = sub.add_parser("search-food")
    p.add_argument("--keyword", required=True)
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--no-delay", action="store_true")
    p.set_defaults(func=cmd_search_food)

    p = sub.add_parser("plan")
    p.add_argument("--date")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("facts")
    p.add_argument("kind", choices=["morning", "preworkout", "evening", "weekly"])
    p.add_argument("--date")
    p.add_argument("--format", choices=["json", "markdown"], default="json")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("readiness")
    p.add_argument("--date")
    p.set_defaults(func=cmd_readiness)

    p = sub.add_parser("dna")
    p.add_argument("--weeks", type=int, default=8)
    p.add_argument("--end")
    p.set_defaults(func=cmd_dna)

    p = sub.add_parser("photo", help="compute macros for vision-estimated food items")
    p.add_argument("--input")
    p.add_argument("--date")
    p.set_defaults(func=cmd_photo)

    p = sub.add_parser("weight")
    p.add_argument("--date")
    p.add_argument("--kg", type=float, required=True)
    p.add_argument("--source", default="manual")
    p.add_argument("--note")
    p.set_defaults(func=cmd_weight)

    p = sub.add_parser("decision")
    p.add_argument("--date")
    p.add_argument("--kind", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--evidence")
    p.add_argument("--action")
    p.add_argument("--verification")
    p.set_defaults(func=cmd_decision)

    p = sub.add_parser("writeback")
    p.add_argument("action", choices=["preview-train", "preview-food", "preview-custom-food", "confirm-train", "confirm-food", "confirm-custom-food"])
    p.add_argument("--input")
    p.add_argument("--preview-id")
    p.set_defaults(func=cmd_writeback)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
