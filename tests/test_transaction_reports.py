"""Search, persistent report inclusion and live report visualizations."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.services.analysis import summarize
from home_finance_cockpit.services.importing import (
    commit_import,
    prepare_import,
    read_csv,
    suggested_mapping,
)
from home_finance_cockpit.services.search import search_transactions
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analyses import AnalysesTab
from home_finance_cockpit.ui.main_window import FinanceApp


class TransactionReportCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.food = self.db.save_category("Food")

    def tx(self, amount="-10", day="2026-09-01", description="Żabka market"):
        return self.db.save_transaction(
            self.wallet, amount, self.food, description, day, "Counterparty"
        )


class ReportInclusionTests(TransactionReportCase):
    def test_default_edit_and_reimport_preserve_inclusion(self):
        transaction = self.tx()
        self.assertEqual(self.db.transactions()[0]["include_in_reports"], 1)
        self.db.set_report_inclusion(transaction, False)
        self.db.save_transaction(
            self.wallet, "-20", self.food, "Changed", "2026-09-01", transaction_id=transaction
        )
        self.assertEqual(self.db.transactions()[0]["include_in_reports"], 0)
        path = Path(self.temp.name) / "source.csv"
        path.write_text("Date,Amount,Description\n2026-09-02,-30,Shop\n", encoding="utf-8")
        file = read_csv(path)
        plan = prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
        commit_import(self.db, plan)
        imported = next(r for r in self.db.transactions() if r["import_id"] is not None)
        self.assertEqual(imported["include_in_reports"], 1)
        self.db.set_report_inclusion(imported["id"], False)
        self.assertEqual(commit_import(self.db, plan), 0)
        self.assertFalse(any(r["include_in_reports"] for r in self.db.transactions()))

    def test_inclusion_changes_reports_but_never_wallet_balances(self):
        included = self.tx("-10")
        excluded = self.tx("-20")
        self.db.set_report_inclusion(excluded, False)
        data = snapshot(self.db, ReportOptions(currency="PLN", exclude_recognized=False))
        summary = data["summaries"]["2026-09"]
        self.assertEqual(summary["expenses"], 1000)
        self.assertEqual(summary["user_excluded_count"], 1)
        self.assertEqual([r["id"] for r in summary["rows"]], [included])
        self.assertEqual(summarize(self.db)["balance"], 97000)

    def test_all_excluded_period_is_not_used_as_zero_comparison(self):
        self.db.set_report_inclusion(self.tx("-10", "2026-08-01"), False)
        self.tx("-20", "2026-09-01")
        data = snapshot(self.db, ReportOptions(currency="PLN"))
        self.assertEqual(data["annual_months"], ("2026-09",))
        self.assertIsNone(data["summaries"]["2026-09"]["change"])
        self.db.set_report_inclusion(self.db.transactions()[0]["id"], False)
        with self.assertRaises(ValueError):
            snapshot(self.db, ReportOptions(currency="PLN"))

    def test_invalid_inclusion_values_are_rejected(self):
        transaction = self.tx()
        with self.assertRaises(ValueError):
            self.db.set_report_inclusion(transaction, "false")
        with self.assertRaises(ValueError):
            self.db.set_report_inclusion(999, False)

    def test_search_is_literal_accent_insensitive_and_supports_amount_date_category(self):
        first = self.tx("-1234.56", description="Żabka a.b")
        self.tx("-20", day="2026-10-01", description="Other axb")
        rows = self.db.transactions()
        for query in ("zabka", "ŻABKA", "1234,56", "2026-09 Food", "a.b", "zabka Main PLN"):
            with self.subTest(query=query):
                self.assertEqual([r["id"] for r in search_transactions(rows, query)], [first])
        self.assertEqual(len(search_transactions(rows, "")), 2)
        self.assertEqual(search_transactions(rows, "no such merchant"), [])


class InclusionMigrationTests(unittest.TestCase):
    def test_v2_upgrade_preserves_transactions_and_persists_user_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("A", "0", "PLN", "2026-01-01")
            transaction = db.save_transaction(
                wallet, "-10", db.default_category_id(), "old", "2026-09-01"
            )
            db.close()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("ALTER TABLE transactions DROP COLUMN include_in_reports")
                connection.execute("ALTER TABLE wallets DROP COLUMN icon_name")
                connection.execute("ALTER TABLE categories DROP COLUMN color")
                connection.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
                connection.execute("DROP TABLE savings_goals")
                connection.execute("DROP TABLE currency_rates")
                connection.execute("DROP TABLE exchange_settings")
                connection.execute("DROP TABLE IF EXISTS currency_history_requests")
                connection.execute("DROP TABLE IF EXISTS currency_rate_history")
                connection.execute("PRAGMA user_version=2")
                connection.commit()
            db = Database.open_existing(path)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)
            self.assertEqual(
                (db.transactions()[0]["id"], db.transactions()[0]["include_in_reports"]),
                (transaction, 1),
            )
            self.assertEqual(len(list((Path(tmp) / "backups").glob("before_v12_*.db"))), 1)
            db.set_report_inclusion(transaction, False)
            db.close()
            db = Database.open_existing(path)
            self.assertEqual(db.transactions()[0]["include_in_reports"], 0)
            db.close()


class TransactionReportUITests(TransactionReportCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dispose(self, window):
        if window.report_generator is not None:
            window.report_generator.close()
        window.dashboard.close_chart_windows()
        window.analyses.close_chart_windows()
        window.deleteLater()
        self.app.processEvents()

    def test_search_updates_table_and_checkbox_targets_filtered_transaction(self):
        target = self.tx("-10", description="Żabka")
        other = self.tx("-20", description="Other")
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertEqual(window.tx_table.rowCount(), 2)
        window.transaction_search.setText("zabka")
        self.assertEqual(window.tx_table.rowCount(), 1)
        self.assertEqual(window.transaction_count.text(), "1 / 2")
        checkbox = window.tx_table.item(0, 10)
        self.assertEqual(checkbox.checkState(), Qt.CheckState.Checked)
        checkbox.setCheckState(Qt.CheckState.Unchecked)
        records = {r["id"]: r for r in self.db.transactions()}
        self.assertEqual(records[target]["include_in_reports"], 0)
        self.assertEqual(records[other]["include_in_reports"], 1)
        window.refresh_ui()
        self.assertEqual(window.transaction_search.text(), "zabka")
        self.assertEqual(window.tx_table.item(0, 10).checkState(), Qt.CheckState.Unchecked)
        window.transaction_search.clear()
        self.assertEqual(window.tx_table.rowCount(), 2)

    def test_visualizations_use_report_flags_and_generate_no_files(self):
        self.tx("-10", day="2026-09-01")
        excluded = self.tx("-20", day="2026-10-01")
        self.db.set_report_inclusion(excluded, False)
        tab = AnalysesTab(self.db)
        self.addCleanup(tab.deleteLater)
        with (
            patch("home_finance_cockpit.ui.reports.generate_reports") as generate,
            patch("matplotlib.figure.Figure.savefig") as save,
        ):
            tab.refresh(force=True)
            self.assertEqual(tab.data["expenses"], 1000)
            self.assertEqual(len(tab.summary_view.canvases), 2)
            for canvas in tab.summary_view.canvases:
                self.assertTrue(canvas.figure.axes)
            generate.assert_not_called()
            save.assert_not_called()
        tab.summary_view.enlarge("months")
        self.assertEqual(len(tab.chart_windows), 1)
        tab.close_chart_windows()

    def test_pdf_configuration_is_an_embedded_reusable_page(self):
        self.tx()
        window = FinanceApp(self.db)
        self.addCleanup(self.dispose, window)
        self.assertIsNotNone(window.report_generator)
        self.assertIsInstance(window.analyses, AnalysesTab)
        window.show_report_generator()
        dialog = window.report_generator
        self.assertFalse(dialog.isWindow())
        self.assertEqual(window.tabs.currentWidget(), dialog)
        self.assertEqual(window.tabs.indexOf(dialog.panel), -1)
        window.tabs.setCurrentIndex(0)
        window.show_report_generator()
        self.assertIs(window.report_generator, dialog)
        self.assertEqual(window.tabs.currentWidget(), dialog)
