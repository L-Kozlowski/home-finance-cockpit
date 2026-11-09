"""Category color persistence and safe review of sorted transaction rows."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.reports import charts
from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.services.review import save_review
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analysis_summary import render_summary
from home_finance_cockpit.ui.common import selected_ids
from home_finance_cockpit.ui.main_window import FinanceApp


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "100", "PLN", "2026-01-01")
        self.root = self.db.save_category("Food")
        self.child = self.db.save_category("Groceries", parent_id=self.root)
        self.tx = self.db.save_transaction(self.wallet, "-10", self.child, "Shop", "2026-09-01")

    def test_default_inheritance_validation_and_clear(self):
        self.assertIsNone(self.db.category(self.root)["color"])
        self.db.set_category_color(self.root, "#79bcfa")
        self.assertEqual(self.db.category(self.child)["effective_color"], "#79BCFA")
        self.assertEqual(self.db.transactions()[0]["category_color"], "#79BCFA")
        for value in ("red", "#123", 123, "#GGGGGG"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.db.set_category_color(self.root, value)
        with self.assertRaises(ValueError):
            self.db.set_category_color(self.child, "#123456")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE categories SET color=? WHERE id=?", ("#123456", self.child))
        self.db.save_category("Food renamed", self.root)
        self.assertEqual(self.db.category(self.root)["color"], "#79BCFA")
        self.db.set_category_color(self.root, None)
        self.assertIsNone(self.db.transactions()[0]["category_color"])

    def test_review_metadata_changes_preserve_classification_and_amount(self):
        self.db.execute(
            "UPDATE transactions SET category_source='rule',category_conflict=1 WHERE id=?",
            (self.tx,),
        )
        before = dict(self.db.transactions()[0])
        save_review(
            self.db, self.tx, self.child, False, "#78DFC1", expected=before, expected_color=None
        )
        after = self.db.transactions()[0]
        for key in (
            "amount_minor",
            "date",
            "description",
            "category_source",
            "category_conflict",
            "raw_json",
            "import_id",
        ):
            self.assertEqual(after[key], before[key])
        self.assertFalse(after["include_in_reports"])
        save_review(self.db, self.tx, self.root, True, None, classify=True)
        after = self.db.transactions()[0]
        self.assertEqual(after["category_source"], "manual")
        self.assertFalse(after["category_conflict"])
        self.assertIsNone(after["matched_rule_id"])

    def test_stale_review_and_partial_failure_are_atomic(self):
        before = dict(self.db.transactions()[0])
        self.db.set_report_inclusion(self.tx, False)
        with self.assertRaises(ValueError):
            save_review(self.db, self.tx, self.root, True, "#78DFC1", expected=before)
        self.assertIsNone(self.db.category(self.root)["color"])
        with patch.object(self.db, "set_report_inclusion", side_effect=ValueError("failure")):
            with self.assertRaises(ValueError):
                save_review(self.db, self.tx, self.root, True, "#78DFC1")
        self.assertIsNone(self.db.category(self.root)["color"])
        self.assertEqual(self.db.transactions()[0]["category_id"], self.child)

    def test_stale_color_is_not_overwritten(self):
        self.db.set_category_color(self.root, "#79BCFA")
        with self.assertRaises(ValueError):
            save_review(self.db, self.tx, self.child, True, "#78DFC1", expected_color=None)
        self.assertEqual(self.db.category(self.root)["color"], "#79BCFA")

    def test_frozen_snapshot_and_live_and_export_charts_use_same_color(self):
        self.db.set_category_color(self.root, "#79BCFA")
        data = snapshot(self.db, ReportOptions(currency="PLN", exclude_recognized=False))
        chart_data = spending_snapshot(self.db, "PLN", after_refunds=False)
        self.db.set_category_color(self.root, "#78DFC1")
        figure = Figure()
        render_summary(figure, "categories", chart_data)
        self.assertEqual(to_hex(figure.axes[0].patches[0].get_facecolor()), "#79bcfa")
        captured = []

        def capture(figure, path):
            captured.append(figure)
            return path

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(charts, "_save", side_effect=capture),
        ):
            charts.monthly_charts(data["summaries"]["2026-09"], "PLN", Path(directory))
            charts.annual_charts(data, "2026", "PLN", Path(directory))
        for index in (0, 2, 4):
            self.assertEqual(to_hex(captured[index].axes[0].patches[0].get_facecolor()), "#79bcfa")

    def test_v4_upgrade_preserves_data_and_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("A", "10", "PLN", "2026-01-01", icon_name="bank")
            tx = db.save_transaction(wallet, "-1", db.default_category_id(), "Old", "2026-09-01")
            db.set_report_inclusion(tx, False)
            db.close()
            connection = sqlite3.connect(path)
            connection.execute("ALTER TABLE categories DROP COLUMN color")
            connection.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
            connection.execute("DROP TABLE savings_goals")
            connection.execute("DROP TABLE currency_rates")
            connection.execute("DROP TABLE exchange_settings")
            connection.execute("DROP TABLE IF EXISTS currency_history_requests")
            connection.execute("DROP TABLE IF EXISTS currency_rate_history")
            connection.execute("PRAGMA user_version=4")
            connection.commit()
            connection.close()
            db = Database.open_existing(path)
            try:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)
                self.assertIsNone(db.transactions()[0]["category_color"])
                self.assertFalse(db.transactions()[0]["include_in_reports"])
                self.assertEqual(db.wallet(wallet)["icon_name"], "bank")
                self.assertEqual(
                    len(list((Path(directory) / "backups").glob("before_v12_*.db"))), 1
                )
            finally:
                db.close()

    def test_pdf_preserves_explicit_category_color_in_table_icons(self):
        from home_finance_cockpit.reports.cockpit import CockpitReport

        self.db.set_category_color(self.root, "#79BCFA")
        data = snapshot(self.db, ReportOptions(currency="PLN", annual=False))
        with tempfile.TemporaryDirectory() as folder:
            report = CockpitReport(data, "2026-09", Path(folder) / "table.pdf")
            self.assertEqual(report.colors["Food"], "#79BCFA")
            report.new_page(2, "Categories")
            with patch.object(report, "glyph", wraps=report.glyph) as glyph:
                report.table(["Category", "Amount"], [["Food", "10.00"]], [2, 1], category_col=0)
                self.assertEqual(glyph.call_args.args[-1], "#79BCFA")
            report.canvas.save()


class TransactionWorkspaceTests(unittest.TestCase):
    def test_visible_totals_follow_search_quick_views_and_currency(self):
        self.db.save_transaction(self.wallet, "250", self.root, "Refund", "2026-09-03")
        self.window.refresh_ui()
        self.assertEqual((self.page.visible_income, self.page.visible_expense), (25000, 11000))
        self.page.search.setText("Shop")
        self.assertEqual((self.page.visible_income, self.page.visible_expense), (0, 1000))
        self.page.search.clear()
        self.page.set_mode("uncategorized")
        self.assertEqual((self.page.visible_income, self.page.visible_expense), (0, 10000))
        self.page.set_mode("all")
        self.page.search.setText("No matching rows")
        self.assertEqual((self.page.visible_income, self.page.visible_expense), (0, 0))

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        ColorTests.setUp(self)
        self.other = self.db.save_transaction(
            self.wallet, "-100", self.db.default_category_id(), "Other", "2026-09-02"
        )
        self.window = FinanceApp(self.db)
        self.page = self.window.transaction_page
        self.addCleanup(self.window.close)

    def row_for(self, transaction_id):
        return next(
            row
            for row in range(self.page.table.rowCount())
            if self.page.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == transaction_id
        )

    def test_numeric_sort_checkbox_and_selection_use_database_id(self):
        self.page.table.sortItems(5, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.page.table.item(0, 0).data(Qt.ItemDataRole.UserRole), self.other)
        self.page.table.item(0, 10).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.db.transactions(transaction_id=self.other)[0]["include_in_reports"])
        self.assertTrue(self.db.transactions(transaction_id=self.tx)[0]["include_in_reports"])
        self.page.table.selectRow(self.row_for(self.tx))
        self.page.show_details()
        self.assertEqual(self.page.inspector.transaction_id, self.tx)
        self.assertEqual(selected_ids(self.page.table), [self.tx])

    def test_quick_views_and_literal_search(self):
        self.page.set_mode("uncategorized")
        self.assertEqual([r["id"] for r in self.page.records], [self.other])
        self.page.set_mode("all")
        self.page.search.setText("Shop")
        self.assertEqual([r["id"] for r in self.page.records], [self.tx])
        self.db.execute("UPDATE transactions SET category_conflict=1 WHERE id=?", (self.tx,))
        self.page.set_mode("conflicts")
        self.assertEqual([r["id"] for r in self.page.records], [self.tx])
        self.assertIn("1", self.page.view_buttons["conflicts"].text())

    def test_inspector_draft_cancel_save_and_navigation_guard(self):
        self.page.table.selectRow(self.row_for(self.tx))
        self.page.show_details()
        editor = self.page.inspector
        editor.color.choose("#78DFC1")
        self.assertTrue(editor.dirty())
        self.assertIsNone(self.db.category(self.root)["color"])
        editor.reload()
        self.assertFalse(editor.dirty())
        editor.color.choose("#79BCFA")
        self.assertTrue(editor.save())
        self.assertEqual(self.db.category(self.root)["color"], "#79BCFA")
        editor.color.choose(None)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.page.table.selectRow(self.row_for(self.other))
            self.page.show_details()
            self.assertEqual(editor.transaction_id, self.tx)
            self.assertEqual(selected_ids(self.page.table), [self.tx])
            self.window.tabs.setCurrentIndex(1)
            self.window.tabs.setCurrentIndex(0)
            self.assertEqual(self.window.tabs.currentIndex(), 1)
        editor.reload()

    def test_details_start_hidden_and_selection_does_not_open_them(self):
        self.window.tabs.setCurrentIndex(1)
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.page.editor_scroll.isHidden())
        self.assertFalse(self.page.detail_button.isEnabled())
        self.page.table.selectRow(self.row_for(self.tx))
        self.assertTrue(self.page.editor_scroll.isHidden())
        self.assertIsNone(self.page.inspector.transaction_id)
        self.page.detail_button.click()
        self.assertFalse(self.page.editor_scroll.isHidden())
        self.assertEqual(self.page.inspector.transaction_id, self.tx)
        self.page.inspector.request_close()
        self.page.table.selectRow(self.row_for(self.other))
        self.assertTrue(self.page.editor_scroll.isHidden())
        self.page.table.cellDoubleClicked.emit(self.row_for(self.other), 7)
        self.assertFalse(self.page.editor_scroll.isHidden())
        self.assertEqual(self.page.inspector.transaction_id, self.other)

    def test_clear_selection_resets_total_without_changing_data(self):
        self.page.table.selectAll()
        self.assertTrue(self.page.clear_selection_button.isEnabled())
        self.page.clear_selection_button.click()
        self.assertEqual(selected_ids(self.page.table), [])
        self.assertFalse(self.page.clear_selection_button.isEnabled())
        self.assertEqual(self.page.selection_summary.text(), "")
        self.assertEqual(self.page.table.columnCount(), 13)
        self.assertEqual(self.page.table.horizontalHeader().visualIndex(0), 0)
        self.assertEqual(len(self.db.transactions()), 2)
        self.assertTrue(all(r["include_in_reports"] for r in self.db.transactions()))
        self.assertTrue(self.page.editor_scroll.isHidden())

    def test_click_updates_open_details_until_explicitly_closed(self):
        from PyQt6.QtTest import QTest

        self.window.tabs.setCurrentIndex(1)
        self.window.show()
        self.app.processEvents()

        def click(transaction_id, double=False):
            row = self.row_for(transaction_id)
            position = self.page.table.visualItemRect(self.page.table.item(row, 7)).center()
            action = QTest.mouseDClick if double else QTest.mouseClick
            action(self.page.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
            self.app.processEvents()

        click(self.tx)
        self.assertTrue(self.page.editor_scroll.isHidden())
        click(self.tx, double=True)
        self.assertFalse(self.page.editor_scroll.isHidden())
        self.assertEqual(self.page.inspector.transaction_id, self.tx)
        click(self.other)
        self.assertFalse(self.page.editor_scroll.isHidden())
        self.assertEqual(self.page.inspector.transaction_id, self.other)
        self.page.inspector.color.choose("#78DFC1")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            click(self.tx)
        self.assertEqual(self.page.inspector.transaction_id, self.other)
        self.assertTrue(self.page.inspector.dirty())
        self.page.inspector.reload()
        self.page.inspector.request_close()
        self.app.processEvents()
        click(self.tx)
        self.assertTrue(self.page.editor_scroll.isHidden())

    def test_clear_selection_caption_preserves_polish_characters(self):
        self.assertEqual(self.page.clear_selection_button.text(), "Wyczy\u015b\u0107 zaznaczenie")
