"""Balance history and working navigation in the redesigned desktop workspace."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.analysis import summarize
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import configure_application


class BalanceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.category = self.db.default_category_id()

    def tx(self, amount, day, wallet=None):
        return self.db.save_transaction(
            wallet or self.wallet, amount, self.category, "Example", day
        )

    def test_history_carries_prior_balance_and_openings_into_selected_period(self):
        self.tx("-100", "2026-09-01")
        self.tx("-30", "2026-10-02")
        self.tx("20", "2026-11-01")
        other = self.db.save_wallet("Second", "200", "PLN", "2026-10-15")
        self.tx("50", "2026-10-20", other)
        self.db.save_currency("EUR", "Euro")
        self.db.save_rate_config("EUR", "manual", "4.00")
        self.db.save_wallet("Euro", "500", "EUR", "2026-01-01")
        data = summarize(self.db, start="2026-10-01", end="2026-10-31", currency="PLN")
        self.assertEqual(
            data["balance_trend"],
            [
                ("2026-10-01", 290000),
                ("2026-10-02", 287000),
                ("2026-10-15", 307000),
                ("2026-10-20", 312000),
                ("2026-10-31", 312000),
            ],
        )
        self.assertEqual(data["balance_trend"][-1][1], data["balance"])
        self.assertEqual((data["income"], data["expense"]), (5000, 3000))

    def test_same_day_events_are_combined_and_report_exclusion_does_not_affect_balance(self):
        self.tx("-1200", "2026-01-01")
        excluded = self.tx("25", "2026-01-01")
        self.db.set_report_inclusion(excluded, False)
        data = summarize(self.db, wallet_id=self.wallet, start="2026-01-01", end="2026-01-01")
        self.assertEqual(data["balance_trend"], [("2026-01-01", -17500)])
        self.assertEqual(data["balance"], -17500)

    def test_empty_period_before_opening_and_period_after_last_transaction(self):
        before = summarize(self.db, start="2025-01-01", end="2025-12-31")
        self.assertEqual(before["balance_trend"], [("2025-01-01", 0), ("2025-12-31", 0)])
        self.tx("-10", "2026-02-01")
        after = summarize(self.db, start="2026-10-01", end="2026-10-31")
        self.assertEqual(after["balance_trend"], [("2026-10-01", 99000), ("2026-10-31", 99000)])


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.db.save_currency("EUR", "Euro")
        self.db.save_rate_config("EUR", "manual", "4.00")
        self.db.save_wallet("Euro", "500", "EUR", "2026-01-01")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = QSettings(str(Path(temporary.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.window = FinanceApp(self.db, settings=settings)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.dashboard.close_chart_windows()
        self.window.analyses.close_chart_windows()
        self.window.deleteLater()
        self.app.processEvents()

    def test_navigation_switches_pages_and_tracks_programmatic_changes(self):
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.tabs.tabBar().isHidden())
        for index, button in enumerate(self.window.workspace.nav_buttons):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.assertEqual(self.window.tabs.currentIndex(), index)
            self.assertTrue(button.isChecked())
            self.assertEqual(sum(b.isChecked() for b in self.window.workspace.nav_buttons), 1)
        self.window.focus_transaction_search()
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertTrue(self.window.workspace.nav_buttons[1].isChecked())
        self.assertTrue(self.window.transaction_search.hasFocus())

    def test_wallet_structure_uses_selected_currency_and_busy_disables_shortcuts(self):
        dashboard = self.window.dashboard
        self.assertEqual(dashboard.currency.currentData(), "PLN")
        self.assertEqual(dashboard.chart_data["balance"], 300000)
        dashboard.currency.setCurrentIndex(dashboard.currency.findData("EUR"))
        self.assertEqual(dashboard.chart_data["balance"], 50000)
        self.assertEqual([w["name"] for w in dashboard.chart_data["wallets"]], ["Euro"])
        self.assertIn("Struktura portfeli", dashboard.composition_title.text())
        self.window.set_report_busy(True)
        self.assertFalse(self.window.import_shortcut.isEnabled())
        self.assertFalse(self.window.workspace.sidebar.isEnabled())
        self.assertTrue(self.window.centralWidget().isEnabled())
        self.window.set_report_busy(False)
        self.assertTrue(self.window.import_shortcut.isEnabled())

    def test_small_window_stacks_charts_and_wide_window_restores_columns(self):
        self.window.resize(px(1000), px(700))
        self.window.show()
        self.app.processEvents()
        dashboard = self.window.dashboard
        self.assertEqual(len(dashboard.body_grid.rows), 4)
        self.assertTrue(all(row.count() == 1 for row in dashboard.body_grid.rows))
        self.assertEqual(dashboard.splitter.widget(1).horizontalScrollBar().maximum(), 0)
        self.window.resize(1600, 1000)
        self.app.processEvents()
        self.assertEqual(len(dashboard.body_grid.rows), 2)
        row = dashboard.body_grid.rows[0]
        self.assertIs(row.widget(1), dashboard.body_widgets[1])
        row.setSizes([600, 300])
        saved = row.sizes()
        dashboard.refresh()
        self.app.processEvents()
        self.assertEqual(row.sizes(), saved)

    def test_wallet_checkboxes_filter_charts_without_hiding_wallet_balances(self):
        wallets = {w["name"]: w for w in self.db.wallets()}
        for name, amount in (("Main", "-10"), ("Euro", "-5")):
            self.db.save_transaction(
                wallets[name]["id"], amount, self.db.default_category_id(), "Shop", "2026-10-01"
            )
        self.window.refresh_ui()
        dashboard = self.window.dashboard
        total = dashboard.cards[0].text()

        def marker(name):
            return next(
                self.window.summary_table.item(row, 3)
                for row in range(self.window.summary_table.rowCount())
                if self.window.summary_table.item(row, 0).text() == name
            )

        marker("Euro").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dashboard.chart_data["expense"], 1000)
        self.assertEqual([w["name"] for w in dashboard.chart_data["wallets"]], ["Main"])
        self.assertEqual(dashboard.cards[0].text(), total)
        self.assertEqual(self.window.summary_table.rowCount(), 2)
        self.window.refresh_summary()
        self.assertEqual(marker("Euro").checkState(), Qt.CheckState.Unchecked)
        marker("Main").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dashboard.chart_data["count"], 0)
        self.assertEqual(dashboard.chart_data["wallets"], [])
        marker("Euro").setCheckState(Qt.CheckState.Checked)
        self.assertEqual(dashboard.chart_data["expense"], 2000)


if __name__ == "__main__":
    unittest.main()
