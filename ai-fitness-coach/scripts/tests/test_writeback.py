import json
import tempfile
import unittest
from pathlib import Path

from coach import db
from coach.writeback import (
    confirm_custom_food,
    confirm_food,
    confirm_train,
    preview_custom_food,
    preview_food,
    preview_train,
    validate_food_records,
    validate_train_records,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def upsert_trains(self, records, *, client_request_id, dry_run=False, include_full_data=False):
        self.calls.append(("train", client_request_id, dry_run, records))
        return {"accepted": True, "dry_run": dry_run}

    def upsert_foods(self, foods, *, client_request_id, dry_run=False):
        self.calls.append(("food", client_request_id, dry_run, foods))
        return {"accepted": True, "dry_run": dry_run}

    def create_custom_food(self, food, *, client_request_id, dry_run=False):
        self.calls.append(("custom_food", client_request_id, dry_run, food))
        return {"accepted": True, "dry_run": dry_run, "food": food}


TRAIN = {
    "datestr": "2026-11-04",
    "localid": 123,
    "start": 1762180000000,
    "end": 1762183600000,
    "movements": [
        {"name": "杠铃卧推", "sets": [{"weight": "60", "unit": "kg", "reps": "10", "done": True}]}
    ],
}

FOOD = {
    "date": "2026-11-04",
    "meal_type": "lunch",
    "name": "鸡胸肉",
    "amount": 150,
    "unit": "g",
    "uniquekey": "u1",
    "ntr": {"cal": 165, "protein": 31, "fat": 3.6, "carb": 0},
}


class WritebackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self.tmp.name) / "coach.sqlite")
        self.client = FakeClient()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_validation(self):
        self.assertEqual(validate_train_records([TRAIN]), [])
        self.assertTrue(validate_train_records([]))
        self.assertTrue(validate_train_records([{"datestr": "bad"}]))
        self.assertEqual(validate_food_records([FOOD]), [])
        self.assertTrue(validate_food_records([{"date": "2026-11-04"}]))

    def test_train_preview_and_confirm(self):
        preview = preview_train(self.conn, self.client, [TRAIN])
        self.assertEqual(preview["status"], "preview")
        self.assertTrue(preview["server_dry_run"])
        preview_id = preview["preview_id"]
        self.assertEqual(db.get_operation(self.conn, preview_id)["status"], "preview")
        confirmed = confirm_train(self.conn, self.client, preview_id)
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(db.get_operation(self.conn, preview_id)["status"], "confirmed")
        self.assertEqual(self.client.calls[0][2], True)
        self.assertEqual(self.client.calls[1][2], False)
        again = confirm_train(self.conn, self.client, preview_id)
        self.assertEqual(again["status"], "not_preview")

    def test_food_preview_and_confirm(self):
        preview = preview_food(self.conn, self.client, [FOOD])
        self.assertEqual(preview["status"], "preview")
        confirmed = confirm_food(self.conn, self.client, preview["preview_id"])
        self.assertEqual(confirmed["status"], "confirmed")

    def test_custom_food_preview_and_confirm(self):
        food = {
            "name": "自制鸡胸饭",
            "ntr": {"cal": 150, "protein": 20, "fat": 3, "carb": 12},
            "units": [{"unit": "份", "count": "1", "gram": 300}],
        }
        preview = preview_custom_food(self.conn, self.client, food)
        self.assertEqual(preview["status"], "preview")
        confirmed = confirm_custom_food(self.conn, self.client, preview["preview_id"])
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(self.client.calls[0][0], "custom_food")

    def test_invalid_payload_does_not_create_operation(self):
        result = preview_train(self.conn, self.client, [])
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(self.client.calls, [])

    def test_expired_preview_is_not_confirmed(self):
        preview = preview_train(self.conn, self.client, [TRAIN])
        preview_id = preview["preview_id"]
        self.conn.execute("UPDATE operations SET created_at = '2000-01-01T00:00:00+00:00' WHERE client_request_id = ?", (preview_id,))
        self.conn.commit()
        result = confirm_train(self.conn, self.client, preview_id)
        self.assertEqual(result["status"], "expired")


if __name__ == "__main__":
    unittest.main()
