import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.counterparties import Counterparties, recipient_records


class CounterpartyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.cat = self.db.default_category_id()
        self.food = self.db.save_category("Food")
        self.a = self.db.save_transaction(
            self.wallet, "-100", self.cat, "Fuel", "2026-09-01", "MOL"
        )
        self.b = self.db.save_transaction(
            self.wallet, "-200", self.cat, "Fuel", "2026-10-01", "MOL"
        )
        self.c = self.db.save_transaction(
            self.wallet, "-50", self.food, "Shop", "2026-10-02", "Lidl"
        )
        self.db.save_transaction(
            self.wallet, "75", self.cat, "Refund", "2026-10-03", "MOL", analysis_kind="refund"
        )
        excluded = self.db.save_transaction(
            self.wallet, "-999", self.cat, "Hidden", "2026-10-04", "MOL"
        )
        self.db.set_report_inclusion(excluded, False)
        self.data = spending_snapshot(self.db, "PLN", after_refunds=False)
        self.owner = QWidget()
        self.owner.open_rows = Mock()
        self.owner.chart_windows = []
        self.view = Counterparties(self.owner)
        self.addCleanup(self.owner.deleteLater)
        self.view.refresh(self.data)

    def test_exact_totals_average_median_and_monthly_series(self):
        rows = {r["name"]: r for r in recipient_records(self.data)}
        self.assertEqual(rows["MOL"]["total"], 30000)
        self.assertEqual(rows["MOL"]["count"], 2)
        self.assertEqual(rows["MOL"]["average"], 15000)
        self.assertEqual(rows["MOL"]["median"], 15000)
        self.assertEqual(dict(rows["MOL"]["monthly"]), {"2026-09": 10000, "2026-10": 20000})
        self.assertEqual(self.view.current_name, "MOL")
        self.view.transactions.click()
        self.assertEqual(set(self.owner.open_rows.call_args.args[0]), {self.a, self.b})

    def test_search_category_sort_and_empty_selection_clear_details(self):
        self.view.search.setText("lidl")
        self.assertEqual(self.view.table.rowCount(), 1)
        self.assertEqual(self.view.current_name, "Lidl")
        self.view.search.clear()
        self.view.category.setCurrentIndex(self.view.category.findData(self.food))
        self.assertEqual(list(self.view.records), ["Lidl"])
        self.view.search.setText("missing")
        self.assertIsNone(self.view.current_name)
        self.assertFalse(self.view.transactions.isEnabled())
        self.assertEqual(self.view.recent_layout.count(), 0)
        self.view.refresh(None)
        self.assertEqual(self.view.table.rowCount(), 0)

    def test_spending_details_keep_text_height_when_panel_is_resized(self):
        self.owner.resize(1300, 700)
        self.view.resize(1300, 700)
        self.owner.show()
        self.view.show()
        try:
            for height in (260, 130, 320):
                self.view.right.setSizes([260, height, 150])
                self.app.processEvents()
                for row in range(6):
                    for column in range(2):
                        field = self.view.details_grid.itemAtPosition(row, column).widget()
                        self.assertGreaterEqual(
                            field.contentsRect().height(), field.fontMetrics().height()
                        )
                self.assertFalse(self.view.right.widget(1).grab().isNull())
        finally:
            self.owner.hide()

    def test_changing_recipient_hides_previous_detail_labels_immediately(self):
        previous = self.view.details_grid.itemAtPosition(0, 1).widget()
        self.view.search.setText("Lidl")
        self.assertTrue(previous.isHidden())
        self.assertEqual(self.view.details_grid.itemAtPosition(0, 1).widget().text(), "Food")
