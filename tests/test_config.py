from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hackex2.config import (
    ConfigurationError,
    InputSettings,
    NavigationSettings,
    load_env_file,
)


class InputSettingsTest(unittest.TestCase):
    def test_loads_validated_input_settings_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory, ".env")
            env_file.write_text(
                "MIN_ACTION_DELAY_MS=125\n"
                "MAX_ACTION_DELAY_MS=425\n"
                "TAP_RANDOM_RADIUS_PX=9\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_env_file(env_file)
                settings = InputSettings.from_environment()

        self.assertEqual(settings.min_action_delay_ms, 125)
        self.assertEqual(settings.max_action_delay_ms, 425)
        self.assertEqual(settings.tap_random_radius_px, 9)

    def test_rejects_inverted_delay_range(self) -> None:
        with patch.dict(
            os.environ,
            {"MIN_ACTION_DELAY_MS": "500", "MAX_ACTION_DELAY_MS": "100"},
            clear=True,
        ):
            with self.assertRaises(ConfigurationError):
                InputSettings.from_environment()

    def test_rejects_zero_navigation_observations(self) -> None:
        with patch.dict(os.environ, {"MAX_STATE_OBSERVATIONS": "0"}, clear=True):
            with self.assertRaises(ConfigurationError):
                NavigationSettings.from_environment()

    def test_rejects_negative_action_retries(self) -> None:
        with patch.dict(os.environ, {"MAX_ACTION_RETRIES": "-1"}, clear=True):
            with self.assertRaises(ConfigurationError):
                NavigationSettings.from_environment()


if __name__ == "__main__":
    unittest.main()
