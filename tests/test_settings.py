"""Automated tests for persisted user settings."""

import sys
import unittest

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import settings as app_settings

from settings import (
    DEFAULT_LANGUAGE,
    load_conversation_language,
    save_conversation_language,
    validate_language_code,
)


class SettingsTestCase(unittest.TestCase):
    """Tests for the persisted settings store."""

    def setUp(self):
        self._temp_dir = Path(__file__).parent / "tmp_settings_test"
        self._temp_dir.mkdir(exist_ok=True)
        self.settings_path = self._temp_dir / "settings.json"
        if self.settings_path.exists():
            self.settings_path.unlink()
        self.addCleanup(self.settings_path.unlink, True)

    def tearDown(self):
        if self._temp_dir.name.startswith("tmp_settings_test"):
            pass

    def test_default_language_when_no_settings_file(self):
        self.assertEqual(
            load_conversation_language(self.settings_path), "es"
        )

    def test_save_and_load_round_trip(self):
        save_conversation_language("en", self.settings_path)

        self.assertEqual(
            load_conversation_language(self.settings_path), "en"
        )

    def test_validate_language_code_accepts_iso_codes(self):
        for code in ("es", "en", "fr", "es-MX"):
            self.assertTrue(validate_language_code(code))

    def test_validate_language_code_rejects_invalid(self):
        for code in ("spanish", "e", "123", "", None, "es_MX_extra"):
            with self.subTest(code=code):
                self.assertFalse(validate_language_code(code))

    def test_default_language_constant(self):
        self.assertEqual(DEFAULT_LANGUAGE, "es")


if __name__ == "__main__":
    unittest.main()
