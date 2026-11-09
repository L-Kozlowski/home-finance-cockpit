import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.time_overview import TimeOverview, weekday_averages


class TimeOverviewTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        cat = self.db.default_category_id()
        self.sep = self.db.save_transaction(self.wallet, "-100", cat, "Expense", "2026-09-01")
        self.oct = self.db.save_transaction(self.wallet, "-310", cat, "Expense", "2026-10-01")
        excluded = self.db.save_transaction(self.wallet, "-999", cat, "Excluded", "2026-10-02")
        self.db.set_report_inclusion(excluded, False)
        self.data = spending_snapshot(self.db, "PLN", after_refunds=False)
        self.owner = QWidget()
        self.owner.open_rows = Mock()
        self.owner.chart_windows = []
        self.view = TimeOverview(self.owner)
        self.addCleanup(self.owner.deleteLater)
        self.view.refresh(self.data)

    def test_month_navigation_and_day_drilldown(self):
        self.assertEqual(self.view.month.currentData(), "2026-10")
        self.assertTrue(self.view.previous.isEnabled())
        self.assertFalse(self.view.next.isEnabled())
        self.view.select_day(0, 3)
        self.owner.open_rows.assert_not_called()
        self.view.transactions.click()
        self.owner.open_rows.assert_called_with([self.oct])
        self.assertIn("310.00", self.view.selection_label.text())
        self.view.previous.click()
        self.assertEqual(self.view.month.currentData(), "2026-09")
        self.assertIsNone(self.view.selected_day)
        self.view.activate_day(0, 1)
        self.owner.open_rows.assert_called_with([self.sep])
        self.view.transactions.click()
        self.owner.open_rows.assert_called_with([self.sep])

    def test_weekday_mean_includes_zero_spending_days(self):
        averages, counts = weekday_averages(self.data, today=date(2026, 10, 31))
        self.assertEqual(sum(counts), 61)
        self.assertAlmostEqual(sum(a * c for a, c in zip(averages, counts)), 41000)
        self.assertAlmostEqual(averages[3], 31000 / counts[3])

    def test_calendar_padding_and_filtered_empty_day(self):
        self.owner.open_rows.reset_mock()
        self.view.select_day(0, 0)
        self.owner.open_rows.assert_not_called()
        self.view.select_day(0, 4)
        self.owner.open_rows.assert_not_called()
        self.view.transactions.click()
        self.owner.open_rows.assert_called_with([])
        self.view.refresh(None)
        self.assertEqual(self.view.calendar.rowCount(), 0)
        self.assertFalse(self.view.transactions.isEnabled())
