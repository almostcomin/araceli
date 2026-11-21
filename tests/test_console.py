"""Automated tests for console color helpers."""

import os
import sys
import unittest

from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import console

from console import GREEN, RED, RESET, paint


class PaintTestCase(unittest.TestCase):
    """Tests for the paint helper in both color modes."""

    def test_paint_is_plain_when_disabled(self):
        console._enabled = False

        self.assertEqual(paint("text", RED), "text")
        self.assertEqual(paint("text"), "text")

    def test_paint_wraps_codes_when_enabled(self):
        console._enabled = True

        self.assertEqual(
            paint("text", RED),
            RED + "text" + RESET,
        )

    def test_paint_combines_multiple_codes(self):
        console._enabled = True

        combined = paint("text", RED, GREEN)

        self.assertTrue(combined.startswith(RED + GREEN))
        self.assertTrue(combined.endswith(RESET))
        self.assertIn("text", combined)

    def setUp(self):
        self._original = console._enabled

    def tearDown(self):
        console._enabled = self._original


class InitColorsTestCase(unittest.TestCase):
    """Tests for the color support detection."""

    def test_no_color_environment_disables_colors(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            enabled = console.init_colors()

        self.assertFalse(enabled)
        self.assertFalse(console.colors_enabled())

    def test_non_terminal_output_disables_colors(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(
                    sys.stdout, "isatty", return_value=False
                ):
            enabled = console.init_colors()

        self.assertFalse(enabled)

    def test_init_colors_reports_state(self):
        console._enabled = False

        self.assertFalse(console.colors_enabled())


if __name__ == "__main__":
    unittest.main()
