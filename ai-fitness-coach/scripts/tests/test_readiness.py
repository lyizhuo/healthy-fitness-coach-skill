import unittest

from coach.readiness import assess_readiness, compute_baseline, readiness_action


BASELINE = {"hrv": 60, "rhr": 58, "sleep_minutes": 450, "steps": 8000, "training_load": 2500, "days": 28}
SLEEP = {"duration_minutes": 480, "time_asleep_minutes": 450, "time_awake_minutes": 30}
HRV = {"avg_hrv_ms": 65}
STRESS = {"avg": 25}
SPO2 = {"min": 97}
ACTIVITY = {"steps": 8000}


class ReadinessTests(unittest.TestCase):
    def test_good_recovery_is_green(self):
        result = assess_readiness(
            sleep=SLEEP,
            hrv=HRV,
            rhr=58,
            stress=STRESS,
            spo2=SPO2,
            activity=ACTIVITY,
            yesterday_load=2500,
            baseline=BASELINE,
        )
        self.assertEqual(result["tier"], "green")
        self.assertGreaterEqual(result["score"], 70)
        self.assertGreater(result["confidence"], 0.9)
        self.assertIn("按计划", readiness_action(result))

    def test_poor_sleep_and_high_rhr_is_not_green(self):
        result = assess_readiness(
            sleep={"duration_minutes": 300, "time_asleep_minutes": 250, "time_awake_minutes": 50},
            hrv={"avg_hrv_ms": 40},
            rhr=70,
            stress={"avg": 75},
            spo2={"min": 94},
            activity={"steps": 1200},
            yesterday_load=6500,
            baseline=BASELINE,
        )
        self.assertIn(result["tier"], ("yellow", "red"))
        self.assertLess(result["score"], 70)

    def test_missing_data_lowers_confidence(self):
        result = assess_readiness(
            sleep=None,
            hrv=None,
            rhr=None,
            stress=None,
            spo2=None,
            activity=None,
            yesterday_load=None,
            baseline={},
        )
        self.assertEqual(result["confidence"], 0.0)
        self.assertNotEqual(result["tier"], "green")

    def test_abnormal_heartbeat_is_a_safety_gate(self):
        result = assess_readiness(
            sleep=SLEEP,
            hrv=HRV,
            rhr=58,
            stress=STRESS,
            spo2=SPO2,
            activity=ACTIVITY,
            yesterday_load=2500,
            baseline=BASELINE,
            abnormal_events=[{"event_id": "a1"}],
        )
        self.assertTrue(result["safety_flag"])
        self.assertIn("abnormal_heart_beat", result["reasons"])
        self.assertNotEqual(result["tier"], "green")

    def test_red_flags_force_red(self):
        result = assess_readiness(
            sleep=SLEEP,
            hrv=HRV,
            rhr=58,
            stress=STRESS,
            spo2=SPO2,
            activity=ACTIVITY,
            yesterday_load=2500,
            baseline=BASELINE,
            red_flags=["chest_pain"],
        )
        self.assertEqual(result["tier"], "red")
        self.assertIn("red_flags", result["reasons"])

    def test_baseline_uses_medians(self):
        rows = [
            {"hrv_json": '{"avg_hrv_ms": 50}', "rhr": 60, "sleep_json": '{"time_asleep_minutes": 420}', "activity_json": '{"steps": 7000}'},
            {"hrv_json": '{"avg_hrv_ms": 70}', "rhr": 58, "sleep_json": '{"time_asleep_minutes": 480}', "activity_json": '{"steps": 9000}'},
        ]
        baseline = compute_baseline(rows, {"2026-11-01": 2000, "2026-11-02": 3000})
        self.assertEqual(baseline["hrv"], 60)
        self.assertEqual(baseline["rhr"], 59)
        self.assertEqual(baseline["sleep_minutes"], 450)
        self.assertEqual(baseline["steps"], 8000)
        self.assertEqual(baseline["training_load"], 2500)


if __name__ == "__main__":
    unittest.main()
