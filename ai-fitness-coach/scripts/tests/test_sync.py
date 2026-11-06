import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from coach import db
from coach.config import load_config
from coach.sync import backfill, preflight, status, sync_day

FIXTURES = Path(__file__).parent / "fixtures"


class FakeXunji:
    def fetch_train_day(self, datestr, *, full=True, delay=True):
        return json.loads((FIXTURES / "train_day.json").read_text(encoding="utf-8"))

    def fetch_food_day(self, datestr, *, include_detail=True, delay=True):
        return {"data": json.loads((FIXTURES / "food_day.json").read_text(encoding="utf-8"))}


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AI_COACH_HOME": self.tmp.name})
        self.env.start()
        self.config = load_config()
        self.conn = db.init_db(self.config.db_path)

    def tearDown(self):
        self.conn.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_sync_day_normalizes_and_saves(self):
        result = sync_day(self.conn, self.config, FakeXunji(), "2026-11-03", full=True, delay=False)
        self.assertEqual(result["trains"], 1)
        self.assertEqual(result["food_records"], 3)
        self.assertEqual(result["food_known"], 3)
        self.assertEqual(len(db.get_train_day(self.conn, "2026-11-03")), 1)
        self.assertEqual(len(db.get_food_range(self.conn, "2026-11-03", "2026-11-03")), 3)

    def test_sync_day_with_unfilled_profile_does_not_crash(self):
        self.config.profile_path.write_text("- weight_kg: TODO\n", encoding="utf-8")
        result = sync_day(self.conn, self.config, FakeXunji(), "2026-11-03", full=True, delay=False)
        self.assertEqual(result["trains"], 1)

    def test_preflight_reports_missing_env_and_profile(self):
        result = preflight(self.conn, self.config)
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("weight_kg", result["missing_profile"])
        self.assertIn("XUNJI_TRAIN_API_KEY", result["missing_env"])
        self.assertTrue(result["questions"])

    def test_preflight_ready_when_profile_and_env_present(self):
        (self.config.home / "profile.json").write_text(
            json.dumps(
                {
                    "weight_kg": 56,
                    "height_cm": 170,
                    "age": 25,
                    "sex": "male",
                    "goal": "hypertrophy",
                    "training_days_per_week": 5,
                    "training_time": "18:30",
                    "training_venue": "gym",
                    "available_equipment": ["barbell"],
                    "injury_or_medical_constraints": "none",
                    "diet_context": "cafeteria",
                    "timezone": "Asia/Shanghai",
                }
            ),
            encoding="utf-8",
        )
        config = replace(
            self.config,
            xunji_train_key="x",
            xunji_food_key="x",
            xunji_food_search_key="x",
            mi_health_api_key="x",
        )
        result = preflight(self.conn, config)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["missing_profile"], [])
        self.assertEqual(result["missing_env"], [])

    def test_preflight_treats_zero_placeholders_as_missing(self):
        (self.config.home / "profile.json").write_text(
            json.dumps(
                {
                    "weight_kg": 56,
                    "height_cm": 0,
                    "age": 0,
                    "sex": "male",
                    "goal": "hypertrophy",
                    "training_days_per_week": 5,
                    "training_time": "18:30",
                    "training_venue": "gym",
                    "available_equipment": ["barbell"],
                    "injury_or_medical_constraints": "none",
                    "diet_context": "canteen",
                    "timezone": "Asia/Shanghai",
                }
            ),
            encoding="utf-8",
        )
        result = preflight(self.conn, self.config)
        self.assertIn("height_cm", result["missing_profile"])
        self.assertIn("age", result["missing_profile"])

    def test_preflight_reports_defaulted_fields_as_missing(self):
        (self.config.home / "profile.json").write_text('{"weight_kg": 56}', encoding="utf-8")
        result = preflight(self.conn, self.config)
        self.assertIn("goal", result["missing_profile"])
        self.assertIn("timezone", result["missing_profile"])
        self.assertIn("training_venue", result["missing_profile"])

    def test_status_requires_profile_json_not_markdown_template(self):
        self.config.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.profile_path.write_text("- weight_kg: TODO\n", encoding="utf-8")
        self.assertFalse(status(self.conn, self.config)["profile"]["exists"])
        (self.config.home / "profile.json").write_text('{"weight_kg": 56}', encoding="utf-8")
        self.assertTrue(status(self.conn, self.config)["profile"]["exists"])

    def test_backfill_reports_missing_key_without_crashing(self):
        result = backfill(self.conn, self.config, days=1, end=__import__("datetime").date(2026, 11, 4), delay=False)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "missing_key")

    def test_backfill_uses_client_and_stops_on_auth_error(self):
        class AuthErrorClient(FakeXunji):
            def fetch_train_day(self, datestr, *, full=True, delay=True):
                from coach.http import ApiError

                raise ApiError("apikey invalid", status=401, code="auth_error")

        with patch("coach.sync.XunjiClient", return_value=AuthErrorClient()):
            result = backfill(self.conn, self.config, days=2, end=__import__("datetime").date(2026, 11, 4), delay=False)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "auth_error")


if __name__ == "__main__":
    unittest.main()
