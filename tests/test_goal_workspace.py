import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.goal_workspace import SavingsGoalsPage


class GoalWorkspaceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Cash", "300", "PLN", "2026-01-01")
        self.manual = self.db.save_savings_goal("Manual", None, "1000", "200", currency="PLN")
        self.automatic = self.db.save_savings_goal(
            "Automatic", self.wallet, "600", "0", calculation_mode="wallet"
        )
        self.page = SavingsGoalsPage(self.db)
        self.addCleanup(self.page.deleteLater)

    def test_inline_edit_cancel_save_and_guard(self):
        page = self.page
        self.assertEqual(page.selected_id, self.manual)
        page.editor.target.setText("2 000.00")
        self.assertTrue(page.dirty())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            page.goal_list.setCurrentRow(1)
        self.assertEqual(page.selected_id, self.manual)
        self.assertEqual(page.editor.target.text(), "2 000.00")
        self.assertTrue(page.save())
        self.assertEqual(self.db.savings_goals()[0]["target_minor"], 200000)
        self.assertFalse(page.dirty())
        page.editor.name.setText("Discard")
        page.cancel()
        self.assertEqual(page.editor.name.text(), "Manual")

    def test_contribution_and_wallet_balance_modes(self):
        page = self.page
        page.amount.setText("1 000.25")
        page.apply_contribution()
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 120025)
        self.assertEqual(self.db.wallet(self.wallet)["opening_minor"], 30000)
        page.goal_list.setCurrentRow(1)
        self.assertEqual(page.selected_id, self.automatic)
        self.assertTrue(page.contribution.isHidden())
        self.assertEqual(page.percent.text(), "50.00%")
        self.db.save_transaction(
            self.wallet, "-100", self.db.default_category_id(), "Expense", "2026-10-01"
        )
        page.refresh()
        self.assertEqual(page.percent.text(), "33.33%")

    def test_create_empty_wallet_manual_goal_and_search(self):
        page = self.page
        page.add()
        page.editor.mode.setCurrentIndex(page.editor.mode.findData("manual"))
        page.editor.name.setText("Holiday")
        page.editor.target.setText("10 000.00")
        page.editor.allocated.setText("1 000.00")
        self.assertTrue(page.save())
        self.assertEqual(page.record()["name"], "Holiday")
        page.search.setText("holiday")
        self.assertEqual(page.goal_list.count(), 1)
        page.editor.target.setText("0")
        with patch("home_finance_cockpit.ui.goal_workspace.show_error") as error:
            self.assertFalse(page.save())
            error.assert_called_once()
        self.assertEqual(page.record()["target_minor"], 1000000)

    def test_filter_keeps_selected_goal_and_editor_in_sync(self):
        page = self.page
        page.search.setText("Automatic")
        self.assertEqual(page.selected_id, self.automatic)
        self.assertEqual(page.editor.name.text(), "Automatic")
        self.assertEqual(page.percent.text(), "50.00%")
        self.assertTrue(page.contribution.isHidden())
        page.search.setText("not a goal")
        self.assertEqual(page.goal_list.count(), 0)
        self.assertIsNone(page.selected_id)
        self.assertIsNone(page.editor)
        page.search.clear()
        self.assertEqual(page.editor.name.text(), "Manual")
        self.assertEqual(page.selected_id, self.manual)

    def test_filter_does_not_discard_unsaved_goal_changes(self):
        page = self.page
        page.editor.name.setText("Unsaved draft")
        page.search.setText("Automatic")
        self.assertEqual(page.selected_id, self.manual)
        self.assertEqual(page.editor.name.text(), "Unsaved draft")
        self.assertTrue(page.dirty())

    def test_goal_cards_fit_their_content(self):
        page = self.page
        page.resize(1100, 850)
        page.show()
        self.app.processEvents()
        for index in range(page.goal_list.count()):
            item = page.goal_list.item(index)
            card = page.goal_list.itemWidget(item)
            self.assertGreaterEqual(item.sizeHint().height(), card.minimumSizeHint().height())
        page.hide()
