"""Preview-first writeback for training and food records."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .db import create_operation, get_operation, update_operation
from .http import ApiError
from .normalize import normalize_date

PREVIEW_TTL = timedelta(minutes=10)


def _age(created_at: str | None) -> timedelta:
    if not created_at:
        return timedelta.max
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return datetime.now(UTC) - created
    except ValueError:
        return timedelta.max


def validate_train_records(records: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list) or not records:
        return ["records must be a non-empty list"]
    if len(records) > 4:
        errors.append("at most 4 trains per request")
    dates = {normalize_date(item.get("datestr") or item.get("date")) for item in records if isinstance(item, dict)}
    if len(dates) != 1 or None in dates:
        errors.append("all trains must belong to the same valid date")
    for index, train in enumerate(records):
        if not isinstance(train, dict):
            errors.append(f"train[{index}] must be an object")
            continue
        movements = train.get("movements")
        if not isinstance(movements, list) or not movements:
            errors.append(f"train[{index}] needs movements")
            continue
        if len(movements) > 15:
            errors.append(f"train[{index}] has more than 15 movements")
        for movement_index, movement in enumerate(movements):
            if not isinstance(movement, dict) or not movement.get("name"):
                errors.append(f"train[{index}].movements[{movement_index}] needs name")
                continue
            sets = movement.get("sets")
            if sets is not None:
                if len(sets) > 20:
                    errors.append(f"train[{index}].movements[{movement_index}] has more than 20 sets")
                for set_index, item in enumerate(sets):
                    if not isinstance(item, dict):
                        errors.append(f"train[{index}].movements[{movement_index}].sets[{set_index}] must be an object")
                        continue
                    if not any(key in item for key in ("weight", "weight_kg", "reps", "time", "duration_s", "selfWeight")):
                        errors.append(f"train[{index}].movements[{movement_index}].sets[{set_index}] needs weight/reps/time/selfWeight")
    return errors


def validate_food_records(foods: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(foods, list) or not foods:
        return ["foods must be a non-empty list"]
    today = date.today()
    for index, item in enumerate(foods):
        if not isinstance(item, dict):
            errors.append(f"foods[{index}] must be an object")
            continue
        date_value = normalize_date(item.get("date"))
        if not date_value:
            errors.append(f"foods[{index}] needs a valid date")
        else:
            target = date.fromisoformat(date_value)
            if target < today - timedelta(days=365) or target > today + timedelta(days=92):
                errors.append(f"foods[{index}] date outside the allowed range (past 1 year to next 3 months)")
        if not item.get("meal_type"):
            errors.append(f"foods[{index}] needs meal_type")
        if not item.get("name"):
            errors.append(f"foods[{index}] needs name")
        if item.get("amount") is None:
            errors.append(f"foods[{index}] needs amount")
        if not item.get("unit"):
            errors.append(f"foods[{index}] needs unit")
        ntr = item.get("ntr")
        if not isinstance(ntr, dict) or not all(key in ntr for key in ("cal", "protein", "fat", "carb")):
            errors.append(f"foods[{index}] needs per-100g ntr with cal/protein/fat/carb")
    return errors


def validate_custom_food(food: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(food, dict):
        return ["food must be an object"]
    if not food.get("name"):
        errors.append("food.name is required")
    ntr = food.get("ntr")
    if not isinstance(ntr, dict) or not all(key in ntr for key in ("cal", "protein", "fat", "carb")):
        errors.append("food.ntr needs per-100g cal/protein/fat/carb")
    units = food.get("units")
    if units is not None:
        if not isinstance(units, list):
            errors.append("food.units must be a list")
        else:
            for index, unit in enumerate(units):
                if not isinstance(unit, dict) or not unit.get("unit") or unit.get("gram") is None:
                    errors.append(f"food.units[{index}] needs unit and gram")
    return errors


def _preview_payload(kind: str, client_request_id: str, records: Any, server: Any, warnings: list[str]) -> dict[str, Any]:
    return {
        "preview_id": client_request_id,
        "kind": kind,
        "status": "preview",
        "records": records,
        "server_dry_run": server is not None,
        "server_response": server,
        "warnings": warnings,
        "instructions": "展示变更摘要并等待用户确认；确认后调用 confirm，10 分钟内有效。",
    }


def preview_train(conn, client, records: Any) -> dict[str, Any]:
    errors = validate_train_records(records)
    if errors:
        return {"status": "invalid", "errors": errors}
    preview_id = str(uuid.uuid4())
    server = None
    warnings: list[str] = []
    try:
        server = client.upsert_trains(records, client_request_id=preview_id, dry_run=True, include_full_data=True)
    except ApiError as exc:
        warnings.append(f"server_dry_run_failed:{exc.code or exc.status or 'unknown'}")
    create_operation(conn, preview_id, "train_upsert", records, status="preview")
    return _preview_payload("train_upsert", preview_id, records, server, warnings)


def confirm_train(conn, client, preview_id: str) -> dict[str, Any]:
    operation = get_operation(conn, preview_id)
    if not operation:
        return {"status": "not_found"}
    if operation["status"] != "preview":
        return {"status": "not_preview", "current_status": operation["status"]}
    if _age(operation.get("created_at")) > PREVIEW_TTL:
        update_operation(conn, preview_id, "expired")
        return {"status": "expired"}
    try:
        response = client.upsert_trains(
            json.loads(operation["payload_json"]),
            client_request_id=preview_id,
            dry_run=False,
            include_full_data=True,
        )
    except ApiError as exc:
        status = "unknown" if exc.status is None or exc.status >= 500 else "failed"
        update_operation(conn, preview_id, status, {"error": str(exc), "code": exc.code})
        return {"status": status, "error": str(exc), "code": exc.code, "retry_after_ms": exc.retry_after_ms}
    update_operation(conn, preview_id, "confirmed", response)
    return {"status": "confirmed", "response": response}


def preview_food(conn, client, foods: Any) -> dict[str, Any]:
    errors = validate_food_records(foods)
    if errors:
        return {"status": "invalid", "errors": errors}
    preview_id = str(uuid.uuid4())
    server = None
    warnings: list[str] = []
    try:
        server = client.upsert_foods(foods, client_request_id=preview_id, dry_run=True)
    except ApiError as exc:
        warnings.append(f"server_dry_run_failed:{exc.code or exc.status or 'unknown'}")
    create_operation(conn, preview_id, "food_upsert", foods, status="preview")
    return _preview_payload("food_upsert", preview_id, foods, server, warnings)


def confirm_food(conn, client, preview_id: str) -> dict[str, Any]:
    operation = get_operation(conn, preview_id)
    if not operation:
        return {"status": "not_found"}
    if operation["status"] != "preview":
        return {"status": "not_preview", "current_status": operation["status"]}
    if _age(operation.get("created_at")) > PREVIEW_TTL:
        update_operation(conn, preview_id, "expired")
        return {"status": "expired"}
    try:
        response = client.upsert_foods(
            json.loads(operation["payload_json"]),
            client_request_id=preview_id,
            dry_run=False,
        )
    except ApiError as exc:
        status = "unknown" if exc.status is None or exc.status >= 500 else "failed"
        update_operation(conn, preview_id, status, {"error": str(exc), "code": exc.code})
        return {"status": status, "error": str(exc), "code": exc.code, "retry_after_ms": exc.retry_after_ms}
    update_operation(conn, preview_id, "confirmed", response)
    return {"status": "confirmed", "response": response}


def preview_custom_food(conn, client, food: Any) -> dict[str, Any]:
    errors = validate_custom_food(food)
    if errors:
        return {"status": "invalid", "errors": errors}
    preview_id = str(uuid.uuid4())
    server = None
    warnings: list[str] = []
    try:
        server = client.create_custom_food(food, client_request_id=preview_id, dry_run=True)
    except ApiError as exc:
        warnings.append(f"server_dry_run_failed:{exc.code or exc.status or 'unknown'}")
    create_operation(conn, preview_id, "custom_food_upsert", food, status="preview")
    return _preview_payload("custom_food_upsert", preview_id, food, server, warnings)


def confirm_custom_food(conn, client, preview_id: str) -> dict[str, Any]:
    operation = get_operation(conn, preview_id)
    if not operation:
        return {"status": "not_found"}
    if operation["status"] != "preview":
        return {"status": "not_preview", "current_status": operation["status"]}
    if _age(operation.get("created_at")) > PREVIEW_TTL:
        update_operation(conn, preview_id, "expired")
        return {"status": "expired"}
    try:
        response = client.create_custom_food(
            json.loads(operation["payload_json"]),
            client_request_id=preview_id,
            dry_run=False,
        )
    except ApiError as exc:
        status = "unknown" if exc.status is None or exc.status >= 500 else "failed"
        update_operation(conn, preview_id, status, {"error": str(exc), "code": exc.code})
        return {"status": status, "error": str(exc), "code": exc.code, "retry_after_ms": exc.retry_after_ms}
    update_operation(conn, preview_id, "confirmed", response)
    return {"status": "confirmed", "response": response}
