import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QToolButton

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.common import selected_ids
from home_finance_cockpit.ui.import_history import ImportHistoryPage


class ImportRegisterTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01", icon_name="bank")
        self.other = self.db.save_wallet("Cash", "0", "PLN", "2026-01-01", icon_name="cash")
        for index in range(18):
            self.db.execute(
                "INSERT INTO imports(wallet_id,file_name,file_hash,mapping_json,imported_at,row_count) VALUES(?,?,?,?,?,?)",
                (
                    self.wallet if index < 15 else self.other,
                    f"file_{index:02}.csv",
                    str(index),
                    "{}",
                    f"2026-10-{index + 1:02}T08:03:00",
                    index,
                ),
            )
        self.host = Mock()
        self.page = ImportHistoryPage(self.db, self.host)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh()

    def test_search_wallet_pagination_and_global_numeric_sort(self):
        page = self.page
        self.assertEqual(page.table.rowCount(), 11)
        page.change_page(1)
        self.assertEqual(page.table.rowCount(), 7)
        page.table.horizontalHeader().setSortIndicator(2, Qt.SortOrder.AscendingOrder)
        self.assertEqual(page.page, 0)
        self.assertEqual(page.table.item(0, 2).text(), "0")
        page.change_page(1)
        self.assertEqual(page.table.item(0, 2).text(), "11")
        page.search.setText("file_17")
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.page, 0)
        page.wallet.setCurrentIndex(page.wallet.findData(self.wallet))
        self.assertEqual(page.table.rowCount(), 0)
        page.search.clear()
        self.assertEqual(len(page.filtered), 15)

    def test_delete_button_targets_row_after_sort_and_selection(self):
        page = self.page
        page.table.selectRow(0)
        selected = selected_ids(page.table)[0]
        target = page.table.item(1, 0).data(Qt.ItemDataRole.UserRole)
        page.table.cellWidget(1, 4).findChild(QToolButton).click()
        self.host.delete_import_transactions.assert_called_once_with(target)
        self.assertNotEqual(selected, target)
        self.assertFalse(page.table.item(0, 1).icon().isNull())
        self.assertTrue(page.view.isEnabled())

    def test_change_import_wallet_moves_linked_transactions(self):
        row = next(
            i
            for i in range(self.page.table.rowCount())
            if self.page.table.item(i, 1).text() == "Main"
        )
        identifier = self.page.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        tx = self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "Imported",
            "2026-10-01",
            import_id=identifier,
            source_line=2,
        )
        self.page.table.selectRow(row)
        with patch(
            "home_finance_cockpit.ui.import_history.WalletDestinationDialog.exec",
            return_value=QDialog.DialogCode.Accepted,
        ):
            self.page.move_selected_import()
        self.assertEqual(self.db.transactions(transaction_id=tx)[0]["wallet_id"], self.other)
        self.assertEqual(
            next(r for r in self.db.import_history() if r["id"] == identifier)["wallet_id"],
            self.other,
        )
        self.host.refresh_ui.assert_called_once()

    def test_view_transactions_clears_unrelated_filters_and_scopes_import(self):
        from home_finance_cockpit.ui.main_window import FinanceApp

        window = FinanceApp(self.db)
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        import_id = self.db.import_history()[0]["id"]
        target = self.db.save_transaction(
            self.other,
            "-12.00",
            self.db.categories()[0]["id"],
            "Imported",
            "2026-10-02",
            source="bank",
            import_id=import_id,
            source_line=1,
        )
        self.db.save_transaction(
            self.other, "-24.00", self.db.categories()[0]["id"], "Manual", "2026-10-02"
        )
        window.refresh_ui()
        window.history_table.selectRow(0)
        window.transaction_search.setText("no match")
        window.transaction_filters.selected_category_ids = {9999}
        window.history_page.open_transactions()
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual([r["id"] for r in window.transactions], [target])
