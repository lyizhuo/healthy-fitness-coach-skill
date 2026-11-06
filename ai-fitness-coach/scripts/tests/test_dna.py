import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from coach import db
from coach.dna import compute_dna
from coach.normalize import normalize_train_day

FIXTURES = Path(__file__).parent / "fixtures"


class DnaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self.tmp.name) / "coach.sqlite")
        self.raw = json.loads((FIXTURES / "train_day.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _save_week(self, start: date, weeks: int):
        for index in range(weeks):
            day = start + timedelta(days=index * 7)
            trains = normalize_train_day(self.raw, date_value=day.isoformat(), bodyweight_kg=56)
            db.save_train_day(self.conn, day.isoformat(), trains, {})

    def test_single_window_is_insufficient(self):
        start = date(2026, 11, 3)
        self._save_week(start, 1)
        dna = compute_dna(self.conn, start.isoformat(), start.isoformat(), bodyweight_kg=56)
        self.assertEqual(dna["metrics"]["sessions"], 1)
        self.assertEqual(dna["confidence"], "insufficient")
        self.assertEqual(dna["dimensions"]["body_distribution"]["status"], "observed")
        self.assertIn("chest", dna["dimensions"]["body_distribution"]["parts"])
        self.assertEqual(dna["dimensions"]["main_lift_response"]["lifts"][0]["trend"], "insufficient")

    def test_four_weeks_reaches_medium_confidence(self):
        start = date(2026, 9, 1)
        self._save_week(start, 4)
        end = start + timedelta(days=21)
        dna = compute_dna(self.conn, start.isoformat(), end.isoformat(), bodyweight_kg=56)
        self.assertEqual(dna["metrics"]["sessions"], 4)
        self.assertEqual(dna["window"]["weeks"], 4)
        self.assertEqual(dna["confidence"], "medium")
        self.assertAlmostEqual(dna["metrics"]["volume_kg"], 1855.0 * 4, places=1)

    def test_version_diff_after_saving(self):
        start = date(2026, 9, 1)
        self._save_week(start, 2)
        first = compute_dna(self.conn, start.isoformat(), (start + timedelta(days=7)).isoformat(), bodyweight_kg=56)
        db.save_dna(self.conn, first)
        second = compute_dna(self.conn, start.isoformat(), (start + timedelta(days=14)).isoformat(), bodyweight_kg=56)
        self.assertIsNotNone(second["version_diff"])
        self.assertEqual(second["version_diff"]["confidence_before"], first["confidence"])


if __name__ == "__main__":
    unittest.main()
