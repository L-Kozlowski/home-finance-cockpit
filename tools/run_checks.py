"""Run regression tests with temporary preferences and no automatic network refresh."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
from PyQt6.QtWidgets import QApplication


class DeferredDeleteResult(unittest.TextTestResult):
    """Finish Qt widget destruction before each test's temporary database is removed."""

    def stopTest(self, test):
        super().stopTest(test)
        if QApplication.instance():
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("general/language", "pl")
        loader = unittest.defaultTestLoader
        suite = (
            loader.loadTestsFromNames(sys.argv[1:])
            if len(sys.argv) > 1
            else loader.discover("tests")
        )
        with (
            patch(
                "home_finance_cockpit.services.preferences.application_settings",
                return_value=settings,
            ),
            patch(
                "home_finance_cockpit.services.exchange_rates.ExchangeRateService.start",
                autospec=True,
            ),
        ):
            result = unittest.TextTestRunner(verbosity=2, resultclass=DeferredDeleteResult).run(
                suite
            )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
