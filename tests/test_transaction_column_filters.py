"""Column filtering must preserve ledger balances and sortable transaction identity."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QDate, QPoint, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.filters import FiltersDialog
from home_finance_cockpit.ui.transactions_page import TransactionsPage


class ColumnFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.category = self.db.save_category("Food")
        self.first = self.db.save_transaction(
            self.wallet, "-100", self.category, "Shop", "2026-09-01"
        )
        self.second = self.db.save_transaction(
            self.wallet, "-50", self.category, "Market", "2026-09-01"
        )
        self.third = self.db.save_transaction(
            self.wallet, "25", self.db.default_category_id(), "Refund", "2026-09-02"
        )
        other = self.db.save_wallet("Cash", "20", "PLN", "2026-01-01")
        self.fourth = self.db.save_transaction(
            other, "-5", self.category, "Cash shop", "2026-09-03"
        )
        self.page = TransactionsPage(self.db, MagicMock())
        self.addCleanup(self.page.close)
        self.page.filters.refresh_choices()
        self.page.refresh()
        self.header = self.page.column_filters

    def ids(self):
        return {r["id"] for r in self.page.records}

    def test_columns_fill_viewport_and_preserve_manual_width_and_filter_geometry(self):
        self.page.resize(1800, 900)
        self.page.show()
        QTest.qWait(50)
        visible = [i for i in range(self.header.count()) if not self.header.isSectionHidden(i)]
        self.assertEqual(
            sum(self.header.sectionSize(i) for i in visible), self.page.table.viewport().width()
        )
        self.header.resizeSection(7, self.header.sectionSize(7) - 40)
        manual_width = self.header.sectionSize(7)
        self.page.refresh()
        self.header.toggle_filters()
        self.header.toggle_filters()
        QTest.qWait(50)
        self.assertEqual(self.header.sectionSize(7), manual_width)
        self.page.resize(2000, 900)
        QTest.qWait(50)
        self.assertEqual(
            sum(self.header.sectionSize(i) for i in visible), self.page.table.viewport().width()
        )
        self.page.table.setColumnHidden(2, False)
        QTest.qWait(50)
        self.assertEqual(
            sum(self.header.sectionSize(i) for i in visible + [2]),
            self.page.table.viewport().width(),
        )
        for logical in visible + [2]:
            editor = self.header.editors[logical]
            self.assertEqual(editor.x(), self.header.sectionViewportPosition(logical))
            self.assertEqual(editor.width(), self.header.sectionSize(logical))

    def test_report_menu_and_centered_checkbox_update_the_correct_transaction(self):
        self.page.resize(1800, 900)
        self.page.show()
        QTest.qWait(50)
        self.header.reports_button.menu().actions()[1].trigger()
        self.assertIs(self.header.reports.currentData(), True)
        self.assertEqual(self.header.reports_button.text(), self.header.reports.currentText())
        item = self.page.table.item(0, 10)
        identifier = item.data(Qt.ItemDataRole.UserRole)
        rect = self.page.table.visualItemRect(item)
        QTest.mouseClick(self.page.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertFalse(self.db.transactions(transaction_id=identifier)[0]["include_in_reports"])
        self.page.refresh()
        self.assertNotIn(identifier, self.ids())
        self.header.clear()
        self.page.refresh()
        self.assertIsNone(self.header.reports.currentData())
        self.assertEqual(self.header.reports_button.text(), self.header.reports.currentText())

    def test_signed_amount_range_and_invalid_input(self):
        low, high = self.header.ranges[5]
        low.setText("-100,00")
        high.setText("-50")
        refreshed = QSignalSpy(self.header.timer.timeout)
        self.assertTrue(refreshed.wait(1500))
        self.assertEqual(self.ids(), {self.first, self.second})
        self.assertEqual(self.page.visible_expense, 15000)
        low.setText("-")
        self.page.refresh()
        self.assertEqual(self.ids(), set())
        self.assertTrue(low.toolTip())
        low.setText("-40")
        self.page.refresh()
        self.assertEqual(self.ids(), set())
        self.assertTrue(high.toolTip())

    def test_balances_use_full_wallet_history_before_filtering(self):
        balances = {r["id"]: r["balance_after_minor"] for r in self.page.records}
        self.assertEqual(
            balances, {self.first: 90000, self.second: 85000, self.third: 87500, self.fourth: 1500}
        )
        self.page.search.setText("Refund")
        self.assertEqual(self.page.records[0]["balance_after_minor"], 87500)
        self.page.search.clear()
        self.header.ranges[12][0].setText("850")
        self.header.ranges[12][1].setText("875")
        self.page.refresh()
        self.assertEqual(self.ids(), {self.second, self.third})
        self.page.table.sortItems(12, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.page.table.item(0, 0).data(Qt.ItemDataRole.UserRole), self.second)

    def test_shared_categories_dates_wallet_and_reset(self):
        self.header.category_changed(self.category, True)
        self.assertEqual(self.ids(), {self.first, self.second, self.fourth})
        self.header.wallet_changed(self.wallet, True)
        self.assertEqual(self.ids(), {self.first, self.second})
        self.header.dates[0].setDate(QDate(2026, 9, 2))
        self.assertEqual(self.ids(), set())
        self.assertEqual(self.page.filters.preset.currentData(), "custom")
        self.page.analysis_ids = {self.first}
        self.page.clear_analysis_button.click()
        self.assertEqual(self.ids(), {self.first, self.second, self.third, self.fourth})
        self.assertIsNone(self.page.analysis_ids)
        self.assertFalse(self.header.active)

    def test_editors_follow_scroll_move_and_hidden_columns(self):
        self.page.resize(1050, 650)
        self.page.show()
        self.app.processEvents()
        self.header.moveSection(self.header.visualIndex(12), 1)
        self.page.table.horizontalScrollBar().setValue(80)
        self.app.processEvents()
        editor = self.header.editors[12]
        self.assertEqual(editor.x(), self.header.sectionViewportPosition(12))
        self.assertEqual(editor.width(), self.header.sectionSize(12))
        self.assertGreaterEqual(editor.y(), 0)
        QTest.mouseClick(
            self.header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(self.header.sectionViewportPosition(0) + 15, 10),
        )
        self.assertEqual(self.header.sortIndicatorSection(), 0)
        self.page.table.hideColumn(12)
        self.app.processEvents()
        self.assertTrue(editor.isHidden())

    def test_multiple_wallets_share_selection_and_clear(self):
        other = self.db.transactions(transaction_id=self.fourth)[0]["wallet_id"]
        self.header.wallet_changed(self.wallet, True)
        self.assertEqual(self.ids(), {self.first, self.second, self.third})
        self.header.wallet_changed(other, True)
        self.assertEqual(self.ids(), {self.first, self.second, self.third, self.fourth})
        self.assertEqual(self.page.filters.selected_wallet_ids, {self.wallet, other})
        host = QWidget()
        host.transaction_filters = self.page.filters
        dialog = FiltersDialog(host, transactions=True)
        dialog.apply()
        self.assertEqual(self.page.filters.selected_wallet_ids, {self.wallet, other})
        dialog.deleteLater()
        self.header.wallet_changed(self.wallet, False)
        self.assertEqual(self.ids(), {self.fourth})
        self.assertEqual(self.page.filters.wallet.currentData(), other)
        self.header.clear_wallets()
        self.assertFalse(self.page.filters.selected_wallet_ids)
        self.assertEqual(len(self.ids()), 4)

    def test_balance_fields_fill_column_after_filter_changes(self):
        self.page.resize(1500, 760)
        self.page.show()
        self.app.processEvents()
        for query in ("Refund", "", "Shop"):
            self.page.search.setText(query)
            self.app.processEvents()
            box = self.header.editors[12]
            self.assertEqual(box.width(), self.header.sectionSize(12))
            for field in self.header.ranges[12]:
                self.assertEqual(field.x(), 0)
                self.assertEqual(field.width(), box.width())
            first, last = self.header.ranges[12]
            self.assertEqual(first.y(), 0)
            self.assertEqual(last.geometry().bottom(), box.height() - 1)

    def test_date_field_opens_calendar_without_typing(self):
        self.page.show()
        self.app.processEvents()
        field = self.header.dates[0]
        QTest.mouseClick(field.lineEdit(), Qt.MouseButton.LeftButton)
        self.assertTrue(field.popup.isVisible())
        field.calendar.clicked.emit(QDate(2026, 9, 2))
        self.assertFalse(field.popup.isVisible())
        self.assertEqual(field.date(), QDate(2026, 9, 2))
        self.assertEqual(self.ids(), {self.third, self.fourth})
        QTest.keyClicks(field.lineEdit(), "1234")
        self.assertEqual(field.date(), QDate(2026, 9, 2))

    def test_collapsing_keeps_filters_active_and_reduces_header_height(self):
        self.page.show()
        self.header.ranges[5][0].setText("-100")
        self.header.ranges[5][1].setText("-50")
        self.page.refresh()
        self.app.processEvents()
        expanded = self.header.height()
        self.header.collapse_button.click()
        self.app.processEvents()
        self.assertLess(self.header.height(), expanded)
        self.assertTrue(self.header.editors[5].isHidden())
        self.assertEqual(self.ids(), {self.first, self.second})
        self.assertIn(5, self.header.active)
        self.header.collapse_button.click()
        self.app.processEvents()
        self.assertEqual(self.header.height(), expanded)
        self.assertFalse(self.header.editors[5].isHidden())
        self.assertEqual(self.header.ranges[5][0].text(), "-100")

    def test_clicking_heading_sorts_rows_in_both_directions(self):
        self.page.resize(1400, 700)
        self.page.show()
        self.app.processEvents()
        location = QPoint(self.header.sectionViewportPosition(5) + 20, 10)
        for _ in range(2):
            QTest.mouseClick(self.header.viewport(), Qt.MouseButton.LeftButton, pos=location)
            self.assertEqual(self.header.sortIndicatorSection(), 5)
            actual = [
                self.page.record_map[self.page.table.item(r, 0).data(Qt.ItemDataRole.UserRole)][
                    "amount_minor"
                ]
                for r in range(self.page.table.rowCount())
            ]
            self.assertEqual(
                actual,
                sorted(
                    actual, reverse=self.header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
                ),
            )

    def test_calendar_dims_dates_outside_displayed_month(self):
        calendar = self.header.dates[0].calendar
        calendar.setCurrentPage(2026, 11)
        muted = calendar.dateTextFormat(QDate(2026, 10, 31)).foreground()
        self.assertNotEqual(muted.style(), Qt.BrushStyle.NoBrush)
        self.assertEqual(
            calendar.dateTextFormat(QDate(2026, 11, 5)).foreground().style(), Qt.BrushStyle.NoBrush
        )
        calendar.setCurrentPage(2026, 10)
        self.assertEqual(
            calendar.dateTextFormat(QDate(2026, 10, 31)).foreground().style(), Qt.BrushStyle.NoBrush
        )

    def test_bulk_copy_and_move_actions_use_selected_ids(self):
        selected = {self.first, self.second}
        self.page.restore_selection(selected)
        destination = self.db.transactions(transaction_id=self.fourth)[0]["wallet_id"]
        with patch(
            "home_finance_cockpit.ui.transactions_page.WalletDestinationDialog.exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.page.relocate_selection(copy=True)
        self.assertEqual(len(self.db.transactions()), 6)
        self.assertTrue(
            all(
                self.db.transactions(transaction_id=i)[0]["wallet_id"] == self.wallet
                for i in selected
            )
        )

        with patch(
            "home_finance_cockpit.ui.transactions_page.WalletDestinationDialog.exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.page.relocate_selection(copy=False)
        self.assertTrue(
            all(
                self.db.transactions(transaction_id=i)[0]["wallet_id"] == destination
                for i in selected
            )
        )

    def test_amount_popup_and_column_fields_share_values_and_width_is_preserved(self):
        self.header.ranges[5][0].setText("-100")
        self.page.refresh()
        host = QWidget()
        host.transaction_filters = self.page.filters
        dialog = FiltersDialog(host, transactions=True)
        self.assertEqual(dialog.amount_min.text(), "-100")
        dialog.amount_max.setText("-50")
        dialog.apply()
        self.assertEqual(self.header.ranges[5][1].text(), "-50")
        self.assertEqual(self.ids(), {self.first, self.second})
        self.page.table.setColumnWidth(7, 480)
        self.page.refresh()
        self.assertEqual(self.page.table.columnWidth(7), 480)
        dialog.deleteLater()

    def test_ctrl_click_adds_sort_columns_and_toggles_each_direction(self):
        self.page.resize(1500, 760)
        self.page.show()
        self.app.processEvents()

        def click(column, control=False):
            QTest.mouseClick(
                self.header.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier if control else Qt.KeyboardModifier.NoModifier,
                QPoint(self.header.sectionViewportPosition(column) + 20, 10),
            )

        def rows():
            return [
                self.page.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
                for r in range(self.page.table.rowCount())
            ]

        click(1)
        click(5, True)
        self.assertEqual([col for col, order in self.page.table.sort_keys], [1, 5])
        self.assertEqual(rows(), [self.fourth, self.first, self.second, self.third])
        click(5, True)
        self.assertEqual(rows(), [self.fourth, self.third, self.second, self.first])
        click(1, True)
        self.assertEqual(rows(), [self.third, self.second, self.first, self.fourth])
        self.page.refresh()
        self.assertEqual(rows(), [self.third, self.second, self.first, self.fourth])
        click(0)
        self.assertEqual(len(self.page.table.sort_keys), 1)
