"""Capture real English application screens from a private, disposable demo copy."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QDate, QSettings, QSignalBlocker, Qt
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.theme import configure_application

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/screenshots/showcase"


def capture():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    configure_application(app, content_density=1)
    with tempfile.TemporaryDirectory() as temporary:
        copied = Path(temporary) / "showcase.db"
        shutil.copy2(ROOT / "example/database/home_finance_demo.db", copied)
        db = Database.open_existing(copied)
        settings = QSettings(str(Path(temporary) / "showcase.ini"), QSettings.Format.IniFormat)
        settings.setValue("general/language", "en")
        settings.setValue("general/font_size", 10)
        window = FinanceApp(db, settings=settings)
        try:
            window.resize(1600, 1000)
            window.show()

            def save(name):
                window.workspace.nav_buttons[window.tabs.currentIndex()].setFocus(
                    Qt.FocusReason.OtherFocusReason
                )
                for _ in range(6):
                    app.processEvents()
                assert window.grab().save(str(OUTPUT / f"{name}.png"))
                print(name)

            def page(index):
                window.tabs.setCurrentIndex(index)
                app.processEvents()

            page(0)
            save("01-overview")
            page(1)
            save("02-transactions")
            page(2)
            save("03-wallets")
            page(3)
            save("04-imports")
            page(4)
            analyses = window.analyses
            analyses.tabs.setCurrentIndex(0)
            analyses.refresh(force=True)
            save("05-analysis-overview")
            analyses.tabs.setCurrentIndex(1)
            with (
                QSignalBlocker(analyses.preset),
                QSignalBlocker(analyses.start),
                QSignalBlocker(analyses.end),
            ):
                analyses.preset.setCurrentIndex(analyses.preset.findData("custom"))
                analyses.start.setDate(QDate(2026, 7, 1))
                analyses.end.setDate(QDate(2026, 7, 31))
            analyses.refresh(force=True)
            save("06-category-overview")
            analyses.category_views.tabs.setCurrentIndex(1)
            save("07-category-details")
            analyses.tabs.setCurrentIndex(2)
            save("08-spending-calendar")
            with QSignalBlocker(analyses.preset):
                analyses.preset.setCurrentIndex(analyses.preset.findData("all"))
            analyses.refresh(force=True)
            analyses.tabs.setCurrentIndex(3)
            save("09-period-comparison")
            analyses.tabs.setCurrentIndex(4)
            save("10-recipients")
            analyses.tabs.setCurrentIndex(5)
            rates = analyses.currency_rates
            rates.start.setDate(QDate(2026, 1, 1))
            rates.end.setDate(QDate(2026, 10, 31))
            rates.refresh()
            for i in range(rates.currencies.count()):
                rates.currencies.item(i).setCheckState(Qt.CheckState.Checked)
            save("11-exchange-history")
            page(5)
            tree = window.category_page.tree
            food = db.find_category("Food")["id"]
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                if item.data(0, Qt.ItemDataRole.UserRole) == food:
                    tree.setCurrentItem(item)
                    item.setExpanded(True)
                    break
            starbucks = next(rule for rule in db.rules() if rule["pattern"] == "STARBUCKS")
            window.category_page.choose_rule(starbucks["id"])
            save("12-categories-and-rules")
            page(6)
            panel = window.report_generator.panel
            panel.output.setText("C:/Reports/HomeFinanceCockpit")
            panel.refresh_summary()
            save("13-report-generator")
            page(7)
            save("14-savings-goals")
        finally:
            window.close()
            app.processEvents()
            window.deleteLater()
            app.processEvents()
            db.close()


if __name__ == "__main__":
    capture()
