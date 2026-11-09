import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.localization import set_language
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_overview import CategoryOverview, expense_groups


class CategoryOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.root = self.db.save_category("Food", icon_name="food")
        self.child = self.db.save_category("Grocery", parent_id=self.root, icon_name="cart")
        for amount, category, day, kind in [
            ("-100", self.child, "2026-10-01", "standard"),
            ("-50", self.root, "2026-10-02", "standard"),
            ("20", self.child, "2026-10-03", "refund"),
            ("-900", self.root, "2026-09-01", "standard"),
            ("-400", self.root, "2026-10-04", "transfer"),
        ]:
            self.db.save_transaction(
                self.wallet, amount, category, "Example", day, analysis_kind=kind
            )
        self.owner = QWidget()
        self.view = CategoryOverview(self.owner)
        self.addCleanup(self.owner.deleteLater)

    def data(self, **kwargs):
        return spending_snapshot(self.db, "PLN", month="2026-10", after_refunds=False, **kwargs)

    def test_localized_overview_and_left_aligned_table(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel

        from home_finance_cockpit.ui.navigation import PAGES

        self.addCleanup(set_language, "pl")
        for code, title, header, amount in (
            ("pl", "Wydatki łącznie", "Kategoria / podkategoria", "150,00 PLN"),
            ("en", "Total expenses", "Category / subcategory", "150.00 PLN"),
        ):
            set_language(code)
            view = CategoryOverview(self.owner)
            view.refresh(self.data())
            captions = [widget.text() for widget in view.findChildren(QLabel)]
            self.assertIn(title, captions)
            self.assertNotIn("Na co wydajesz pieniądze?", captions)
            self.assertEqual(view.tree.headerItem().text(0), header)
            self.assertEqual(view.metrics[0][0].text(), amount)
            for column in range(4):
                self.assertEqual(
                    view.tree.headerItem().textAlignment(column),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                self.assertEqual(
                    view.tree.topLevelItem(0).textAlignment(column),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
            view.deleteLater()
        self.assertEqual(PAGES[0][0], PAGES[0][2])
        self.assertEqual(PAGES[4][0], PAGES[4][2])

    def test_counts_totals_and_children_match_expenses_not_inflows(self):
        data = self.data()
        groups, _ = expense_groups(data)
        self.assertEqual(groups[self.root]["amount"], data["gross"])
        self.assertEqual(groups[self.root]["count"], 2)
        self.assertEqual(sum(c["amount"] for c in groups[self.root]["children"].values()), 15000)
        self.view.refresh(data)
        item = self.view.tree.topLevelItem(0)
        self.assertEqual(item.text(1), "2")
        self.assertEqual(item.childCount(), 2)
        self.assertFalse(item.icon(0).isNull())
        self.assertFalse(item.child(0).icon(0).isNull())
        self.assertEqual(self.view.ring.total, 15000)

    def test_filters_empty_state_and_expansion_survive_refresh(self):
        self.view.refresh(self.data())
        self.view.tree.collapseAll()
        self.view.refresh(self.data())
        self.assertFalse(self.view.tree.topLevelItem(0).isExpanded())
        self.view.refresh(self.data(amount_max=-7500))
        self.assertEqual(self.view.ring.total, 10000)
        self.assertEqual(self.view.ring.count, 1)
        self.view.refresh(None)
        self.assertEqual(self.view.tree.topLevelItemCount(), 0)
        self.assertEqual(self.view.legend.topLevelItemCount(), 0)
        self.assertEqual(self.view.ring.total, 0)
