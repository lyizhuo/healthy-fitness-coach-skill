"""Normalize Xunji training, plan, and food payloads into stable records."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

BODY_PART_PATTERNS = [
    ("chest", r"胸|卧推|飞鸟|夹胸|俯卧撑"),
    ("back", r"背|划船|下拉|引体|硬拉|耸肩"),
    ("shoulders", r"肩|推举|侧平举|前平举|面拉"),
    ("legs", r"腿|深蹲|硬拉|腿举|弓步|提踵|臀|髋|股四头|腘绳"),
    ("biceps", r"二头|弯举"),
    ("triceps", r"三头|臂屈伸|下压"),
    ("arms", r"手臂|前臂|腕"),
    ("core", r"核心|腹|卷腹|平板|抗旋"),
    ("calves", r"小腿|提踵"),
]

AEROBIC_PATTERN = re.compile(r"跑|骑|走|游泳|划船|椭圆|有氧|跳绳|hiit|cardio", re.IGNORECASE)


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None else None


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_date(value: Any) -> str | None:
    raw = text(value)
    if not raw:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return None
    match = re.search(r"(\d{4})(\d{2})(\d{2})", raw)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    return None


def epoch_ms(value: Any) -> int | None:
    parsed = number(value)
    if parsed is None:
        return None
    if parsed < 10_000_000_000:
        parsed *= 1000
    return int(parsed)


def body_parts_for(name: str, type_value: str = "") -> list[str]:
    haystack = f"{name} {type_value}"
    parts = [part for part, pattern in BODY_PART_PATTERNS if re.search(pattern, haystack, re.IGNORECASE)]
    return sorted(set(parts))


def is_aerobic(name: str, type_value: str = "", cardio: bool = False) -> bool:
    return bool(cardio) or bool(AEROBIC_PATTERN.search(f"{name} {type_value}"))


def normalize_set(raw: dict[str, Any], *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    unit = text(raw.get("unit") or raw.get("weight_unit") or "kg").lower()
    weight = number(raw.get("weight") or raw.get("weight_kg"))
    reps = number(raw.get("reps"))
    time_value = number(raw.get("time") or raw.get("duration_s") or raw.get("seconds"))
    self_weight = bool(raw.get("selfWeight") or raw.get("self_weight"))
    done = raw.get("done")
    if done is None:
        done = True
    volume_kg = None
    if reps is not None:
        if self_weight and bodyweight_kg:
            volume_kg = bodyweight_kg * reps
        elif weight is not None:
            weight_kg = weight * 0.45359237 if unit in ("lb", "lbs", "磅") else weight
            volume_kg = weight_kg * reps
    return {
        "index": integer(raw.get("index")),
        "done": bool(done),
        "weight": weight,
        "unit": unit,
        "reps": reps,
        "time_s": time_value,
        "rpe": text(raw.get("rpe")) or None,
        "set_type": text(raw.get("setType") or raw.get("set_type")) or None,
        "self_weight": self_weight,
        "note": text(raw.get("note")) or None,
        "comment": text(raw.get("comment")) or None,
        "rest_seconds": number(raw.get("restSeconds") or raw.get("rest_seconds")),
        "volume_kg": round(volume_kg, 3) if volume_kg is not None else None,
        "items": raw.get("items") or [],
        "drop_sets": raw.get("dropSets") or raw.get("drop_sets") or [],
    }


def normalize_movement(raw: dict[str, Any], *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    name = text(raw.get("name") or raw.get("title"))
    type_value = text(raw.get("type"))
    cardio = bool(raw.get("cardio"))
    sets = [normalize_set(item, bodyweight_kg=bodyweight_kg) for item in (raw.get("sets") or []) if isinstance(item, dict)]
    completed_sets = [item for item in sets if item["done"]]
    volume = sum(item["volume_kg"] for item in completed_sets if item["volume_kg"] is not None)
    planned_volume = sum(item["volume_kg"] for item in sets if item["volume_kg"] is not None)
    return {
        "index": integer(raw.get("index")),
        "name": name,
        "type": type_value or None,
        "exetype": text(raw.get("exetype")) or None,
        "rest_time": number(raw.get("restTime") or raw.get("rest_time")),
        "warn_rest_time": number(raw.get("warn_restTime") or raw.get("warn_rest_time")),
        "difficulty": text(raw.get("difficulty")) or None,
        "single_side": bool(raw.get("singleSide") or raw.get("single_side")),
        "cardio": cardio,
        "aerobic": is_aerobic(name, type_value, cardio),
        "metrics": raw.get("metrics") or {},
        "sets": sets,
        "volume_kg": round(volume, 3),
        "planned_volume_kg": round(planned_volume, 3),
        "body_parts": body_parts_for(name, type_value),
    }


def normalize_train(raw: dict[str, Any], *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    movements = [
        normalize_movement(item, bodyweight_kg=bodyweight_kg)
        for item in (raw.get("movements") or [])
        if isinstance(item, dict)
    ]
    sets = [item for movement in movements for item in movement["sets"]]
    completed = [item for item in sets if item["done"]]
    volume = sum(item["volume_kg"] for item in sets if item["done"] and item["volume_kg"] is not None)
    planned_volume = sum(item["volume_kg"] for item in sets if item["volume_kg"] is not None)
    body_parts: dict[str, float] = {}
    for movement in movements:
        for part in movement["body_parts"]:
            body_parts[part] = body_parts.get(part, 0) + movement["volume_kg"]
    warnings: list[str] = []
    units = {item["unit"] for item in sets if item["weight"] is not None}
    if len(units) > 1:
        warnings.append("mixed_units")
    if any(item["self_weight"] for item in sets) and not bodyweight_kg:
        warnings.append("self_weight_without_bodyweight")
    if any(item["weight"] is not None and item["weight"] >= 500 for item in sets):
        warnings.append("extreme_weight")
    note = raw.get("note")
    if isinstance(note, str) and note.strip().startswith("{"):
        try:
            import json

            note = json.loads(note)
        except ValueError:
            pass
    return {
        "localid": raw.get("localid") or raw.get("id"),
        "date": normalize_date(raw.get("datestr") or raw.get("date") or raw.get("record_date")),
        "title": text(raw.get("title") or raw.get("name")) or None,
        "start_ms": epoch_ms(raw.get("start") or raw.get("start_at")),
        "end_ms": epoch_ms(raw.get("end") or raw.get("end_at")),
        "note": note,
        "movements": movements,
        "sets": sets,
        "sets_total": len(sets),
        "sets_completed": len(completed),
        "volume_kg": round(volume, 3),
        "planned_volume_kg": round(planned_volume, 3),
        "body_parts": {key: round(value, 3) for key, value in sorted(body_parts.items())},
        "heart_rate": raw.get("heartRate") or raw.get("heart_rate"),
        "warnings": sorted(set(warnings)),
        "raw": raw,
    }


def normalize_train_day(raw: dict[str, Any], *, date_value: str | None = None, bodyweight_kg: float | None = None) -> list[dict[str, Any]]:
    trains = raw.get("trains") if isinstance(raw, dict) else None
    if trains is None and isinstance(raw, dict) and isinstance(raw.get("res"), dict):
        trains = raw["res"].get("trains")
    if trains is None and isinstance(raw, list):
        trains = raw
    result = []
    for item in trains or []:
        if not isinstance(item, dict):
            continue
        normalized = normalize_train(item, bodyweight_kg=bodyweight_kg)
        normalized["date"] = normalized["date"] or normalize_date(item.get("datestr") or date_value)
        result.append(normalized)
    return result


def _first_number(ntr: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in ntr:
            parsed = number(ntr[key])
            if parsed is not None:
                return parsed
    return None


def normalize_food_record(raw: dict[str, Any]) -> dict[str, Any]:
    ntr = raw.get("ntr") or raw.get("nrt") or {}
    if not isinstance(ntr, dict):
        ntr = {}
    amount = number(raw.get("amount"))
    unit = text(raw.get("unit")).lower()
    units = raw.get("units") or ntr.get("foodUnit") or ntr.get("food_unit") or []
    if not isinstance(units, list):
        units = []
    factor = None
    if amount is not None:
        if unit in ("g", "克", "gram", "grams"):
            factor = amount / 100.0
        else:
            for entry in units:
                if not isinstance(entry, dict):
                    continue
                candidate = text(entry.get("unit")).lower()
                if candidate and candidate == unit:
                    gram = number(entry.get("gram"))
                    count = number(entry.get("count")) or 1.0
                    if gram is not None:
                        factor = amount * gram / count / 100.0
                    break
    cal = _first_number(ntr, "cal", "calories", "kcal")
    protein = _first_number(ntr, "protein", "蛋白质")
    fat = _first_number(ntr, "fat", "脂肪")
    carb = _first_number(ntr, "carb", "carbs", "碳水")
    record_cal = _first_number(raw, "cals", "calories", "kcal")
    macro_known = factor is not None and all(value is not None for value in (cal, protein, fat, carb))
    basis = "unknown"
    macros = {"cal": None, "protein": None, "fat": None, "carb": None}
    if macro_known:
        per100 = {key: value * factor for key, value in (("cal", cal), ("protein", protein), ("fat", fat), ("carb", carb))}
        if record_cal is not None:
            # Query records may expose ntr as the recorded amount rather than per 100g.
            if abs(record_cal - cal) <= abs(record_cal - per100["cal"]):
                basis = "record"
                macros = {"cal": cal, "protein": protein, "fat": fat, "carb": carb}
            else:
                basis = "per_100g"
                macros = per100
        else:
            basis = "per_100g"
            macros = per100
    return {
        "record_id": raw.get("record_id") or raw.get("id") or raw.get("localid"),
        "date": normalize_date(raw.get("date") or raw.get("datestr")),
        "meal_type": text(raw.get("meal_type") or raw.get("meal") or raw.get("mealType")) or "unknown",
        "name": text(raw.get("name") or raw.get("food_name")) or None,
        "amount": amount,
        "unit": unit,
        "uniquekey": raw.get("uniquekey") or raw.get("unique_key"),
        "ntr": {"cal": cal, "protein": protein, "fat": fat, "carb": carb},
        "factor": factor,
        "macro_basis": basis,
        "macros": {
            "cal": round(macros["cal"], 2) if macro_known else None,
            "protein": round(macros["protein"], 2) if macro_known else None,
            "fat": round(macros["fat"], 2) if macro_known else None,
            "carb": round(macros["carb"], 2) if macro_known else None,
        },
        "macro_known": macro_known,
        "raw": raw,
    }


def _walk_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
    elif isinstance(value, dict):
        for key in ("records", "foods", "items", "data", "days"):
            if key in value:
                yield from _walk_records(value[key])
        if any(key in value for key in ("name", "ntr", "nrt", "record_id")):
            yield value


def normalize_food_day(raw: Any, *, date_value: str | None = None) -> list[dict[str, Any]]:
    records = [item for item in _walk_records(raw)]
    result = []
    seen = set()
    for item in records:
        normalized = normalize_food_record(item)
        normalized["date"] = normalized["date"] or normalize_date(date_value)
        key = (normalized["date"], normalized["record_id"], normalized["name"], normalized["amount"], normalized["unit"])
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def food_totals(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    totals = {"cal": 0.0, "protein": 0.0, "fat": 0.0, "carb": 0.0}
    known = 0
    unknown = 0
    for record in records:
        if record.get("macro_known"):
            known += 1
            for key in totals:
                totals[key] += float(record["macros"][key] or 0)
        else:
            unknown += 1
    return {
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "known_records": known,
        "unknown_records": unknown,
        "complete": unknown == 0,
    }
