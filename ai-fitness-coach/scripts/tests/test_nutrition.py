import unittest

from coach.nutrition import gap, protein_target, target_ranges


class NutritionTests(unittest.TestCase):
    def test_protein_target(self):
        self.assertEqual(protein_target(56), {"min_g": 89.6, "max_g": 112.0})

    def test_unfilled_profile_returns_unknown_targets(self):
        targets = target_ranges({"weight_kg": "TODO", "height_cm": "TODO", "age": "TODO"})
        self.assertIsNone(targets["protein_g"]["min_g"])
        self.assertIn("weight_kg", targets["note"])

    def test_bmr_uses_mifflin_st_jeor(self):
        targets = target_ranges(
            {"weight_kg": 56, "height_cm": 170, "age": 25, "sex": "male", "goal": "hypertrophy"}
        )
        self.assertIsNotNone(targets["bmr"])
        self.assertGreater(targets["bmr"], 1000)
        self.assertIsNotNone(targets["calories"]["min"])

    def test_gap_with_unknown_target_is_none(self):
        result = gap({"totals": {"protein": 60, "cal": 2000}, "complete": True}, {"protein_g": {"min_g": None, "max_g": None}})
        self.assertIsNone(result["protein"]["gap_to_min_g"])


if __name__ == "__main__":
    unittest.main()
