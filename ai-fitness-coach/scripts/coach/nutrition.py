"""Nutrition targets, macro accounting, and deficit/surplus gaps."""

from __future__ import annotations

from typing import Any, Iterable

from .normalize import food_totals


def protein_target(weight_kg: float | None) -> dict[str, float | None]:
    if not weight_kg or float(weight_kg) <= 0:
        return {"min_g": None, "max_g": None}
    weight = float(weight_kg)
    return {"min_g": round(weight * 1.6, 1), "max_g": round(weight * 2.0, 1)}


def estimate_bmr(profile: dict[str, Any]) -> float | None:
    def as_float(value: Any) -> float | None:
        try:
            parsed = float(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    weight = as_float(profile.get("weight_kg"))
    height = as_float(profile.get("height_cm"))
    age = as_float(profile.get("age"))
    sex = str(profile.get("sex", "")).lower()
    if not all(value for value in (weight, height, age)):
        return None
    base = 10 * weight + 6.25 * height - 5 * age
    if sex in ("male", "m", "男"):
        return round(base + 5, 1)
    if sex in ("female", "f", "女"):
        return round(base - 161, 1)
    return round(base - 78, 1)


def target_ranges(profile: dict[str, Any], *, training_day: bool = True) -> dict[str, Any]:
    weight_value = profile.get("weight_kg")
    try:
        weight = float(weight_value) if weight_value else 0.0
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0:
        return {
            "weight_kg": None,
            "protein_g": {"min_g": None, "max_g": None},
            "fat_g": {"min": None, "max": None},
            "carb_g": {"min": None, "max": None},
            "calories": {"min": None, "max": None},
            "bmr": None,
            "tdee": None,
            "note": "先在 profile.json 填写 weight_kg；没有体重时只给趋势规则，不硬算宏量。",
        }
    protein = protein_target(weight)
    fat_min, fat_max = round(weight * 0.6, 1), round(weight * 1.0, 1)
    carbs_min, carbs_max = (
        (round(weight * 3.0, 1), round(weight * 5.0, 1))
        if training_day
        else (round(weight * 2.0, 1), round(weight * 3.5, 1))
    )
    bmr = estimate_bmr(profile)
    activity = float(profile.get("activity_factor") or 1.45)
    tdee = round(bmr * activity, 1) if bmr else None
    goal = str(profile.get("goal", "hypertrophy")).lower()
    calorie_min = calorie_max = None
    if tdee:
        if "cut" in goal or "fat" in goal or "减脂" in goal:
            calorie_min, calorie_max = round(tdee * 0.85), round(tdee * 0.92)
        elif "maintain" in goal or "维持" in goal:
            calorie_min, calorie_max = round(tdee * 0.97), round(tdee * 1.03)
        else:
            calorie_min, calorie_max = round(tdee * 1.03), round(tdee * 1.10)
    return {
        "weight_kg": weight,
        "protein_g": protein,
        "fat_g": {"min": fat_min, "max": fat_max},
        "carb_g": {"min": carbs_min, "max": carbs_max},
        "calories": {"min": calorie_min, "max": calorie_max},
        "bmr": bmr,
        "tdee": tdee,
        "note": "区间是起点，不是处方；按 2–4 周体重趋势、训练表现、饥饿和依从性调整。",
    }


def totals_for(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return food_totals(records)


def gap(totals: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    macros = totals.get("totals", {})
    protein = macros.get("protein", 0)
    target = targets.get("protein_g", {})
    target_min = target.get("min_g")
    target_max = target.get("max_g")
    result = {
        "protein": {
            "actual_g": round(protein, 1),
            "target_min_g": target_min,
            "target_max_g": target_max,
            "gap_to_min_g": round(max(0.0, target_min - protein), 1) if target_min is not None else None,
        },
        "calories": {
            "actual_kcal": macros.get("cal", 0),
            "target_min_kcal": (targets.get("calories") or {}).get("min"),
            "target_max_kcal": (targets.get("calories") or {}).get("max"),
        },
        "data_complete": totals.get("complete", False),
        "unknown_records": totals.get("unknown_records", 0),
    }
    return result


def meal_distribution(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, float]] = {}
    for record in records:
        if not record.get("macro_known"):
            continue
        meal = record.get("meal_type") or "unknown"
        bucket = buckets.setdefault(meal, {"cal": 0.0, "protein": 0.0, "fat": 0.0, "carb": 0.0, "items": 0})
        for key in ("cal", "protein", "fat", "carb"):
            bucket[key] += float(record["macros"].get(key) or 0)
        bucket["items"] += 1
    return {
        meal: {key: round(value, 1) for key, value in bucket.items()}
        for meal, bucket in sorted(buckets.items())
    }


def protein_food_suggestions(remaining_g: float | None, context: str = "general") -> list[dict[str, Any]]:
    """Concrete, low-prep protein options with approximate protein per serving."""
    if remaining_g is None or remaining_g <= 0:
        return []
    options = [
        {"food": "水煮蛋", "serving": "2 个", "protein_g": 12, "note": "食堂/便利店可得"},
        {"food": "无糖希腊酸奶", "serving": "200 g", "protein_g": 20, "note": "有冷藏条件时"},
        {"food": "乳清蛋白粉", "serving": "1 勺 + 250 ml 牛奶", "protein_g": 32, "note": "无需烹饪，适合睡前快补"},
        {"food": "即食鸡胸肉", "serving": "100 g", "protein_g": 23, "note": "便利店/外卖"},
        {"food": "豆浆", "serving": "400 ml", "protein_g": 12, "note": "食堂早餐"},
    ]
    return [item for item in options if item["protein_g"] <= max(remaining_g + 15, 25)]
