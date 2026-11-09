"""Exercise Qt widgets headlessly, without opening the user's database."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.category_workbench import CategoryManagerPage
from home_finance_cockpit.ui.currency_manager import CurrencyManagerPage
from home_finance_cockpit.ui.editors import (
    CategoryDialog,
    CurrencyDialog,
    RuleDialog,
    TransactionDialog,
    WalletDialog,
    select_data,
)
from home_finance_cockpit.ui.import_dialog import ImportDialog
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.theme import configure_application


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Test", "1000", "PLN", "2026-01-01")
        self.food = self.db.save_category("Food")

    def dispose(self, widget):
        widget.deleteLater()
        self.app.processEvents()

    def test_header_actions_are_limited_to_relevant_pages(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            self.assertEqual(not window.workspace.import_button.isHidden(), index in (0, 3))
            self.assertEqual(not window.workspace.add_button.isHidden(), index in (1, 2, 7))

    def test_category_export_is_left_of_import_in_shared_header(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        window.resize(1500, 900)
        window.tabs.setCurrentIndex(5)
        window.show()
        self.app.processEvents()
        page = window.category_page
        header = window.workspace.header_layout
        self.assertLess(header.indexOf(page.export_button), header.indexOf(page.import_button))
        self.assertEqual(page.export_button.geometry().top(), page.import_button.geometry().top())
        self.assertEqual(page.toolbar.indexOf(page.export_button), -1)
        self.assertFalse(page.export_button.isHidden())
        window.tabs.setCurrentIndex(0)
        self.assertTrue(page.export_button.isHidden())

    def test_import_window_is_nonmodal_reused_and_released_on_close(self):
        from PyQt6.QtCore import Qt

        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        window.show()
        window.import_csv()
        self.app.processEvents()
        dialog = window.import_dialog
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.isModal())
        self.assertEqual(dialog.windowModality(), Qt.WindowModality.NonModal)
        self.assertTrue(window.isEnabled())
        window.tabs.setCurrentIndex(1)
        self.assertEqual(window.tabs.currentIndex(), 1)
        window.import_csv()
        self.assertIs(window.import_dialog, dialog)
        dialog.reject()
        self.assertIsNone(window.import_dialog)

    def test_navigation_history_tracks_main_and_analytics_pages_and_branches(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        history = window.navigation_history
        self.assertFalse(window.workspace.back_button.isEnabled())
        window.tabs.setCurrentIndex(4)
        window.analyses.tabs.setCurrentIndex(2)
        window.tabs.setCurrentIndex(1)
        window.workspace.back_button.click()
        self.assertEqual((window.tabs.currentIndex(), window.analyses.tabs.currentIndex()), (4, 2))
        history.back()
        self.assertEqual(window.analyses.tabs.currentIndex(), 0)
        history.forward()
        self.assertEqual(window.analyses.tabs.currentIndex(), 2)
        window.tabs.setCurrentIndex(2)
        self.assertFalse(window.workspace.forward_button.isEnabled())
        history.back()
        self.assertEqual((window.tabs.currentIndex(), window.analyses.tabs.currentIndex()), (4, 2))

    def test_navigation_history_respects_unsaved_inspector_guard(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        window.tabs.setCurrentIndex(1)
        position = window.navigation_history.position
        with patch.object(window.transaction_page.inspector, "guard_pending", return_value=False):
            window.navigation_history.back()
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.navigation_history.position, position)

    def test_wallet_and_transaction_editors_roundtrip_spaced_amounts(self):
        wallet = WalletDialog(None, self.db, self.db.wallet(self.wallet))
        self.addCleanup(self.dispose, wallet)
        self.assertEqual(wallet.balance.text(), "1 000.00")
        wallet.balance.setText("12 000.50")
        wallet.persist()
        tx_id = self.db.save_transaction(
            self.wallet, "-2 000.25", self.food, "Expense", "2026-10-01"
        )
        record = next(t for t in self.db.transactions() if t["id"] == tx_id)
        editor = TransactionDialog(None, self.db, record)
        self.addCleanup(self.dispose, editor)
        self.assertEqual(editor.amount.text(), "2 000.25")
        editor.amount.setText("3 000.75")
        editor.persist()
        self.assertEqual(self.db.wallet(self.wallet)["opening_minor"], 1200050)
        self.assertEqual(self.db.transactions()[0]["amount_minor"], -300075)

    def test_main_window_refresh_after_changes_and_delete(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertEqual(window.dashboard.period(), (None, None))
        self.db.save_transaction(self.wallet, "-30", self.food, "test", "2026-10-01")
        window.refresh_ui()
        self.assertEqual(window.tx_table.rowCount(), 1)
        self.assertEqual(window.tx_table.item(0, 5).text(), "-30.00")
        self.assertIn("970.00", window.dashboard.cards[0].text())
        self.assertIn("30.00", window.dashboard.cards[2].text())
        window.tx_table.selectRow(0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window.delete_records("transactions", window.tx_table)
        self.assertEqual(window.tx_table.rowCount(), 0)
        self.assertFalse(hasattr(window.dashboard, "recent_table"))

    def test_import_history_delete_confirm_cancel_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            from home_finance_cockpit.services.importing import (
                commit_import,
                prepare_import,
                read_csv,
                suggested_mapping,
            )

            path = Path(tmp) / "batch.csv"
            path.write_text("Date,Amount\n2026-10-01,-10\n2026-10-02,-20\n", encoding="utf-8")
            file = read_csv(path)
            commit_import(
                self.db, prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
            )
        manual = self.db.save_transaction(self.wallet, "5", self.food, "manual", "2026-10-01")
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertTrue(window.history_table.cellWidget(0, 4).isEnabled())
        self.assertFalse(
            window.history_table.cellWidget(0, 4).findChild(QToolButton).icon().isNull()
        )
        self.assertEqual(window.history_table.item(0, 3).text(), "2")
        from home_finance_cockpit.ui.chart_dates import format_timestamp

        self.assertEqual(window.history_table.horizontalHeaderItem(5).text(), "Data importu")
        self.assertEqual(
            window.history_table.item(0, 5).text(),
            format_timestamp(self.db.import_history()[0]["imported_at"]),
        )
        self.assertNotIn("T", window.history_table.item(0, 5).text())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            window.history_table.cellWidget(0, 4).findChild(QToolButton).click()
        self.assertEqual(len(self.db.transactions()), 3)
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(QMessageBox, "information"),
        ):
            window.history_table.cellWidget(0, 4).findChild(QToolButton).click()
        self.assertEqual([r["id"] for r in self.db.transactions()], [manual])
        self.assertEqual(window.tx_table.rowCount(), 1)
        self.assertEqual(window.history_table.rowCount(), 0)
        self.assertIn("1 005.00", window.dashboard.cards[0].text())

    def test_chart_enlargement_has_independent_figure_and_working_zoom_history(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.db.save_transaction(self.wallet, "-30", self.food, "test", "2026-10-01")
        window.refresh_ui()
        QTest.mouseDClick(window.dashboard.canvases[0], Qt.MouseButton.LeftButton)
        self.assertEqual(len(window.dashboard.chart_windows), 1)
        dialog = window.dashboard.chart_windows[0]
        self.addCleanup(dialog.close)
        self.assertTrue(dialog.isVisible())
        self.assertIsNot(dialog.canvas.figure, window.dashboard.canvases[0].figure)
        self.assertEqual(dialog.data["balance"], 97000)
        axes = dialog.canvas.figure.axes[0]
        original_limits = axes.get_xlim()
        dialog.toolbar.push_current()
        axes.set_xlim(100, 200)
        dialog.toolbar.push_current()
        dialog.toolbar.home()
        self.assertEqual(axes.get_xlim(), original_limits)
        self.db.save_transaction(self.wallet, "-10", self.food, "new", "2026-10-01")
        window.refresh_ui()
        self.assertEqual(dialog.data["balance"], 97000)
        self.assertEqual(window.dashboard.chart_data["balance"], 96000)
        dialog.close()
        self.assertEqual(len(window.dashboard.chart_windows), 0)

    def test_trash_icon_targets_its_own_import_regardless_of_row_selection(self):
        from home_finance_cockpit.services.importing import (
            commit_import,
            prepare_import,
            read_csv,
            suggested_mapping,
        )

        with tempfile.TemporaryDirectory() as tmp:
            for name, amount in (("first.csv", "-10"), ("second.csv", "-20")):
                path = Path(tmp) / name
                path.write_text(f"Date,Amount\n2026-10-01,{amount}\n", encoding="utf-8")
                file = read_csv(path)
                commit_import(
                    self.db,
                    prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers)),
                )
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertEqual(window.history_table.item(0, 0).text(), "second.csv")
        window.history_table.selectRow(0)
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(QMessageBox, "information"),
        ):
            window.history_table.cellWidget(1, 4).findChild(QToolButton).click()
        self.assertEqual([row["amount_minor"] for row in self.db.transactions()], [-2000])
        self.assertTrue(window.history_table.cellWidget(0, 4).isEnabled())
        self.assertEqual(window.history_table.rowCount(), 1)
        self.assertEqual(window.history_table.item(0, 0).text(), "second.csv")

    def test_analytical_filters_can_collapse_and_restore(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        window.resize(1200, 850)
        window.show()
        for view in (window.dashboard, window.analyses):
            window.tabs.setCurrentWidget(view)
            self.app.processEvents()
            splitter = view.splitter
            splitter.setSizes([200, 500])
            self.app.processEvents()
            before = splitter.sizes()[1]
            splitter.setSizes([0, 700])
            self.app.processEvents()
            self.assertEqual(splitter.sizes()[0], 0)
            self.assertGreater(splitter.sizes()[1], before)
            splitter.setSizes([200, 500])
            self.assertGreater(splitter.sizes()[0], 0)

    def test_chart_double_click_and_close_with_main_window(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        QTest.mouseDClick(window.dashboard.canvases[1], Qt.MouseButton.LeftButton)
        self.assertEqual(len(window.dashboard.chart_windows), 1)
        window.close()
        self.assertEqual(len(window.dashboard.chart_windows), 0)

    def test_wallet_summary_default_and_currency_totals_share_displayed_balances(self):
        second = self.db.save_wallet("Other", "25.05", "PLN", "2026-01-01")
        self.db.save_currency("EUR", "€")
        self.db.save_wallet("Euro", "50.25", "EUR", "2026-01-01")
        self.db.save_transaction(self.wallet, "-1200.01", self.food, "", "2026-10-01")
        self.db.save_transaction(second, "5.10", self.food, "", "2026-10-01")
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertEqual(window.summary_mode.currentData(), "wallet")
        self.assertEqual(window.summary_table.rowCount(), 3)
        sidebar = {
            window.summary_table.item(row, 0).text(): window.summary_table.item(row, 1).text()
            for row in range(window.summary_table.rowCount())
        }
        wallets_tab = {
            window.wallet_table.item(row, 0).text(): window.wallet_table.item(row, 3).text()
            for row in range(window.wallet_table.rowCount())
        }
        self.assertEqual(sidebar, wallets_tab)
        self.assertEqual(sidebar["Test"], "-200.01")
        window.summary_mode.setCurrentIndex(1)
        totals = {
            window.summary_table.item(row, 0).text(): window.summary_table.item(row, 1).text()
            for row in range(window.summary_table.rowCount())
        }
        self.assertEqual(totals, {"EUR": "50.25", "PLN": "-169.86"})
        self.db.save_transaction(second, "1.01", self.food, "", "2026-10-01")
        window.refresh_ui()
        self.assertEqual(window.summary_mode.currentData(), "currency")
        self.assertEqual(window.summary_table.item(1, 1).text(), "-168.85")

    def test_file_menu_emits_database_selection_requests(self):
        from PyQt6.QtTest import QSignalSpy

        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        opened, created = (
            QSignalSpy(window.open_database_requested),
            QSignalSpy(window.new_database_requested),
        )
        menu = window.workspace.database_button.menu()
        self.assertTrue(window.menuBar().isHidden())
        from PyQt6.QtWidgets import QStatusBar

        from home_finance_cockpit.identity import APP_NAME

        self.assertEqual(window.windowTitle(), APP_NAME)
        self.assertFalse(window.findChildren(QStatusBar))
        self.assertTrue(window.workspace.subtitle.isHidden())
        menu.actions()[0].trigger()
        menu.actions()[1].trigger()
        self.assertEqual((len(opened), len(created)), (1, 1))
        window.workspace.report_button.click()
        self.assertIs(window.tabs.currentWidget(), window.report_generator)

    def test_all_dashboard_presets_and_invalid_custom_range(self):
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        dashboard = window.dashboard
        for index in range(dashboard.preset.count() - 1):
            dashboard.preset.setCurrentIndex(index)
            start, end = dashboard.period()
            if start:
                self.assertLessEqual(start, end)
        select_data(dashboard.preset, "custom")
        dashboard.start.setDate(QDate(2026, 10, 20))
        dashboard.end.setDate(QDate(2026, 10, 1))
        self.assertIn("późniejsza", dashboard.notice.text())
        dashboard.end.setDate(QDate(2026, 10, 30))
        self.assertEqual(dashboard.notice.text(), "")
        self.assertTrue(dashboard.notice.isHidden())

    def test_transaction_form_honors_type_and_manual_category(self):
        dialog = TransactionDialog(None, self.db)
        self.addCleanup(self.dispose, dialog)
        dialog.amount.setText("25,50")
        select_data(dialog.kind, -1)
        select_data(dialog.category, self.food)
        dialog.day.setDate(QDate(2026, 10, 1))
        dialog.description.setPlainText("groceries")
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        row = self.db.transactions()[0]
        self.assertEqual(
            (row["amount_minor"], row["category_id"], row["category_source"]),
            (-2550, self.food, "manual"),
        )
        edit = TransactionDialog(None, self.db, row)
        self.addCleanup(self.dispose, edit)
        edit.amount.setText("40")
        select_data(edit.kind, 1)
        edit.save()
        self.assertEqual(self.db.transactions()[0]["amount_minor"], 4000)
        self.assertEqual(len(self.db.transactions()), 1)

    def test_bad_form_stays_open_and_cancel_does_not_save(self):
        dialog = TransactionDialog(None, self.db)
        self.addCleanup(self.dispose, dialog)
        dialog.amount.setText("NaN")
        with patch("home_finance_cockpit.ui.common.QMessageBox.warning") as warning:
            dialog.save()
            warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertFalse(self.db.transactions())
        dialog.amount.setText("12")
        dialog.reject()
        self.assertFalse(self.db.transactions())

    def test_category_edit_does_not_change_wallet(self):
        self.db.save_transaction(
            self.wallet, "-10", self.db.default_category_id(), "a", "2026-10-01"
        )
        record = self.db.transactions()[0]
        dialog = TransactionDialog(None, self.db, record)
        self.addCleanup(self.dispose, dialog)
        select_data(dialog.category, self.food)
        dialog.save()
        row = self.db.transactions()[0]
        self.assertEqual((row["wallet_id"], row["category_id"]), (self.wallet, self.food))

    def test_rule_manager_applies_rules(self):
        self.db.save_rule(self.food, "description", "shop")
        self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "SHOP",
            "2026-10-01",
            source="unassigned",
        )
        dialog = CategoryManagerPage(None, self.db)
        self.addCleanup(self.dispose, dialog)
        self.assertEqual(dialog.rule_list.count(), 1)
        with patch.object(QMessageBox, "information"):
            dialog.run_rules()
        self.assertEqual(self.db.transactions()[0]["category_id"], self.food)

    def test_category_window_import_json_and_apply_to_history(self):
        self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "LIDL",
            "2026-10-01",
            source="unassigned",
        )
        dialog = CategoryManagerPage(None, self.db)
        self.addCleanup(self.dispose, dialog)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "categories.json"
            path.write_text('{"Details":{"Food":{"Grocery":["LIDL"]}}}', encoding="utf-8")
            with (
                patch(
                    "home_finance_cockpit.ui.category_actions.QFileDialog.getOpenFileName",
                    return_value=(str(path), ""),
                ),
                patch.object(QMessageBox, "information"),
                patch.object(
                    QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
                ) as ask,
            ):
                dialog.import_json()
                ask.assert_called_once()
        row = self.db.transactions()[0]
        self.assertEqual((row["category"], row["subcategory"]), ("Food", "Grocery"))
        self.assertEqual(dialog.rule_list.count(), 1)
        food = self.db.find_category("Food")
        for index in range(dialog.tree.topLevelItemCount()):
            node = dialog.tree.topLevelItem(index)
            if node.data(0, Qt.ItemDataRole.UserRole) == food["id"]:
                dialog.tree.setCurrentItem(node.child(0))
                break
        self.assertEqual(dialog.records[0]["subcategory"], "Grocery")
        self.assertEqual(dialog.records[0]["column_name"], "description")

    def test_category_import_can_skip_running_rules(self):
        tx = self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "LIDL",
            "2026-10-01",
            source="unassigned",
        )
        dialog = CategoryManagerPage(None, self.db)
        self.addCleanup(self.dispose, dialog)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "categories.json"
            path.write_text('{"Details":{"Food":{"Grocery":["LIDL"]}}}', encoding="utf-8")
            with (
                patch(
                    "home_finance_cockpit.ui.category_actions.QFileDialog.getOpenFileName",
                    return_value=(str(path), ""),
                ),
                patch.object(
                    QMessageBox, "question", return_value=QMessageBox.StandardButton.No
                ) as ask,
                patch.object(dialog, "run_rules") as run,
            ):
                dialog.import_json()
                ask.assert_called_once()
                run.assert_not_called()
        self.assertEqual(len(self.db.rules()), 1)
        self.assertEqual(
            self.db.transactions(transaction_id=tx)[0]["category_id"], self.db.default_category_id()
        )

    def test_subcategory_and_keyword_editors_save_selected_target(self):
        parent = self.db.find_category("Food")
        category = CategoryDialog(None, self.db, parent_id=parent["id"])
        self.addCleanup(self.dispose, category)
        category.name.setText("Grocery")
        category.save()
        child = self.db.find_category("Grocery", parent["id"])
        rule = RuleDialog(None, self.db, category_id=child["id"])
        self.addCleanup(self.dispose, rule)
        self.assertEqual(rule.column.currentData(), "description")
        rule.pattern.setText("LIDL")
        rule.save()
        record = self.db.rules()[0]
        edit = RuleDialog(None, self.db, record)
        self.addCleanup(self.dispose, edit)
        edit.pattern.setText("AUCHAN")
        select_data(edit.column, "from_to")
        select_data(edit.mode, "starts_with")
        edit.save()
        changed = self.db.rules()[0]
        self.assertEqual(
            (changed["pattern"], changed["column_name"], changed["mode"], changed["subcategory"]),
            ("AUCHAN", "from_to", "starts_with", "Grocery"),
        )

    def test_all_editors_create_records(self):
        category = CategoryDialog(None, self.db)
        category.name.setText("Travel")
        category.save()
        self.assertEqual(category.result(), QDialog.DialogCode.Accepted)
        currency = CurrencyDialog(None, self.db)
        currency.code.setText("EUR")
        currency.symbol.setText("€")
        currency.save()
        wallet = WalletDialog(None, self.db)
        wallet.name.setText("Euro")
        select_data(wallet.currency, "EUR")
        wallet.balance.setText("123,45")
        wallet.save()
        rule = RuleDialog(None, self.db)
        rule.pattern.setText("MARKET")
        rule.save()
        self.assertEqual(len(self.db.rules()), 1)
        self.assertEqual(len(self.db.wallets()), 2)
        for dialog in (category, currency, wallet, rule):
            self.dispose(dialog)

    def test_import_dialog_preview_save_history_and_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.csv"
            path.write_text(
                "Date,Amount,Description\n2026-10-01,-12.34,MARKET\n", encoding="utf-8-sig"
            )
            dialog = ImportDialog(None, self.db)
            self.addCleanup(self.dispose, dialog)
            with patch(
                "home_finance_cockpit.ui.import_dialog.QFileDialog.getOpenFileNames",
                return_value=([str(path)], ""),
            ):
                dialog.choose_file()
            dialog.validate()
            self.assertFalse(dialog.save_button.isEnabled())
            self.assertEqual(dialog.preview.item(0, 2).text(), "-12.34")
            select_data(dialog.fields["amount"], None)
            self.assertIsNone(dialog.plan)
            self.assertFalse(dialog.save_button.isEnabled())
            select_data(dialog.fields["amount"], "Amount")
            dialog.advance_step()
            dialog.advance_step()
            dialog.review_confirmation.setChecked(True)
            self.assertTrue(dialog.save_button.isEnabled())
            with patch.object(QMessageBox, "information"):
                dialog.save()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(self.db.execute("SELECT count(*) FROM imports").fetchone()[0], 1)

    def test_import_dialog_can_shrink_and_scroll_with_save_button_visible(self):
        dialog = ImportDialog(None, self.db)
        self.addCleanup(self.dispose, dialog)
        dialog.resize(520, 400)
        dialog.show()
        self.app.processEvents()
        self.assertLessEqual(dialog.height(), 400)
        self.assertLessEqual(dialog.width(), 520)
        scroll = dialog.source_scroll.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        scroll.setValue(scroll.maximum())
        self.app.processEvents()
        save_position = dialog.next_button.mapTo(dialog, dialog.next_button.rect().center())
        self.assertTrue(dialog.rect().contains(save_position))
        self.assertTrue(dialog.next_button.isVisible())
        self.assertTrue(dialog.content_scroll.viewport().isVisible())

    def test_import_uses_signed_amount_and_exposes_only_current_mapping_fields(self):
        dialog = ImportDialog(None, self.db)
        self.addCleanup(self.dispose, dialog)
        self.assertIn("*", dialog.field_labels["date"].text())
        self.assertIn("*", dialog.field_labels["amount"].text())
        self.assertFalse(hasattr(dialog, "mode"))
        for key in ("debit", "credit", "status", "external_id"):
            self.assertNotIn(key, dialog.fields)
        self.assertIn("tylko wtedy", dialog.fields["amount_fallback"].toolTip())
        self.assertIn("opcjonalne", dialog.fields["description"].toolTip())
        self.assertEqual(dialog.pages.count(), 3)

    def test_negative_wallet_balance_chart_and_empty_state(self):
        self.db.save_transaction(self.wallet, "-1200", self.food, "test", "2026-10-01")
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        for canvas in window.dashboard.canvases:
            canvas.draw()
        self.assertIn("-200.00", window.dashboard.cards[0].text())
        for page_type in (CategoryManagerPage, CurrencyManagerPage):
            dialog = page_type(None, self.db)
            self.dispose(dialog)


if __name__ == "__main__":
    unittest.main()
