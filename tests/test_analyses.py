"""Explicit refunds, exact costs, portable metadata and no-scroll chart navigation."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.reports.generator import generate_reports
from home_finance_cockpit.services.review import save_review
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analysis_summary import render_summary
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.scaling import px


class SpendingTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "100", "PLN", "2026-01-01")
        self.food = self.db.save_category("Food", color="#78DFC1")
        self.home = self.db.save_category("Home", color="#B9A0FA")
        self.db.save_transaction(self.wallet, "-100", self.food, "Previous", "2026-09-01")
        self.expense = self.tx("-3000", self.food, "Food")
        self.tx("-1800", self.home, "Home")
        self.refund = self.tx("600", self.food, "Refund", kind="refund")
        self.salary = self.tx("7500", self.home, "Salary", kind="salary")
        self.tx("100", self.food, "Unmarked income")
        self.tx("-1000", self.home, "Transfer out", kind="transfer")
        self.tx("1000", self.home, "Transfer in", kind="transfer")

    def tx(self, amount, category, description, kind="standard", day="2026-10-12"):
        return self.db.save_transaction(
            self.wallet, amount, category, description, day, "Receiver", analysis_kind=kind
        )

    def data(self, **kwargs):
        return spending_snapshot(self.db, "PLN", year=2026, month="2026-10", **kwargs)

    def test_only_explicit_refunds_reduce_costs_and_all_subtotals_agree(self):
        data = self.data()
        self.assertEqual((data["gross"], data["refunds"], data["cost"]), (480000, 60000, 420000))
        self.assertEqual(data["inflows"], 70000)
        self.assertEqual(data["categories"][self.food], 240000)
        for key in ("categories", "children", "daily", "merchants"):
            self.assertEqual(sum(data[key].values()), 420000)
        self.assertEqual(sum(data["weekday"]), 420000)
        self.assertEqual(self.data(omit_salary=False)["cost"], 420000)
        self.assertEqual(self.data(after_refunds=False)["cost"], 480000)

    def test_category_scope_filters_history_and_preserves_full_wallet_balance(self):
        from home_finance_cockpit.services.analysis import summarize

        child = self.db.save_category("Groceries", parent_id=self.food)
        self.tx("-10", child, "Child purchase")
        data = self.data(category_ids={self.food}, after_refunds=False)
        self.assertEqual(data["cost"], 301000)
        self.assertEqual(data["previous"]["cost"], 10000)
        self.assertEqual(self.data(category_ids={child}, after_refunds=False)["cost"], 1000)
        self.assertEqual(
            self.data(category_ids={self.food, self.home}, after_refunds=False)["cost"], 481000
        )
        complete = summarize(self.db, currency="PLN")
        scoped = summarize(self.db, currency="PLN", category_ids={child})
        self.assertEqual(scoped["expense"], 1000)
        self.assertEqual(scoped["balance"], complete["balance"])

    def test_refund_timing_unknown_category_and_exclusions(self):
        self.tx(
            "50",
            self.db.default_category_id(),
            "Unassigned refund",
            kind="reimbursement",
            day="2026-11-01",
        )
        october = self.data()
        november = spending_snapshot(self.db, "PLN", year=2026, month="2026-11")
        self.assertEqual(october["cost"], 420000)
        self.assertEqual(november["categories"][None], -5000)
        self.db.set_report_inclusion(self.refund, False)
        self.assertEqual(self.data()["cost"], 480000)
        self.assertEqual(november["cost"], -5000)

    def test_currency_wallet_scoping_and_balance_never_changes(self):
        before = self.db.wallet_balances()[0]["balance"]
        self.db.save_currency("EUR", "Euro")
        other = self.db.save_wallet("Other", "0", "EUR", "2026-01-01")
        self.db.save_transaction(other, "-99", self.food, "EUR", "2026-10-01")
        self.db.save_rate_config("EUR", "manual", "4.3")
        self.assertEqual(self.data()["cost"], 462570)
        self.data(after_refunds=False, omit_salary=False)
        self.assertEqual(
            next(w["balance"] for w in self.db.wallet_balances() if w["id"] == self.wallet), before
        )

    def test_kind_validation_and_atomic_review(self):
        for kind in ("salary", "refund", "reimbursement", "bad", []):
            with self.assertRaises(ValueError):
                self.db.set_analysis_kind(self.expense, kind)
        before = dict(self.db.transactions(transaction_id=self.expense)[0])
        with self.assertRaises(ValueError):
            save_review(
                self.db,
                self.expense,
                self.home,
                False,
                "#79BCFA",
                analysis_kind="refund",
                expected=before,
            )
        after = self.db.transactions(transaction_id=self.expense)[0]
        self.assertEqual(after["category_id"], self.food)
        self.assertTrue(after["include_in_reports"])
        self.assertEqual(self.db.category(self.home)["color"], "#B9A0FA")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE transactions SET analysis_kind='refund' WHERE id=?", (self.expense,)
            )

    def test_pdf_and_live_aggregation_have_identical_costs(self):
        live = self.data()
        report = snapshot(
            self.db, ReportOptions(currency="PLN", year=2026, after_refunds=True, omit_salary=True)
        )
        month = report["summaries"]["2026-10"]
        self.assertEqual(month["expenses"], live["cost"])
        self.assertEqual(month["gross_expenses"], live["gross"])
        self.assertEqual(month["refunds"], live["refunds"])
        self.assertEqual(month["net"], live["inflows"] - live["gross"])

    def test_summary_charts_render_and_use_category_colors(self):
        data = self.data()
        for after_refunds in (False, True):
            chart_data = self.data(after_refunds=after_refunds)
            for key in ("months", "categories"):
                figure = Figure(figsize=(7, 4))
                render_summary(figure, key, chart_data)
                self.assertTrue(figure.axes)
        figure = Figure()
        ax = render_summary(figure, "categories", data)
        self.assertIn("#78dfc1", [to_hex(p.get_facecolor()) for p in ax.patches])

    def test_missing_month_comparisons_do_not_invent_zeros(self):
        self.tx("-10", self.food, "Later", day="2026-12-01")
        data = spending_snapshot(self.db, "PLN", month="2026-12")
        self.assertIsNone(data["previous"])
        self.assertNotIn("2026-11", data["monthly"])

    def test_zero_and_negative_cost_pdfs_are_generated_without_fake_shares(self):
        self.tx("-10", self.food, "Cost", day="2027-01-01")
        self.tx("20", self.food, "Refund", kind="refund", day="2027-01-02")
        self.tx("-10", self.food, "Cost", day="2027-02-01")
        self.tx("10", self.food, "Refund", kind="refund", day="2027-02-02")
        data = snapshot(self.db, ReportOptions(currency="PLN", year=2027, after_refunds=True))
        self.assertEqual(data["summaries"]["2027-01"]["expenses"], -1000)
        self.assertEqual(data["summaries"]["2027-02"]["expenses"], 0)
        self.assertIsNone(data["summaries"]["2027-02"]["change_percent"])
        with tempfile.TemporaryDirectory() as directory:
            result = generate_reports(data, directory)
            self.assertEqual(len(result["pdfs"]), 3)
            self.assertTrue(all(p.read_bytes().startswith(b"%PDF-") for p in result["pdfs"]))


class KindMigrationTests(unittest.TestCase):
    def test_v5_migrates_with_backup_and_preserves_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("Main", "0", "PLN", "2026-01-01", icon_name="bank")
            tx = db.save_transaction(wallet, "-10", db.default_category_id(), "Old", "2026-10-01")
            db.set_report_inclusion(tx, False)
            db.close()
            with closing(sqlite3.connect(path)) as c:
                c.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
                c.execute("DROP TABLE savings_goals")
                c.execute("DROP TABLE currency_rates")
                c.execute("DROP TABLE exchange_settings")
                c.execute("DROP TABLE IF EXISTS currency_history_requests")
                c.execute("DROP TABLE IF EXISTS currency_rate_history")
                c.execute("PRAGMA user_version=5")
                c.commit()
            db = Database.open_existing(path)
            try:
                row = db.transactions()[0]
                self.assertEqual(
                    (
                        row["id"],
                        row["amount_minor"],
                        row["analysis_kind"],
                        row["include_in_reports"],
                    ),
                    (tx, -1000, "standard", 0),
                )
                self.assertEqual(db.wallet(wallet)["icon_name"], "bank")
                self.assertEqual(
                    len(list((Path(directory) / "backups").glob("before_v12_*.db"))), 1
                )
            finally:
                db.close()

    def test_failed_v5_migration_restores_old_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            Database.create_new(path).close()
            with closing(sqlite3.connect(path)) as c:
                c.execute("ALTER TABLE transactions DROP COLUMN analysis_kind")
                c.execute("DROP TABLE savings_goals")
                c.execute("DROP TABLE currency_rates")
                c.execute("DROP TABLE exchange_settings")
                c.execute("DROP TABLE IF EXISTS currency_history_requests")
                c.execute("DROP TABLE IF EXISTS currency_rate_history")
                c.execute("PRAGMA user_version=5")
                c.commit()
            original = Database.execute

            def fail(database, sql, params=()):
                if sql == "PRAGMA user_version=12":
                    raise sqlite3.OperationalError("failure")
                return original(database, sql, params)

            with (
                patch.object(Database, "execute", fail),
                self.assertRaises(sqlite3.OperationalError),
            ):
                Database.open_existing(path)
            with closing(sqlite3.connect(path)) as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertNotIn(
                    "analysis_kind", {r[1] for r in c.execute("PRAGMA table_info(transactions)")}
                )


class AnalysisUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(":memory:")
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        cat = self.db.default_category_id()
        self.tx = self.db.save_transaction(self.wallet, "-10", cat, "Expense", "2026-10-01")
        self.credit = self.db.save_transaction(
            self.wallet, "5", cat, "Refund", "2026-10-02", analysis_kind="refund"
        )
        self.window = FinanceApp(
            self.db,
            settings=QSettings(str(Path(self.temp.name) / "prefs.ini"), QSettings.Format.IniFormat),
        )
        self.addCleanup(self.dispose)
        self.view = self.window.analyses

    def dispose(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_six_tabs_use_gross_expenses_and_drilldown_preserves_exact_ids(self):
        self.view.refresh(force=True)
        self.assertEqual(self.view.tabs.count(), 6)
        self.assertEqual(self.view.data["cost"], 1000)
        self.view.open_rows([self.credit])
        self.assertEqual([r["id"] for r in self.window.transactions], [self.credit])
        self.window.transaction_page.clear_analysis_scope()
        self.assertEqual(len(self.window.transactions), 2)
        self.view.refresh(force=True)
        self.assertEqual(self.view.data["cost"], 1000)

    def test_pdf_button_copies_mode_scope_and_salary_option(self):
        self.view.refresh(force=True)
        self.view.open_pdf()
        options = self.window.report_generator.panel.options()
        self.assertFalse(options.after_refunds)
        self.assertTrue(options.omit_salary)
        self.assertEqual(options.currency, "PLN")

    def test_wide_and_compact_layout_do_not_need_vertical_chart_scrolling(self):
        self.window.resize(1600, 1000)
        self.window.show()
        self.window.tabs.setCurrentIndex(4)
        for _ in range(5):
            self.app.processEvents()
        self.assertTrue(self.view.summary_view.isVisible())
        self.view.tabs.setCurrentIndex(4)
        self.app.processEvents()
        self.assertTrue(self.view.counterparties.isVisible())
        self.assertFalse(hasattr(self.view, "mode"))
        self.assertFalse(hasattr(self.view, "omit_salary"))
        body = self.view.splitter.widget(1)
        self.assertLessEqual(self.view.counterparties.height(), body.height())
        self.window.resize(px(950), px(700))
        for _ in range(5):
            self.app.processEvents()
        self.assertFalse(hasattr(self.view, "chart_picker"))
        self.assertTrue(self.view.counterparties.isVisible())
