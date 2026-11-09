import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date
from unittest import TestCase
from unittest.mock import Mock

from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.services.period_comparison import comparison
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.period_comparison import PeriodComparison


class ComparisonTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        w = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.cat = self.db.default_category_id()
        self.a = self.db.save_transaction(w, "-100", self.cat, "Expense", "2026-09-01")
        self.b = self.db.save_transaction(w, "-200", self.cat, "Expense", "2026-10-01")
        self.extra = self.db.save_transaction(w, "-500", self.cat, "Last day", "2026-10-31")
        self.credit = self.db.save_transaction(w, "300", self.cat, "Income", "2026-10-02")
        self.data = spending_snapshot(self.db, "PLN", after_refunds=False)

    def test_equal_days_full_period_and_normalized_categories(self):
        equal = comparison(self.data, "2026-09", "2026-10", today=date(2027, 1, 1))
        self.assertEqual((equal["a"]["days"], equal["b"]["days"]), (30, 30))
        self.assertEqual(equal["b"]["total"], 20000)
        self.assertEqual(equal["changed_ids"], [self.a, self.b])
        full = comparison(
            self.data, "2026-09", "2026-10", equal_days=False, per_day=True, today=date(2027, 1, 1)
        )
        self.assertEqual(full["b"]["days"], 31)
        self.assertEqual(full["b"]["count"], 2)
        self.assertEqual(full["b"]["median"], 35000)
        self.assertAlmostEqual(full["values"][self.cat][1], 70000 / 31)
        self.assertEqual(full["b"]["highest"], 50000)

    def test_controls_swap_drilldown_and_empty_data(self):
        owner = QWidget()
        owner.open_rows = Mock()
        owner.chart_windows = []
        view = PeriodComparison(owner)
        self.addCleanup(owner.deleteLater)
        view.refresh(self.data)
        self.assertEqual(view.period_a.currentData(), "2026-09")
        self.assertEqual(view.period_b.currentData(), "2026-10")
        view.transactions.click()
        owner.open_rows.assert_called_with([self.a, self.b])
        view.swap()
        self.assertEqual(view.period_a.currentData(), "2026-10")
        view.normalization.setCurrentIndex(1)
        self.assertTrue(view.result["per_day"])
        view.refresh(None)
        self.assertIsNone(view.result)
        self.assertFalse(view.transactions.isEnabled())

    def test_current_month_uses_elapsed_days_and_identical_period_has_no_changes(self):
        result = comparison(self.data, "2026-09", "2026-10", today=date(2026, 10, 12))
        self.assertEqual(result["a"]["days"], 12)
        self.assertEqual(result["b"]["days"], 12)
        result = comparison(self.data, "2026-09", "2026-09")
        self.assertEqual(result["changed_ids"], [])

    def test_visual_columns_and_dot_labels_match_comparison_layout(self):
        from matplotlib.figure import Figure

        from home_finance_cockpit.ui.period_comparison import render_comparison

        result = comparison(self.data, "2026-09", "2026-10")
        figure = Figure()
        render_comparison(figure, "changes", result)
        self.assertEqual(len(figure.axes), 3)
        self.assertTrue(any(t.get_text() == "+100.00" for t in figure.axes[1].texts))
        self.assertTrue(any(t.get_text() == "+100.00%" for t in figure.axes[2].texts))
        ax = render_comparison(Figure(), "paired", result)
        labels = [t for t in ax.texts if hasattr(t, "_semantic_color")]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all(t.get_va() == "center" for t in labels))
        self.assertTrue(all(t.get_position()[1] == 0 for t in labels))
        self.assertEqual(ax.get_xlabel(), "")
        self.assertTrue(any(t.get_text() == "PLN" and t.get_position()[0] < 0 for t in ax.texts))

    def test_zero_category_values_do_not_get_value_annotations(self):
        from matplotlib.figure import Figure

        from home_finance_cockpit.ui.period_comparison import render_comparison

        category = self.db.save_category("Only October")
        wallet = self.db.transactions(transaction_id=self.a)[0]["wallet_id"]
        self.db.save_transaction(wallet, "-10", category, "New", "2026-10-01")
        result = comparison(
            spending_snapshot(self.db, "PLN", after_refunds=False), "2026-09", "2026-10"
        )
        ax = render_comparison(Figure(), "paired", result)
        annotations = [text.get_text() for text in ax.texts if hasattr(text, "_semantic_color")]
        self.assertEqual(len(annotations), 3)
        self.assertNotIn("0.00", annotations)

    def test_amount_labels_hide_only_category_collisions_and_recheck_after_resize(self):
        from unittest.mock import patch

        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.text import Annotation

        from home_finance_cockpit.ui.period_comparison import CategoryAmountLabel, render_comparison

        result = comparison(self.data, "2026-09", "2026-10")
        result["roots"] = [1, 2]
        result["category_names"] = {1: "Subscriptions", 2: "Housing"}
        result["values"] = {1: (4900, 6900), 2: (380600, 533300)}
        figure = Figure(figsize=(8, 3), dpi=100)
        canvas = FigureCanvasAgg(figure)
        ax = render_comparison(figure, "paired", result)
        labels = [text for text in ax.texts if isinstance(text, CategoryAmountLabel)]
        with patch.object(Annotation, "draw", autospec=True) as draw:
            canvas.draw()
            renderer = canvas.get_renderer()
            collisions = [label for label in labels if label.overlaps_category(renderer)]
            self.assertTrue(collisions)
            self.assertLess(len(collisions), len(labels))
            self.assertEqual(draw.call_count, len(labels) - len(collisions))
            figure.set_size_inches(120, 3)
            draw.reset_mock()
            canvas.draw()
            remaining = [
                label for label in labels if label.overlaps_category(canvas.get_renderer())
            ]
            self.assertLess(len(remaining), len(collisions))
            self.assertEqual(draw.call_count, len(labels) - len(remaining))
