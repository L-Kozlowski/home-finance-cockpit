"""Run the real desktop layout at native 100%, 125% and 150% monitor scaling."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from home_finance_cockpit.ui.scaling import screen_density


class ScalingTests(unittest.TestCase):
    def test_density_uses_logical_screen_space_with_a_readable_lower_limit(self):
        self.assertEqual(screen_density(1920, 1080), 1.0)
        self.assertEqual(screen_density(1536, 800), 0.8)
        self.assertEqual(screen_density(1280, 650), 0.75)
        self.assertEqual(screen_density(640, 480), 0.75)

    def test_full_hd_primary_panels_fit_at_multiple_native_dpi_settings(self):
        script = """
import json, sys, tempfile
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.theme import configure_application
from home_finance_cockpit.ui.scaling import screen_density
from home_finance_cockpit.ui.main_window import FinanceApp
factor = float(sys.argv[1])
width, height = round(1920 / factor), round(1000 / factor)
app = QApplication([])
configure_application(app, content_density=screen_density(width, height))
db = Database(':memory:')
db.save_wallet('Main', '1000', 'PLN', '2026-01-01')
temporary_settings = tempfile.TemporaryDirectory()
settings = QSettings(str(Path(temporary_settings.name) / 'settings.ini'), QSettings.Format.IniFormat)
with patch('home_finance_cockpit.services.exchange_rates.ExchangeRateService.start', autospec=True):
    window = FinanceApp(db, settings=settings)
window.resize(width, height)
window.show()
for _ in range(8):
    app.processEvents()
view = window.dashboard
viewport = view.body_scroll.viewport()
initial = [f.y() + f.height() for f in view.body_widgets[:4]]
initial_viewport = viewport.height()
size = [window.width(), window.height()]
scroll = view.body_scroll.horizontalScrollBar().maximum()
top_scroll = view.splitter.widget(0).verticalScrollBar().maximum()
view.splitter.setSizes([0, 1000])
for _ in range(8):
    app.processEvents()
print(json.dumps(dict(dpi=window.devicePixelRatioF(), size=size, expected=[width,height],
    bottom=initial, initial_viewport=initial_viewport, horizontal=scroll,
    top_scroll=top_scroll, collapsed=view.splitter.sizes()[0],
    expanded_fits=all(f.y()+f.height() <= viewport.height()+1 for f in view.body_widgets[:4]))))
window.close()
temporary_settings.cleanup()
"""
        for factor in (1.0, 1.25, 1.5):
            with self.subTest(dpi=factor):
                environment = dict(
                    os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=str(factor)
                )
                result = subprocess.run(
                    [sys.executable, "-c", script, str(factor)],
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=40,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertAlmostEqual(data["dpi"], factor)
                self.assertEqual(data["size"], data["expected"])
                self.assertEqual(data["horizontal"], 0)
                self.assertEqual(data["top_scroll"], 0)
                self.assertLessEqual(max(data["bottom"]), data["initial_viewport"] + 1)
                self.assertEqual(data["collapsed"], 0)
                self.assertTrue(data["expanded_fits"])


if __name__ == "__main__":
    unittest.main()
