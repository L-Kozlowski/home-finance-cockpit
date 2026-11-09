import unittest

from home_finance_cockpit.domain.chart_palettes import PALETTES, chart_colors, set_palette
from home_finance_cockpit.reports.presentation import category_color


class PaletteTests(unittest.TestCase):
    def tearDown(self):
        set_palette("cockpit")

    def test_palette_switch_preserves_manual_colors_and_stable_category_assignment(self):
        seen = set()
        for name in PALETTES:
            set_palette(name)
            color = category_color("Food")
            seen.add(color)
            self.assertIn(color, chart_colors())
            self.assertEqual(category_color("Food"), color)
            self.assertEqual(category_color("Food", {"Food": "#123456"}), "#123456")
        self.assertEqual(len(seen), len(PALETTES))

    def test_invalid_palette_is_rejected(self):
        with self.assertRaises(ValueError):
            set_palette("unknown")
