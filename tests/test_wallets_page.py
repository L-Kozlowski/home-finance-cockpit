"""Wallet scope, sorted actions and ledger history use stable database IDs."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QMenu

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.common import selected_ids
from home_finance_cockpit.ui.main_window import FinanceApp


class WalletPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(":memory:")
        self.main = self.db.save_wallet("Główny", "100", "PLN", "2026-01-01", icon_name="bank")
        self.cash = self.db.save_wallet("Gotówka", "0", "PLN", "2026-01-01", icon_name="cash")
        self.db.save_currency("EUR", "Euro")
        self.eur = self.db.save_wallet("Euro", "50", "EUR", "2026-01-01")
        cat = self.db.default_category_id()
        self.tx = self.db.save_transaction(self.main, "-150", cat, "Shop", "2026-09-01")
        self.db.save_transaction(self.main, "20", cat, "Refund", "2026-10-01")
        self.db.save_transaction(self.cash, "9", cat, "Cash", "2026-09-02")
        self.window = FinanceApp(
            self.db,
            settings=QSettings(str(Path(self.temp.name) / "prefs.ini"), QSettings.Format.IniFormat),
        )
        self.page = self.window.wallet_page
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def select(self, wallet_id):
        row = next(
            r
            for r in range(self.page.table.rowCount())
            if self.page.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == wallet_id
        )
        self.page.table.setCurrentCell(row, 0)
        self.page.table.selectRow(row)
        return row

    def test_move_wallet_updates_table_choices_and_preserves_selection(self):
        self.select(self.cash)
        self.page.move_up.click()
        expected = [self.cash, self.main, self.eur]
        self.assertEqual([w["id"] for w in self.db.wallets()], expected)
        self.assertEqual([w["id"] for w in self.db.wallet_balances()], expected)
        self.assertEqual(
            [self.page.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(3)], expected
        )
        self.assertEqual(selected_ids(self.page.table), [self.cash])
        self.assertFalse(self.page.move_up.isEnabled())
        self.page.move_down.click()
        self.assertEqual([w["id"] for w in self.db.wallets()], [self.main, self.cash, self.eur])

    def test_v9_migration_order_persists_after_reopening(self):
        path = Path(self.temp.name) / "order.db"
        db = Database.create_new(path)
        z = db.save_wallet("Zulu", "0", "PLN", "2026-01-01")
        a = db.save_wallet("Alpha", "0", "PLN", "2026-01-01")
        with db.transaction():
            db.execute("ALTER TABLE wallets DROP COLUMN sort_order")
            db.execute("DROP TABLE IF EXISTS currency_history_requests")
            db.execute("DROP TABLE IF EXISTS currency_rate_history")
            db.execute("PRAGMA user_version=9")
        db.close()
        db = Database.open_existing(path)
        try:
            self.assertEqual([w["id"] for w in db.wallets()], [a, z])
            db.move_wallet(z, -1)
        finally:
            db.close()
        db = Database.open_existing(path)
        try:
            self.assertEqual([w["id"] for w in db.wallets()], [z, a])
            self.assertEqual(db.wallet(z)["opening_minor"], 0)
            self.assertTrue(list((path.parent / "backups").glob("before_v12_*.db")))
        finally:
            db.close()

    def test_currency_totals_are_separate_and_filter_and_search_do_not_change_them(self):
        self.assertEqual({w["currency"] for w in self.page.records}, {"PLN", "EUR"})
        summary = self.page.summary.text()
        self.assertIn("-21.00 PLN", summary)
        self.assertIn("50.00 EUR", summary)
        self.page.currency.setCurrentIndex(self.page.currency.findData("PLN"))
        self.page.search.setText("glowny")
        self.assertEqual(list(self.page.visible), [self.main])
        self.assertEqual(self.page.summary.text(), summary)
        self.page.search.setText("nothing")
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertFalse(self.page.transactions_button.isEnabled())
        self.assertIsNone(self.page.chart_data)

    def test_sort_is_numeric_and_selection_survives_refresh(self):
        self.page.table.sortItems(3, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.page.table.item(0, 0).data(Qt.ItemDataRole.UserRole), self.main)
        self.select(self.eur)
        self.window.refresh_ui()
        self.assertEqual(selected_ids(self.page.table), [self.eur])
        self.assertEqual(self.page.chart_data["currency"], "EUR")
        self.assertEqual(self.page.chart_data["balance"], 5000)

    def test_history_has_prior_balance_and_ignores_report_exclusion(self):
        self.db.set_report_inclusion(self.tx, False)
        self.window.refresh_ui()
        self.select(self.main)
        self.page.set_period("1m")
        self.assertEqual(self.page.chart_data["balance"], -3000)
        self.assertEqual(self.page.chart_data["balance_trend"][-1][1], -3000)
        self.page.set_period("all")
        self.assertIn(("2026-01-01", 10000), self.page.chart_data["balance_trend"])
        self.assertIn(("2026-09-01", -5000), self.page.chart_data["balance_trend"])

    def test_open_transactions_resets_stale_scope_for_selected_wallet(self):
        self.window.transaction_search.setText("no match")
        self.window.transaction_page.set_mode("conflicts")
        self.window.transaction_filters.preset.setCurrentIndex(
            self.window.transaction_filters.preset.findData("today")
        )
        self.select(self.main)
        self.page.open_transactions()
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertEqual(self.window.wallet_filter.currentData(), self.main)
        self.assertEqual(len(self.window.transactions), 2)
        self.assertEqual(self.window.transaction_page.mode, "all")
        self.assertEqual(self.window.transaction_search.text(), "")
        self.assertEqual(self.window.transaction_filters.preset.currentData(), "all")

    def test_context_action_targets_sorted_wallet_id(self):
        self.page.table.sortItems(3, Qt.SortOrder.DescendingOrder)
        row = self.select(self.main)
        with patch.object(QMenu, "exec", return_value=None):
            self.page.actions_menu(self.eur, self.page.table.cellWidget(row, 7))
        self.assertEqual(selected_ids(self.page.table), [self.eur])

    def test_import_and_header_add_use_wallet_context(self):
        self.window.tabs.setCurrentIndex(2)
        self.select(self.eur)
        self.window.import_csv()
        self.assertEqual(self.window.import_dialog.wallet.currentData(), self.eur)
        self.window.import_dialog.reject()
        self.assertEqual(self.window.workspace.add_button.text(), "Dodaj portfel")
        with patch(
            "home_finance_cockpit.ui.main_window.WalletDialog.exec", return_value=0
        ) as opened:
            self.window.workspace.add_button.click()
        opened.assert_called_once()

    def test_chart_window_keeps_snapshot_and_deleted_wallet_is_not_left_selected(self):
        self.select(self.main)
        self.page.enlarge_chart()
        dialog = self.page.chart_windows[0]
        self.db.save_transaction(
            self.main, "1", self.db.default_category_id(), "Later", "2026-10-02"
        )
        self.window.refresh_ui()
        self.assertEqual(dialog.data["balance"], -3000)
        self.assertEqual(self.page.chart_data["balance"], -2900)
        empty = self.db.save_wallet("Empty", "0", "PLN", "2026-01-01")
        self.window.refresh_ui()
        self.select(empty)
        self.db.delete("wallets", [empty])
        self.window.refresh_ui()
        self.assertNotEqual(self.page.selected_wallet()["id"], empty)
        self.page.close_chart_windows()
