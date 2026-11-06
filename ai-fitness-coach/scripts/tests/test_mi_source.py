import os
import tempfile
import unittest
from unittest.mock import patch

from coach.config import load_config
from zoneinfo import ZoneInfo

from coach.mi_source import MiHealthSource, _date_key


class FakeMiClient:
    def __init__(self):
        self.day_payload = {
            "date": "2026-11-04",
            "sleep": {"time_asleep_minutes": 450, "end_at": "2026-11-04T07:10:00+08:00", "avg_hrv_ms": 65},
            "hrv": {"avg_hrv_ms": 65},
            "rhr": 58,
            "stress": {"avg": 28},
            "spo2": {"min": 96},
            "activity": {"steps": 8000},
            "abnormal": [],
            "meta": {"stale": False, "data_as_of": "2026-11-04T07:10:00+08:00"},
        }
        self.sleep_payload = {
            "data": [
                {"end_at": "2026-11-03T07:00:00+08:00", "time_asleep_minutes": 420, "avg_hrv_ms": 50},
                {"end_at": "2026-11-04T07:10:00+08:00", "time_asleep_minutes": 450, "avg_hrv_ms": 65},
            ],
            "meta": {"stale": False, "last_synced_at": "2026-11-04T07:20:00+08:00"},
        }
        self.hr_payload = {
            "data": [
                {"timestamp": "2026-11-03T03:00:00+08:00", "bpm": 60, "sample_type": "resting"},
                {"timestamp": "2026-11-04T03:00:00+08:00", "bpm": 58, "sample_type": "resting"},
            ],
            "meta": {"stale": False},
        }
        self.summary_payload = {
            "data": [
                {"date": "2026-11-03", "steps": 7000},
                {"date": "2026-11-04", "steps": 8000},
            ],
            "meta": {"stale": False},
        }

    def collect_day(self, date_value):
        return dict(self.day_payload, date=date_value)

    def sleep_range(self, start_date, end_date):
        return self.sleep_payload

    def heart_rate_range(self, start_date, end_date):
        return self.hr_payload

    def summary_range(self, start_date, end_date):
        return self.summary_payload


class MiSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AI_COACH_HOME": self.tmp.name})
        self.env.start()
        self.config = load_config()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_date_key_accepts_epoch_and_compact_dates(self):
        tz = ZoneInfo("Asia/Shanghai")
        self.assertEqual(_date_key("20261104", tz), "2026-11-04")
        self.assertEqual(_date_key("2026-11-04T07:10:00+08:00", tz), "2026-11-04")
        self.assertEqual(_date_key(1762180000000, tz), "2025-11-03")

    def test_day_is_live_with_meta(self):
        source = MiHealthSource(self.config, client=FakeMiClient())
        day = source.day("2026-11-04")
        self.assertEqual(day["date"], "2026-11-04")
        self.assertEqual(day["rhr"], 58)
        self.assertFalse(day["meta"]["stale"])

    def test_baseline_rows_group_by_wake_date(self):
        source = MiHealthSource(self.config, client=FakeMiClient())
        rows = source.baseline_rows("2026-11-04")
        by_date = {row["date"]: row for row in rows}
        self.assertEqual(sorted(by_date), ["2026-11-03", "2026-11-04"])
        self.assertEqual(by_date["2026-11-03"]["rhr"], 60.0)
        self.assertEqual(by_date["2026-11-04"]["sleep_json"]["time_asleep_minutes"], 450)
        self.assertEqual(by_date["2026-11-04"]["activity_json"]["steps"], 8000)
        self.assertEqual(by_date["2026-11-04"]["hrv_json"]["avg_hrv_ms"], 65)


if __name__ == "__main__":
    unittest.main()
