import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase

from matplotlib.figure import Figure
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analysis_summary import change_text, render_summary, summary_rows


class SummaryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_gross_totals_categories_and_month_changes_ignore_refund(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        wallet = db.save_wallet("Main", "0", "PLN", "2026-01-01")
        cat = db.default_category_id()
        for day, amount in [
            ("2026-09-01", "-1000"),
            ("2026-10-01", "-1100"),
            ("2026-11-01", "-1200"),
        ]:
            db.save_transaction(wallet, amount, cat, "Expense", day)
        db.save_transaction(wallet, "500", cat, "Refund", "2026-11-02", analysis_kind="refund")
        data = spending_snapshot(db, "PLN", after_refunds=False)
        months, rows = summary_rows(data)
        self.assertEqual(months, ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(rows, [(cat, [100000, 110000, 120000])])
        self.assertEqual(change_text(120000, 110000), ("+100.00", "+9.09%", 10000))
        ax = render_summary(Figure(), "months", data)
        self.assertEqual([bar.get_height() for bar in ax.patches], [1000, 1100, 1200])
        ax = render_summary(Figure(), "categories", data)
        self.assertEqual(ax.patches[0].get_width(), 3300)

    def test_empty_single_month_and_missing_previous_are_safe(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        data = spending_snapshot(db, "PLN", after_refunds=False)
        self.assertEqual(summary_rows(data), ([], []))
        render_summary(Figure(), "months", data)
        self.assertEqual(change_text(100, None), ("—", "—", None))
        self.assertEqual(change_text(100, 0), ("+1.00", "—", 100))
