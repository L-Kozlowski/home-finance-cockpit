"""Modal filter drafts and persistent wallet appearance."""

import os
from contextlib import closing

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.editors import WalletDialog
from home_finance_cockpit.ui.filters import FiltersDialog
from home_finance_cockpit.ui.icon_picker import WalletIconDialog
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.theme import configure_application


class WalletIconStorageTests(unittest.TestCase):
    def test_failed_icon_migration_restores_original_schema_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("Main", "100", "PLN", "2026-01-01")
            db.close()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("ALTER TABLE wallets DROP COLUMN icon_name")
                connection.execute("ALTER TABLE categories DROP COLUMN color")
                connection.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
                connection.execute("DROP TABLE savings_goals")
                connection.execute("DROP TABLE currency_rates")
                connection.execute("DROP TABLE exchange_settings")
                connection.execute("DROP TABLE IF EXISTS currency_history_requests")
                connection.execute("DROP TABLE IF EXISTS currency_rate_history")
                connection.execute("PRAGMA user_version=3")
                connection.commit()
            original_execute = Database.execute

            def fail_version_update(database, sql, params=()):
                if sql == "PRAGMA user_version=12":
                    raise sqlite3.OperationalError("Simulated migration failure")
                return original_execute(database, sql, params)

            with patch.object(Database, "execute", fail_version_update):
                with self.assertRaises(sqlite3.OperationalError):
                    Database.open_existing(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertNotIn(
                    "icon_name",
                    {row[1] for row in connection.execute("PRAGMA table_info(wallets)")},
                )
                self.assertNotIn(
                    "color", {row[1] for row in connection.execute("PRAGMA table_info(categories)")}
                )
                self.assertEqual(
                    connection.execute("SELECT id,opening_minor FROM wallets").fetchone(),
                    (wallet, 10000),
                )

    def test_icon_validation_default_and_preservation_on_unrelated_edit(self):
        db = Database(":memory:")
        self.addCleanup(db.close)
        wallet = db.save_wallet("A", "10", "PLN", "2026-01-01")
        self.assertEqual(db.wallet(wallet)["icon_name"], "wallet")
        db.save_wallet("A", "10", "PLN", "2026-01-01", wallet, icon_name="bank")
        db.save_wallet("Renamed", "20", "PLN", "2026-01-01", wallet)
        self.assertEqual(db.wallet(wallet)["icon_name"], "bank")
        for invalid in ("", "not-supported", 12):
            with self.assertRaises(ValueError):
                db.save_wallet("Invalid", "20", "PLN", "2026-01-01", wallet, icon_name=invalid)
        self.assertEqual(db.wallet(wallet)["name"], "Renamed")

    def test_v3_upgrade_preserves_ids_amounts_and_report_choices_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("Main", "100", "PLN", "2026-01-01")
            transaction = db.save_transaction(
                wallet, "-10", db.default_category_id(), "Example", "2026-10-01"
            )
            db.set_report_inclusion(transaction, False)
            db.close()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("ALTER TABLE wallets DROP COLUMN icon_name")
                connection.execute("ALTER TABLE categories DROP COLUMN color")
                connection.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
                connection.execute("DROP TABLE savings_goals")
                connection.execute("DROP TABLE currency_rates")
                connection.execute("DROP TABLE exchange_settings")
                connection.execute("DROP TABLE IF EXISTS currency_history_requests")
                connection.execute("DROP TABLE IF EXISTS currency_rate_history")
                connection.execute("PRAGMA user_version=3")
                connection.commit()
            db = Database.open_existing(path)
            self.assertEqual(db.wallet(wallet)["icon_name"], "wallet")
            self.assertEqual(db.transactions()[0]["id"], transaction)
            self.assertEqual(db.transactions()[0]["include_in_reports"], 0)
            self.assertEqual(db.wallet_balances()[0]["balance"], 9000)
            backup = next((Path(directory) / "backups").glob("before_v12_*.db"))
            with closing(sqlite3.connect(backup)) as original:
                self.assertEqual(original.execute("PRAGMA user_version").fetchone()[0], 3)
            db.save_wallet("Main", "100", "PLN", "2026-01-01", wallet, icon_name="cash")
            db.close()
            db = Database.open_existing(path)
            self.assertEqual(db.wallet(wallet)["icon_name"], "cash")
            db.close()


class FilterDialogTests(unittest.TestCase):
    def test_tree_selection_includes_children_and_can_select_one_child(self):
        root = self.db.save_category("Food")
        child = self.db.save_category("Grocery", parent_id=root)
        second = self.db.save_category("Restaurant", parent_id=root)
        dialog = FiltersDialog(self.window, transactions=True)
        self.addCleanup(dialog.deleteLater)
        nodes = {item.data(Qt.ItemDataRole.UserRole): item for item in dialog.categories.items}
        nodes[root].setCheckState(Qt.CheckState.Checked)
        self.assertEqual(nodes[child].checkState(), Qt.CheckState.Checked)
        dialog.apply()
        self.assertEqual(self.window.transaction_filters.selected_category_ids, {root})
        nodes[second].setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(nodes[root].checkState(), Qt.CheckState.PartiallyChecked)
        dialog.apply()
        self.assertEqual(self.window.transaction_filters.selected_category_ids, {child})
        dialog.category_search.setText("grocery")
        self.assertFalse(nodes[root].isHidden())
        self.assertTrue(nodes[second].isHidden())

    def test_analytics_custom_dates_are_draft_until_applied(self):
        owner = self.window.analyses
        owner.refresh(force=True)
        dialog = FiltersDialog(owner)
        self.addCleanup(dialog.deleteLater)
        dialog.choose_period("custom")
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 10, 31))
        self.assertEqual(owner.preset.currentData(), "all")
        dialog.apply()
        owner.refresh(force=True)
        self.assertEqual(owner.data["expenses"], 2000)
        self.assertEqual(owner.data["months"], ["2026-10"])

    def test_category_checks_apply_together_and_reset_restores_rows(self):
        other = self.db.save_category("Other category")
        self.db.save_transaction(self.wallet, "-5", other, "Other", "2026-10-03")
        self.window.refresh_ui()
        dialog = FiltersDialog(self.window, transactions=True)
        self.addCleanup(dialog.deleteLater)
        for i in range(dialog.categories.count()):
            item = dialog.categories.item(i)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.data(Qt.ItemDataRole.UserRole) == other
                else Qt.CheckState.Unchecked
            )
        self.assertEqual(len(self.window.transactions), 3)
        dialog.apply()
        self.assertEqual([r["description"] for r in self.window.transactions], ["Other"])
        dialog.reset_filters()
        dialog.apply()
        self.assertEqual(len(self.window.transactions), 3)

    def test_transaction_filters_match_overview_periods_and_combine_dates_with_search(self):
        dialog = FiltersDialog(self.window, transactions=True)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(
            set(dialog.fields),
            {"currency", "wallet", "preset", "start", "end", "amount_min", "amount_max"},
        )
        overview = self.window.dashboard
        self.assertEqual(
            [dialog.preset.itemData(i) for i in range(dialog.preset.count())],
            [overview.preset.itemData(i) for i in range(overview.preset.count())],
        )
        dialog.preset.setCurrentIndex(dialog.preset.findData("custom"))
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 10, 31))
        self.window.transaction_search.setText("Example")
        dialog.accept()
        dialog.apply()
        self.assertEqual(self.window.tx_table.rowCount(), 1)
        self.assertEqual(self.window.tx_table.item(0, 5).text(), "-20.00")
        self.assertIn("2026-10-31", self.window.transaction_wallet_summary.text())
        self.window.refresh_ui()
        self.assertEqual(self.window.tx_table.rowCount(), 1)
        self.assertEqual(self.window.transaction_search.text(), "Example")
        canceled = FiltersDialog(self.window, transactions=True)
        self.addCleanup(canceled.deleteLater)
        canceled.currency.setCurrentIndex(canceled.currency.findData("EUR"))
        canceled.reject()
        self.assertEqual(self.window.transaction_filters.currency.currentData(), "PLN")
        self.assertEqual(self.window.tx_table.rowCount(), 1)
        dialog.reset_filters()
        dialog.apply()
        self.assertEqual(self.window.tx_table.rowCount(), 2)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.db.save_currency("EUR", "Euro")
        self.db.save_rate_config("EUR", "manual", "4.30")
        self.euro = self.db.save_wallet("Euro", "250", "EUR", "2026-01-01", icon_name="travel")
        for day, amount in (("2026-09-01", "-10"), ("2026-10-02", "-20")):
            self.db.save_transaction(
                self.wallet, amount, self.db.default_category_id(), "Example", day
            )
        self.window = FinanceApp(self.db)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.dashboard.close_chart_windows()
        self.window.analyses.close_chart_windows()
        self.window.deleteLater()
        self.app.processEvents()

    def test_cancel_keeps_scope_and_apply_updates_currency_and_wallet_together(self):
        owner = self.window.dashboard
        dialog = FiltersDialog(owner)
        self.addCleanup(dialog.deleteLater)
        dialog.currency.setCurrentIndex(dialog.currency.findData("EUR"))
        self.assertEqual(dialog.wallet.itemData(1), self.euro)
        dialog.wallet.setCurrentIndex(1)
        dialog.reject()
        self.assertEqual(owner.currency.currentData(), "PLN")
        self.assertEqual(owner.chart_data["balance"], 204500)
        dialog.accept()
        dialog.apply()
        self.assertEqual(owner.currency.currentData(), "EUR")
        self.assertEqual(owner.wallet.currentData(), self.euro)
        self.assertEqual(owner.chart_data["balance"], 25000)
        self.assertIn("EUR", owner.filter_summary.text())

    def test_invalid_custom_range_stays_open_and_valid_range_filters_transactions(self):
        owner = self.window.dashboard
        dialog = FiltersDialog(owner)
        self.addCleanup(dialog.deleteLater)
        dialog.preset.setCurrentIndex(dialog.preset.findData("custom"))
        dialog.start.setDate(QDate(2026, 10, 31))
        dialog.end.setDate(QDate(2026, 10, 1))
        with patch("home_finance_cockpit.ui.filters.show_error") as error:
            dialog.accept()
        error.assert_called_once()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(owner.preset.currentData(), "all")
        dialog.start.setDate(QDate(2026, 10, 1))
        dialog.end.setDate(QDate(2026, 10, 31))
        dialog.accept()
        dialog.apply()
        self.assertEqual(owner.chart_data["count"], 1)
        self.assertEqual(owner.chart_data["expense"], 2000)
        self.assertIn("2026-10-31", owner.filter_summary.text())

    def test_report_month_and_transaction_wallet_filter_use_modal_selection(self):
        owner = self.window.analyses
        dialog = FiltersDialog(owner)
        self.addCleanup(dialog.deleteLater)
        dialog.month.setCurrentIndex(dialog.month.findData("2026-09"))
        dialog.accept()
        dialog.apply()
        owner.refresh(force=True)
        self.assertEqual(owner.data["expenses"], 1000)
        transaction_dialog = FiltersDialog(self.window, transactions=True)
        self.addCleanup(transaction_dialog.deleteLater)
        transaction_dialog.currency.setCurrentIndex(transaction_dialog.currency.findData("EUR"))
        transaction_dialog.wallet.setCurrentIndex(transaction_dialog.wallet.findData(self.euro))
        transaction_dialog.accept()
        transaction_dialog.apply()
        self.assertEqual(self.window.tx_table.rowCount(), 0)
        self.assertIn("Euro", self.window.transaction_wallet_summary.text())

    def test_overview_has_two_charts_and_four_icons_without_recent_transactions(self):
        owner = self.window.dashboard
        self.assertEqual(len(owner.canvases), 2)
        self.assertEqual(owner.chart_indices, (0, 2))
        self.assertEqual(len(owner.body_widgets), 4)
        self.assertFalse(hasattr(owner, "recent_table"))
        self.assertTrue(
            all(card.glyph is not None and not card.glyph.isNull() for card in owner.cards)
        )
        self.assertTrue(owner.filter_fields.isHidden())

    def test_icon_picker_and_wallet_editor_keep_cancel_local_until_saved(self):
        editor = WalletDialog(self.window, self.db, self.db.wallet(self.wallet))
        self.addCleanup(editor.deleteLater)
        picker = WalletIconDialog(editor, "wallet")
        self.addCleanup(picker.deleteLater)
        picker.show()
        QTest.mouseClick(picker.buttons["savings"], Qt.MouseButton.LeftButton)
        self.assertEqual(picker.selected_icon, "savings")
        self.assertEqual(sum(button.isChecked() for button in picker.buttons.values()), 1)
        picker.reject()
        self.assertEqual(editor.icon_name, "wallet")
        editor.icon_name = "bank"
        self.assertEqual(self.db.wallet(self.wallet)["icon_name"], "wallet")
        editor.persist()
        self.assertEqual(self.db.wallet(self.wallet)["icon_name"], "bank")
        self.window.refresh_ui()
        self.assertFalse(self.window.wallet_table.item(1, 0).icon().isNull())


if __name__ == "__main__":
    unittest.main()
