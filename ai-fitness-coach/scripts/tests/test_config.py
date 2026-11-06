import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coach.config import load_config


class ConfigTests(unittest.TestCase):
    def test_default_home_uses_hermes_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"HERMES_HOME": tmp}, clear=False):
                os.environ.pop("AI_COACH_HOME", None)
                config = load_config()
                self.assertEqual(config.home, Path(tmp) / "data" / "ai-coach")

    def test_ai_coach_home_overrides_hermes_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "explicit"
            with patch.dict(os.environ, {"HERMES_HOME": tmp, "AI_COACH_HOME": str(explicit)}, clear=False):
                config = load_config()
                self.assertEqual(config.home, explicit)


if __name__ == "__main__":
    unittest.main()
