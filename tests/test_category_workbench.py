import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from home_finance_cockpit.domain.category_icons import CATEGORY_ICONS
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_workbench import CategoryManagerPage
from home_finance_cockpit.ui.components import PATHS
from home_finance_cockpit.ui.editors import CategoryDialog


class WorkbenchTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.root = self.db.save_category("Transport", color="#22D3EE", icon_name="car")
        self.child = self.db.save_category("Fuel", parent_id=self.root)
        self.rule = self.db.save_rule(
            self.child,
            "description",
            "MOL",
            conditions=[dict(column_name="description", mode="not_contains", pattern="parowka")],
        )
        self.other = self.db.save_rule(self.child, "description", "ORLEN")
        self.page = CategoryManagerPage(None, self.db)
        self.addCleanup(self.page.deleteLater)

    def test_inline_compound_rule_preview_save_and_validation(self):
        page = self.page
        page.choose_rule(self.rule)
        self.assertEqual(len(page.editor.conditions), 2)
        page.editor.conditions[1][3].setText("snack")
        self.assertIn("snack", page.editor.preview.text())
        self.assertTrue(page.save_rule())
        self.assertIn(
            "snack", next(r for r in self.db.rules() if r["id"] == self.rule)["conditions_json"]
        )
        page.editor.conditions[0][3].clear()
        with patch("home_finance_cockpit.ui.category_workbench.show_error") as error:
            self.assertFalse(page.save_rule())
            error.assert_called_once()
        self.assertEqual(next(r for r in self.db.rules() if r["id"] == self.rule)["pattern"], "MOL")

    def test_unsaved_rule_navigation_and_rule_search(self):
        page = self.page
        page.choose_rule(self.rule)
        page.editor.conditions[0][3].setText("Edited")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            page.choose_rule(self.other)
        self.assertEqual(page.selected_rule_id, self.rule)
        self.assertEqual(page.editor.conditions[0][3].text(), "Edited")
        page.cancel_rule()
        page.rule_search.setText("orlen")
        self.assertEqual(page.rule_list.count(), 1)
        self.assertEqual(page.records[0]["id"], self.other)
        self.assertTrue(page.include_bank.isChecked())
        self.assertFalse(page.include_manual.isChecked())
        self.assertFalse(page.apply_dialog.isVisible())

    def test_create_remove_conditions_and_subcategory_has_no_icon_choice(self):
        page = self.page
        page.add_rule()
        page.editor.category.setCurrentIndex(page.editor.category.findData(self.child))
        page.editor.conditions[0][3].setText("BP")
        page.editor.add_condition()
        entry = page.editor.conditions[-1]
        entry[3].setText("snack")
        page.editor.remove_condition(entry)
        self.assertEqual(len(page.editor.conditions), 1)
        self.assertTrue(page.save_rule())
        self.assertEqual(len(self.db.rules()), 3)
        dialog = CategoryDialog(None, self.db, self.db.category(self.child))
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.icon_button.isHidden())
        self.assertTrue(dialog.color.isHidden())
        self.assertEqual(len(CATEGORY_ICONS), 40)
        self.assertTrue(set(CATEGORY_ICONS) <= set(PATHS))

    def test_new_rule_draft_is_replaced_at_top_after_save_and_removed_on_cancel(self):
        self.page.add_rule()
        self.assertIsNone(self.page.rule_list.item(0).data(Qt.ItemDataRole.UserRole))
        self.assertTrue(self.page.new_rule_pending)
        self.page.editor.category.setCurrentIndex(self.page.editor.category.findData(self.child))
        self.page.editor.conditions[0][3].setText("BP")
        self.assertTrue(self.page.save_rule())
        self.assertEqual(
            self.page.rule_list.item(0).data(Qt.ItemDataRole.UserRole),
            max(r["id"] for r in self.db.rules()),
        )
        self.assertFalse(self.page.new_rule_pending)
        self.page.add_rule()
        self.page.cancel_rule()
        self.assertEqual(self.page.rule_list.count(), 3)
        self.assertIsNotNone(self.page.rule_list.item(0).data(Qt.ItemDataRole.UserRole))

    def test_rule_usage_counts_actual_assignments_and_caps_display(self):
        wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        with self.db.transaction():
            self.db.conn.executemany(
                "INSERT INTO transactions(wallet_id,amount_minor,category_id,date,category_source,matched_rule_id) VALUES (?,?,?,?,?,?)",
                [(wallet, -100, self.child, "2026-10-01", "rule", self.rule)] * 1001,
            )
        self.page.refresh_rules()
        item = next(
            self.page.rule_list.item(i)
            for i in range(self.page.rule_list.count())
            if self.page.rule_list.item(i).data(Qt.ItemDataRole.UserRole) == self.rule
        )
        count = self.page.rule_list.itemWidget(item).findChild(QLabel, "ruleUsageCount")
        self.assertEqual(count.text(), "+999")
        self.assertIn("1001", count.toolTip())

    def test_added_condition_expands_editor_before_save(self):
        self.page.resize(1450, 900)
        self.page.show()
        self.app.processEvents()
        editor = self.page.editor
        editor.add_condition()
        self.app.processEvents()
        last = editor.conditions[-1][0]
        self.assertLessEqual(last.geometry().bottom(), editor.scroll.viewport().height())
        self.assertEqual(editor.scroll.verticalScrollBar().maximum(), 0)

    def test_delete_category_confirmation_can_be_cancelled(self):
        root = self.page.tree.topLevelItem(1)
        for index in range(self.page.tree.topLevelItemCount()):
            item = self.page.tree.topLevelItem(index)
            if item.data(0, Qt.ItemDataRole.UserRole) == self.root:
                root = item
                break
        self.page.tree.setCurrentItem(root)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.page.delete_category()
        self.assertIsNotNone(self.db.find_category("Transport"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.page.delete_category()
        self.assertIsNone(self.db.find_category("Transport"))

    def test_edit_icon_opens_the_clicked_category(self):
        page = self.page
        root = next(
            page.tree.topLevelItem(i)
            for i in range(page.tree.topLevelItemCount())
            if page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == self.root
        )
        with patch("home_finance_cockpit.ui.category_actions.CategoryDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            page.tree.edit_requested.emit(root.child(0))
        self.assertEqual(dialog.call_args.args[2]["id"], self.child)

    def test_single_click_selects_and_double_click_expands_without_editing(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtTest import QTest

        page = self.page
        page.resize(1200, 800)
        page.show()
        self.app.processEvents()
        root = next(
            page.tree.topLevelItem(i)
            for i in range(page.tree.topLevelItemCount())
            if page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == self.root
        )
        root.setExpanded(False)
        page.tree.scrollToItem(root)
        self.app.processEvents()
        rect = page.tree.visualItemRect(root)
        point = QPoint(rect.left() + 40, rect.center().y())
        QTest.mouseClick(page.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertFalse(root.isExpanded())
        with patch("home_finance_cockpit.ui.category_actions.CategoryDialog") as dialog:
            QTest.mouseDClick(page.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertTrue(root.isExpanded())
            dialog.assert_not_called()
        page.hide()

    def test_clearing_category_leaves_editor_empty_until_a_rule_is_selected(self):
        other = self.db.save_category("Home")
        rent = self.db.save_rule(other, "description", "RENT")
        self.page.refresh()
        root = next(
            self.page.tree.topLevelItem(i)
            for i in range(self.page.tree.topLevelItemCount())
            if self.page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == self.root
        )
        self.page.tree.setCurrentItem(root.child(0))
        self.page.clear_category_button.click()
        self.assertEqual(self.page.tree.selectedItems(), [])
        self.assertIsNone(self.page.tree.currentItem())
        self.assertIsNone(self.page.editor)
        self.assertFalse(self.page.save_rule_button.isEnabled())
        self.page.rule_search.setText("RENT")
        self.assertEqual([r["id"] for r in self.page.records], [rent])
        self.assertIsNone(self.page.editor)
        self.page.choose_rule(rent)
        self.assertEqual(self.page.editor.record["id"], rent)

    def test_category_plus_opens_new_child_for_the_clicked_parent(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtTest import QTest

        self.page.resize(1200, 800)
        self.page.show()
        self.app.processEvents()
        root = next(
            self.page.tree.topLevelItem(i)
            for i in range(self.page.tree.topLevelItemCount())
            if self.page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == self.root
        )
        point = QPoint(
            self.page.tree.viewport().width() - 75, self.page.tree.visualItemRect(root).center().y()
        )
        with patch("home_finance_cockpit.ui.category_workbench.CategoryDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            QTest.mouseClick(self.page.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(dialog.call_args.kwargs["parent_id"], self.root)

    def test_legacy_raw_rule_requires_an_application_field_when_edited(self):
        identifier = self.db.execute(
            "INSERT INTO rules(category_id,column_name,pattern,mode) VALUES (?,?,?,?)",
            (self.child, "raw:Private", "example", "literal"),
        ).lastrowid
        self.page.refresh()
        self.page.choose_rule(identifier)
        column = self.page.editor.conditions[0][1]
        self.assertEqual(column.count(), 4)
        self.assertIsNone(column.currentData())
        with patch("home_finance_cockpit.ui.category_workbench.show_error") as error:
            self.assertFalse(self.page.save_rule())
            error.assert_called_once()
