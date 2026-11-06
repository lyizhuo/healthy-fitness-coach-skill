import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coach import db
from coach.config import load_config
from coach.mi_source import empty_day
from coach.normalize import normalize_food_day, normalize_train_day
from coach.report import (
    build_evening_facts,
    build_morning_facts,
    build_weekly_facts,
    render_evening,
    render_morning,
    render_weekly,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeMiSource:
    def __init__(self, day, rows=None):
        self.day_payload = day
        self.rows = rows or []

    def day(self, date_value):
        return self.day_payload

    def baseline_rows(self, end_date, days=28):
        return self.rows


def mi_payload():
    payload = json.loads((FIXTURES / "mi_day.json").read_text(encoding="utf-8"))
    payload["meta"] = {
        "data_as_of": "2026-11-04T07:10:00+08:00",
        "last_synced_at": "2026-11-04T07:20:00+08:00",
        "stale": False,
    }
    return payload


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AI_COACH_HOME": self.tmp.name})
        self.env.start()
        self.config = load_config()
        self.conn = db.init_db(self.config.db_path)
        self.config.profile_path.parent.mkdir(parents=True, exist_ok=True)
        (self.config.home / "profile.json").write_text('{"weight_kg": 56}', encoding="utf-8")

        trains = normalize_train_day(
            json.loads((FIXTURES / "train_day.json").read_text(encoding="utf-8")),
            date_value="2026-11-03",
            bodyweight_kg=56,
        )
        db.save_train_day(self.conn, "2026-11-03", trains, {})

        records = normalize_food_day(
            json.loads((FIXTURES / "food_day.json").read_text(encoding="utf-8")),
            date_value="2026-11-03",
        )
        db.save_food_day(self.conn, "2026-11-03", records, {})

        self.mi_day = mi_payload()

    def tearDown(self):
        self.conn.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_morning_facts_and_render(self):
        facts = build_morning_facts(self.conn, self.config, "2026-11-04", mi_source=FakeMiSource(self.mi_day))
        self.assertEqual(facts["date"], "2026-11-04")
        self.assertTrue(facts["data_quality"]["mi_present"])
        self.assertIn(facts["readiness"]["tier"], ("green", "yellow"))
        self.assertEqual(facts["energy_window"]["window"], "09:10–11:10")
        text = render_morning(facts)
        self.assertIn("今天", text)
        self.assertIn("高能窗口", text)

    def test_abnormal_heartbeat_is_a_safety_flag(self):
        self.mi_day["abnormal"] = [{"event_id": "a1", "start_at": "2026-11-04T03:00:00+08:00"}]
        facts = build_morning_facts(self.conn, self.config, "2026-11-04", mi_source=FakeMiSource(self.mi_day))
        self.assertTrue(facts["readiness"]["safety_flag"])
        self.assertIn("abnormal_heart_beat", facts["readiness"]["reasons"])
        text = render_morning(facts)
        self.assertIn("异常心搏", text)

    def test_evening_gap_uses_local_per_100g_totals(self):
        facts = build_evening_facts(self.conn, self.config, "2026-11-03", mi_source=FakeMiSource(self.mi_day))
        self.assertEqual(len(facts["trains"]), 1)
        self.assertAlmostEqual(facts["food"]["totals"]["protein"], 64.3)
        self.assertAlmostEqual(facts["gap"]["protein"]["gap_to_min_g"], 25.3)
        text = render_evening(facts)
        self.assertIn("蛋白", text)

    def test_weekly_uses_dna_and_volume(self):
        facts = build_weekly_facts(self.conn, self.config, "2026-11-09")
        self.assertEqual(facts["training"]["sessions"], 1)
        self.assertAlmostEqual(facts["training"]["volume_kg"], 1855.0)
        self.assertEqual(facts["dna"]["metrics"]["sessions"], 1)
        text = render_weekly(facts)
        self.assertIn("周报", text)

    def test_empty_mi_does_not_print_fake_score(self):
        facts = build_morning_facts(self.conn, self.config, "2026-11-06", mi_source=FakeMiSource(empty_day("2026-11-06")))
        text = render_morning(facts)
        self.assertIn("数据不足", text)
        self.assertNotIn("0.0/100", text)

    def test_stale_meta_is_surfaced(self):
        self.mi_day["meta"]["stale"] = True
        facts = build_morning_facts(self.conn, self.config, "2026-11-04", mi_source=FakeMiSource(self.mi_day))
        self.assertTrue(facts["data_quality"]["stale"])
        self.assertIn("可能不新", render_morning(facts))


if __name__ == "__main__":
    unittest.main()
