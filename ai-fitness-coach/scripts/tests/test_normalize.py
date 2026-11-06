import json
import unittest
from pathlib import Path

from coach.normalize import food_totals, normalize_food_day, normalize_food_record, normalize_train_day

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NormalizeTests(unittest.TestCase):
    def test_training_volume_sets_and_body_parts(self):
        trains = normalize_train_day(load("train_day.json"), date_value="2026-11-03", bodyweight_kg=56)
        self.assertEqual(len(trains), 1)
        train = trains[0]
        self.assertEqual(train["date"], "2026-11-03")
        self.assertEqual(train["sets_total"], 5)
        self.assertEqual(train["sets_completed"], 4)
        self.assertAlmostEqual(train["volume_kg"], 1855.0)
        self.assertAlmostEqual(train["body_parts"]["chest"], 1480.0)
        self.assertAlmostEqual(train["body_parts"]["triceps"], 375.0)

    def test_food_macros_are_computed_from_per_100g_ntr(self):
        records = normalize_food_day(load("food_day.json"), date_value="2026-11-03")
        self.assertEqual(len(records), 3)
        totals = food_totals(records)
        self.assertTrue(totals["complete"])
        self.assertAlmostEqual(totals["totals"]["cal"], 622.5)
        self.assertAlmostEqual(totals["totals"]["protein"], 64.3)
        eggs = next(item for item in records if item["name"] == "鸡蛋")
        self.assertTrue(eggs["macro_known"])
        self.assertAlmostEqual(eggs["factor"], 1.0)
        self.assertAlmostEqual(eggs["macros"]["cal"], 143.0)
        self.assertEqual(eggs["macro_basis"], "per_100g")

    def test_record_level_ntr_is_not_multiplied_by_grams(self):
        record = normalize_food_record(
            {
                "date": "2026-11-03",
                "meal_type": "lunch",
                "name": "鸡腿",
                "amount": 100,
                "unit": "g",
                "cals": 200,
                "ntr": {"cal": 200, "protein": 20, "fat": 10, "carb": 5},
            }
        )
        self.assertEqual(record["macro_basis"], "record")
        self.assertAlmostEqual(record["macros"]["cal"], 200.0)
        self.assertAlmostEqual(record["macros"]["protein"], 20.0)

    def test_per_100g_ntr_with_matching_total_is_multiplied(self):
        record = normalize_food_record(
            {
                "date": "2026-11-03",
                "meal_type": "lunch",
                "name": "鸡胸肉",
                "amount": 150,
                "unit": "g",
                "cals": 247.5,
                "ntr": {"cal": 165, "protein": 31, "fat": 3.6, "carb": 0},
            }
        )
        self.assertEqual(record["macro_basis"], "per_100g")
        self.assertAlmostEqual(record["macros"]["cal"], 247.5)
        self.assertAlmostEqual(record["macros"]["protein"], 46.5)

    def test_missing_unit_conversion_is_not_silently_summed(self):
        record = normalize_food_record(
            {
                "date": "2026-11-03",
                "meal_type": "lunch",
                "name": "未知份量",
                "amount": 1,
                "unit": "份",
                "ntr": {"cal": 200, "protein": 10, "fat": 5, "carb": 20},
            }
        )
        self.assertFalse(record["macro_known"])
        totals = food_totals([record])
        self.assertFalse(totals["complete"])
        self.assertEqual(totals["unknown_records"], 1)


if __name__ == "__main__":
    unittest.main()
