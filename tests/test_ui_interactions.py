"""Drag-only text selection and bounded filter popups."""

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QToolButton

from home_finance_cockpit.localization import language, quote_text, set_language
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_workbench import CategoryManagerPage
from home_finance_cockpit.ui.components import label
from home_finance_cockpit.ui.editors import CategoryDialog
from home_finance_cockpit.ui.text_selection import DragSelectableLabel
from home_finance_cockpit.ui.transaction_header import CategoryMenu


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_labels_select_only_by_drag_and_clear_on_another_click(self):
        widget = label("Amount 123.45 PLN example", "")
        self.addCleanup(widget.deleteLater)
        widget.resize(300, 50)
        widget.show()
        self.app.processEvents()
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(10, 25))
        self.assertFalse(widget.hasSelectedText())
        QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(10, 25))
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=QPoint(10, 25))
        self.assertFalse(widget.hasSelectedText())
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(1, 25))
        end = QPoint(250, 25)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(widget.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.app.sendEvent(widget, move)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        self.assertTrue(widget.hasSelectedText())
        self.assertFalse(widget.hasFocus())
        before = self.app.clipboard().text()
        self.addCleanup(self.app.clipboard().setText, before)
        QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.app.clipboard().text(), widget.selectedText())
        other = QPushButton("Other")
        self.addCleanup(other.deleteLater)
        QTest.mouseClick(other, Qt.MouseButton.LeftButton)
        self.assertFalse(widget.hasSelectedText())

    def test_rule_text_single_click_selects_the_rule(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        category = db.save_category("Food")
        first = db.save_rule(category, "description", "SHOP")
        db.save_rule(category, "description", "OTHER")
        page = CategoryManagerPage(None, db)
        self.addCleanup(page.deleteLater)
        page.resize(1200, 700)
        page.show()
        self.app.processEvents()
        item = next(
            page.rule_list.item(i)
            for i in range(page.rule_list.count())
            if page.rule_list.item(i).data(Qt.ItemDataRole.UserRole) == first
        )
        description = page.rule_list.itemWidget(item).findChild(DragSelectableLabel)
        QTest.mouseClick(description, Qt.MouseButton.LeftButton)
        self.assertEqual(page.selected_rule_id, first)
        self.assertFalse(description.hasSelectedText())

    def test_category_popup_starts_below_filter_and_stays_bounded(self):
        button = QToolButton()
        self.addCleanup(button.deleteLater)
        screen = button.screen().availableGeometry()
        button.setGeometry(screen.right() - 180, screen.top() + 60, 140, 35)
        button.show()
        changed = Mock()
        menu = CategoryMenu(
            button,
            [(i, "Long category name " + str(i) + "x" * 50) for i in range(100)],
            set(),
            "Search",
            changed,
            Mock(),
        )
        self.addCleanup(menu.close)
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        self.app.processEvents()
        self.assertGreaterEqual(menu.y(), button.mapToGlobal(QPoint(0, button.height())).y())
        self.assertLessEqual(menu.height(), 390)
        self.assertLessEqual(menu.geometry().right(), screen.right())
        menu.choices.item(0).setCheckState(Qt.CheckState.Checked)
        changed.assert_called_once_with(0, True)
        self.assertTrue(menu.isVisible())

    def test_new_subcategory_focuses_name_and_quotes_follow_language(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        parent = db.save_category("Food")
        dialog = CategoryDialog(None, db, parent_id=parent)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        dialog.activateWindow()
        self.app.processEvents()
        self.assertTrue(dialog.name.hasFocus())
        previous = language()
        self.addCleanup(set_language, previous)
        set_language("en")
        self.assertEqual(quote_text("SHOP"), '"SHOP"')
        self.assertEqual(quote_text(""), "")
        set_language("pl")
        self.assertEqual(quote_text("SHOP"), "„SHOP”")
