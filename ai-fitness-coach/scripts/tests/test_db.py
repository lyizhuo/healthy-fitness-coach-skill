import json
import tempfile
import unittest
from pathlib import Path

from coach import db
from coach.normalize import normalize_food_day, normalize_train_day

FIXTURES = Path(__file__).parent / "fixtures"


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self.tmp.name) / "coach.sqlite")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_train_food_and_readiness_roundtrip(self):
        trains = normalize_train_day(
            json.loads((FIXTURES / "train_day.json").read_text(encoding="utf-8")),
            date_value="2026-11-03",
            bodyweight_kg=56,
        )
        db.save_train_day(self.conn, "2026-11-03", trains, {})
        loaded = db.get_train_day(self.conn, "2026-11-03")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(len(loaded[0]["movements"]), 3)
        self.assertEqual(sum(len(item["sets"]) for item in loaded[0]["movements"]), 5)
        load = db.training_load(self.conn, "2026-11-03")
        self.assertAlmostEqual(load["volume_kg"], 1855.0)
        self.assertEqual(load["sets_completed"], 4)

        records = normalize_food_day(
            json.loads((FIXTURES / "food_day.json").read_text(encoding="utf-8")),
            date_value="2026-11-03",
        )
        db.save_food_day(self.conn, "2026-11-03", records, {})
        food = db.get_food_range(self.conn, "2026-11-03", "2026-11-03")
        self.assertEqual(len(food), 3)
        self.assertTrue(all(item["macro_known"] for item in food))

        db.save_readiness(
            self.conn,
            "2026-11-04",
            {"tier": "green", "score": 82, "confidence": 0.9, "components": {}, "inputs": {}},
        )
        self.assertEqual(db.get_readiness(self.conn, "2026-11-04")["tier"], "green")

        db.save_weight(self.conn, "2026-11-04", 56.0)
        self.assertEqual(db.get_weights(self.conn, "2026-11-01", "2026-11-30")[0]["weight_kg"], 56.0)

    def test_multiple_trains_without_localid_do_not_collide(self):
        from coach.normalize import normalize_train

        raw = {"datestr": "2026-11-04", "title": "A", "movements": [{"name": "卧推", "sets": [{"weight": "50", "reps": "10"}]}]}
        trains = [normalize_train(raw), normalize_train({**raw, "title": "B"})]
        self.assertEqual(db.save_train_day(self.conn, "2026-11-04", trains, {}), 2)
        self.assertEqual(len(db.get_train_day(self.conn, "2026-11-04")), 2)

    def test_decision_appends_markdown_log(self):
        path = Path(self.tmp.name) / "DECISIONS.md"
        db.add_decision(
            self.conn,
            date_value="2026-11-04",
            kind="evening_review",
            summary="蛋白缺口 25 g",
            evidence={"protein_g": 64.3},
            action="睡前补酸奶",
            verification="明晚复盘蛋白",
            decisions_path=path,
        )
        text = path.read_text(encoding="utf-8")
        self.assertIn("2026-11-04", text)
        self.assertIn("evening_review", text)
        self.assertIn("蛋白缺口 25 g", text)
        self.assertIn("睡前补酸奶", text)
        self.assertEqual(len(db.get_decisions(self.conn, limit=10)), 1)

    def test_plan_and_food_day(self):
        db.save_plan(self.conn, "platform:1", [{"date": "2026-11-04", "title": "胸", "movements": [{"name": "卧推"}]}])
        plan = db.get_plan_day(self.conn, "2026-11-04")
        self.assertEqual(plan["day"]["title"], "胸")
        self.assertEqual(db.get_food_day(self.conn, "2026-11-04"), [])


if __name__ == "__main__":
    unittest.main()
