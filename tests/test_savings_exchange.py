"""Savings allocations, schema upgrade, API failures and scheduled FX updates."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtCore import QByteArray, QCoreApplication, QEvent, QObject, QSettings, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QApplication, QProgressBar, QPushButton

from home_finance_cockpit.localization import set_language
from home_finance_cockpit.services.exchange_rates import ExchangeRateService, parse_table
from home_finance_cockpit.storage import Database
from home_finance_cockpit.storage.finance_features import rate_value


class SavingsStorageTests(TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")

    def test_wallet_goal_tracks_balance_and_manual_goal_is_independent(self):
        self.db.save_savings_goal("Reserve", self.wallet, "2000", "0", calculation_mode="wallet")
        b = self.db.save_savings_goal(
            "Holiday", None, "800", "400", calculation_mode="manual", currency="PLN"
        )
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 100000)
        self.db.save_transaction(
            self.wallet, "-500", self.db.default_category_id(), "Rent", "2026-10-01"
        )
        goals = self.db.savings_goals()
        self.assertEqual([g["funded_minor"] for g in goals], [50000, 40000])
        self.assertIsNone(goals[1]["wallet_id"])
        self.db.delete("savings_goals", [b])
        self.db.undo_delete()
        self.assertEqual(len(self.db.savings_goals()), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete("wallets", [self.wallet])

    def test_manual_additions_corrections_and_validation_are_atomic(self):
        goal = self.db.save_savings_goal("Manual", None, "600", "0", currency="PLN")
        self.db.add_goal_amount(goal, "100.10")
        self.db.add_goal_amount(goal, "199.90")
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 30000)
        self.db.add_goal_amount(goal, "-50")
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 25000)
        with self.assertRaises(ValueError):
            self.db.add_goal_amount(goal, "-251")
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 25000)
        for target, allocated in [("0", "0"), ("10", "-1"), ("NaN", "0")]:
            with self.assertRaises(ValueError):
                self.db.save_savings_goal("Invalid", self.wallet, target, allocated)
        with self.assertRaises(ValueError):
            self.db.save_savings_goal("Invalid", self.wallet, "1", "0", "2026-02-30")
        self.assertEqual(len(self.db.savings_goals()), 1)

    def test_wallet_with_goals_cannot_silently_change_goal_currency(self):
        self.db.save_savings_goal("Reserve", self.wallet, "2000", "0", calculation_mode="wallet")
        self.db.save_currency("EUR", "EUR")
        with self.assertRaises(ValueError):
            self.db.save_wallet("Main", "1000", "EUR", "2026-01-01", self.wallet)
        self.assertEqual(self.db.savings_goals()[0]["currency"], "PLN")

    def test_manual_currency_cannot_be_reinterpreted_and_mode_switch_preserves_manual_total(self):
        self.db.save_currency("EUR", "EUR")
        goal = self.db.save_savings_goal("Manual", None, "600", "300", currency="EUR")
        eur = next(c for c in self.db.currencies() if c["code"] == "EUR")
        with self.assertRaises(ValueError):
            self.db.save_currency("GBP", "GBP", eur["id"])
        wallet = self.db.save_wallet("Euro", "200", "EUR", "2026-01-01")
        self.db.save_savings_goal(
            "Manual", wallet, "600", "0", goal_id=goal, calculation_mode="wallet"
        )
        self.assertEqual(self.db.savings_goals()[0]["funded_minor"], 20000)
        self.assertEqual(self.db.savings_goals()[0]["allocated_minor"], 30000)

    def test_v8_upgrade_preserves_saved_amounts_currency_and_exchange_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "v8.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("Main", "300", "PLN", "2026-01-01")
            db.save_currency("EUR", "EUR")
            db.save_rate_config("EUR", "manual", "4.2")
            db.save_exchange_config(False, 6)
            with db.transaction():
                db.execute("DROP TABLE savings_goals")
                db.execute("""CREATE TABLE savings_goals(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,
                    wallet_id INTEGER NOT NULL REFERENCES wallets(id),target_minor INTEGER NOT NULL,
                    allocated_minor INTEGER NOT NULL,deadline TEXT)""")
                db.execute(
                    "INSERT INTO savings_goals VALUES(17,?,?,?,?,?)",
                    ("Existing", wallet, 60000, 30000, "2027-06-01"),
                )
                db.execute("DROP TABLE IF EXISTS currency_history_requests")
                db.execute("DROP TABLE IF EXISTS currency_rate_history")
                db.execute("PRAGMA user_version=8")
            db.close()
            db = Database.open_existing(path)
            try:
                goal = db.savings_goals()[0]
                self.assertEqual(
                    (goal["id"], goal["calculation_mode"], goal["currency"], goal["funded_minor"]),
                    (17, "manual", "PLN", 30000),
                )
                self.assertIsNone(goal["wallet_id"])
                self.assertEqual(db.exchange_config()["interval_hours"], 6)
                self.assertEqual(db.effective_rate("EUR"), (Decimal("4.2"), "manual"))
                backup = next((Path(folder) / "backups").glob("before_v12_*.db"))
                with closing(sqlite3.connect(backup)) as original:
                    self.assertEqual(original.execute("PRAGMA user_version").fetchone()[0], 8)
                    self.assertEqual(
                        original.execute("SELECT allocated_minor FROM savings_goals").fetchone()[0],
                        30000,
                    )
            finally:
                db.close()

    def test_v7_upgrade_backed_up_and_reopened_with_all_new_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            db = Database.create_new(path)
            wallet = db.save_wallet("Main", "100", "PLN", "2026-01-01")
            db.save_transaction(wallet, "-10", db.default_category_id(), "Old", "2026-10-01")
            old = [dict(r) for r in db.transactions()]
            db.close()
            with closing(sqlite3.connect(path)) as connection, connection:
                for table in ("savings_goals", "currency_rates", "exchange_settings"):
                    connection.execute("DROP TABLE " + table)
                connection.execute("DROP TABLE IF EXISTS currency_history_requests")
                connection.execute("DROP TABLE IF EXISTS currency_rate_history")
                connection.execute("PRAGMA user_version=7")
            db = Database.open_existing(path)
            self.assertEqual([dict(r) for r in db.transactions()], old)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)
            self.assertEqual(len(list((Path(folder) / "backups").glob("before_v12_*.db"))), 1)
            db.save_savings_goal("Reserve", wallet, "200", "50")
            db.save_currency("EUR", "EUR")
            db.save_rate_config("EUR", "manual", "4.2")
            db.save_exchange_config(False, 12)
            db.close()
            db = Database.open_existing(path)
            try:
                self.assertEqual(db.savings_goals()[0]["funded_minor"], 5000)
                self.assertEqual(db.effective_rate("EUR"), (Decimal("4.2"), "manual"))
                self.assertEqual(db.exchange_config()["interval_hours"], 12)
            finally:
                db.close()

    def test_failed_upgrade_leaves_v7_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            db = Database.create_new(path)
            db.close()
            with closing(sqlite3.connect(path)) as connection, connection:
                for table in ("savings_goals", "currency_rates", "exchange_settings"):
                    connection.execute("DROP TABLE " + table)
                connection.execute("DROP TABLE IF EXISTS currency_history_requests")
                connection.execute("DROP TABLE IF EXISTS currency_rate_history")
                connection.execute("PRAGMA user_version=7")
            original = Database.execute

            def fail(db, sql, params=()):
                if sql == "PRAGMA user_version=12":
                    raise sqlite3.OperationalError("Simulated failure")
                return original(db, sql, params)

            with (
                patch.object(Database, "execute", fail),
                self.assertRaises(sqlite3.OperationalError),
            ):
                Database.open_existing(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
                self.assertFalse(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='savings_goals'"
                    ).fetchone()
                )


class FakeReply(QObject):
    downloadProgress = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.payload = b""
        self.failed = False
        self.aborted = False

    def error(self):
        return (
            QNetworkReply.NetworkError.UnknownNetworkError
            if self.failed
            else QNetworkReply.NetworkError.NoError
        )

    def errorString(self):
        return "offline"

    def readAll(self):
        return QByteArray(self.payload)

    def abort(self):
        self.aborted = True
        self.failed = True
        self.finished.emit()


class FakeNetwork:
    def __init__(self):
        self.requests = []
        self.replies = []

    def get(self, request):
        self.requests.append(request)
        reply = FakeReply()
        self.replies.append(reply)
        return reply


def payload(table="A", **rates):
    return json.dumps(
        [
            dict(
                table=table,
                effectiveDate="2026-01-02",
                rates=[dict(code=code, mid=value) for code, value in rates.items()],
            )
        ]
    ).encode()


class ExchangeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language("pl")
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        for code in ("EUR", "USD", "BTC"):
            self.db.save_currency(code, code)
        self.service = ExchangeRateService(self.db)
        self.network = FakeNetwork()
        self.service.network = self.network
        self.addCleanup(self.service.stop)

    def test_contract_validation_decimal_values_and_invalid_rates(self):
        rates = parse_table(payload(EUR=4.3), "A")
        self.assertEqual(rates["EUR"], ("4.3", "2026-01-02"))
        for value in ("0", "-1", "NaN", "Infinity", "0.00000000001"):
            with self.assertRaises(ValueError):
                rate_value(value)
        for value in (b"[]", b"{}", b"not JSON", payload("B", EUR=4), payload(EUR=0)):
            with self.assertRaises((ValueError, TypeError, KeyError)):
                parse_table(value, "A")

    def test_success_failure_manual_fallback_and_cache_recovery(self):
        self.db.save_rate_config("USD", "api", "4.1")
        self.db.store_quote("EUR", "4.2", "2026-01-01")
        self.service.refresh_now()
        self.assertTrue(self.service.busy)
        self.assertTrue(all(r.url().scheme() == "https" for r in self.network.requests))
        self.network.replies[0].payload = payload(EUR=4.3)
        self.network.replies[0].finished.emit()
        self.network.replies[1].failed = True
        self.network.replies[1].finished.emit()
        self.assertFalse(self.service.busy)
        self.assertEqual(self.db.effective_rate("EUR"), (Decimal("4.3"), "api"))
        self.assertEqual(self.db.effective_rate("USD"), (Decimal("4.1"), "fallback"))
        self.assertEqual(self.db.effective_rate("BTC"), (None, "missing"))
        self.service.refresh_now()
        for reply in self.network.replies[-2:]:
            reply.failed = True
            reply.finished.emit()
        self.assertEqual(self.db.effective_rate("EUR"), (Decimal("4.3"), "cached"))
        self.service.refresh_now()
        self.network.replies[-2].payload = payload(EUR=4.4, USD=3.9)
        self.network.replies[-2].finished.emit()
        self.network.replies[-1].payload = payload("B", CZK=0.16)
        self.network.replies[-1].finished.emit()
        self.assertEqual(self.db.effective_rate("USD"), (Decimal("3.9"), "api"))
        self.assertEqual(self.db.effective_rate("PLN"), (Decimal(1), "base"))

    def test_schedule_default_daily_disabled_manual_refresh_and_no_overlap(self):
        self.assertEqual(self.db.exchange_config()["interval_hours"], 24)
        with patch.object(self.service, "refresh_now") as refresh:
            self.service.check_due()
            refresh.assert_called_once()
            refresh.reset_mock()
            with self.db.transaction():
                self.db.execute(
                    "UPDATE exchange_settings SET last_attempt=?",
                    (datetime.now(timezone.utc).isoformat(),),
                )
            self.service.check_due()
            refresh.assert_not_called()
            with self.db.transaction():
                self.db.execute(
                    "UPDATE exchange_settings SET last_attempt=?",
                    ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),),
                )
            self.db.save_exchange_config(False, 24)
            self.service.check_due()
            refresh.assert_not_called()
        self.service.refresh_now()
        self.service.refresh_now()
        self.assertEqual(len(self.network.requests), 2)
        self.service.stop()
        self.assertTrue(all(r.aborted for r in self.network.replies))

    def test_manual_mode_during_request_and_close_before_reply(self):
        self.service.refresh_now()
        self.db.save_rate_config("EUR", "manual", "4.9")
        self.network.replies[0].payload = payload(EUR=4.3)
        self.network.replies[0].finished.emit()
        self.network.replies[1].payload = payload("B", CZK=0.16)
        self.network.replies[1].finished.emit()
        self.assertEqual(self.db.effective_rate("EUR"), (Decimal("4.9"), "manual"))
        self.service.refresh_now()
        self.db.close()
        self.assertFalse(self.service.active)
        self.assertTrue(all(r.aborted for r in self.network.replies[-2:]))

    def test_total_request_deadline_uses_fallback_and_unlocks_refresh(self):
        self.db.save_rate_config("EUR", "api", "4.2")
        self.service.refresh_now()
        self.service.deadline.timeout.emit()
        self.assertFalse(self.service.busy)
        self.assertEqual(self.db.effective_rate("EUR"), (Decimal("4.2"), "fallback"))
        self.assertTrue(all(r.aborted for r in self.network.replies))

    def test_currency_rename_clears_old_api_quote_and_undo_restores_configuration(self):
        self.db.save_rate_config("EUR", "api", "4.2")
        self.db.store_quote("EUR", "4.3", "2026-01-02")
        eur = next(r for r in self.db.currencies() if r["code"] == "EUR")
        self.db.delete("currencies", [eur["id"]])
        self.db.undo_delete()
        self.assertEqual(self.db.effective_rate("EUR"), (Decimal("4.3"), "api"))
        self.db.save_currency("GBP", "GBP", eur["id"])
        self.assertIsNone(next(r for r in self.db.rate_records() if r["code"] == "GBP")["api_rate"])


class SavingsExchangeUITests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_spaced_amounts_create_edit_add_and_display_as_numeric_storage(self):
        from PyQt6.QtWidgets import QLabel

        from home_finance_cockpit.ui.goal_workspace import SavingsGoalsPage
        from home_finance_cockpit.ui.savings_goals import GoalDialog, GoalSummary

        db = Database(":memory:")
        widgets = []
        try:
            dialog = GoalDialog(None, db)
            widgets.append(dialog)
            dialog.mode.setCurrentIndex(dialog.mode.findData("manual"))
            dialog.name.setText("Spaced amounts")
            dialog.target.setText("10 000.00")
            dialog.allocated.setText("1 000.50")
            dialog.persist()
            record = db.savings_goals()[0]
            edit = GoalDialog(None, db, record)
            widgets.append(edit)
            self.assertEqual(edit.target.text(), "10 000.00")
            self.assertEqual(edit.allocated.text(), "1 000.50")
            edit.target.setText("20\u00a0000.00")
            edit.allocated.setText("2\u202f000.50")
            edit.persist()
            page = SavingsGoalsPage(db)
            widgets.append(page)
            for value in ("1 000.25", "-1 000.00"):
                page.amount.setText(value)
                page.apply_contribution()
            stored = db.execute(
                "SELECT target_minor,allocated_minor,typeof(target_minor),typeof(allocated_minor) FROM savings_goals"
            ).fetchone()
            self.assertEqual(tuple(stored), (2000000, 200075, "integer", "integer"))
            self.assertEqual(page.editor.target.text(), "20 000.00")
            self.assertEqual(page.editor.allocated.text(), "2 000.75")
            summary = GoalSummary(db)
            widgets.append(summary)
            summary.refresh()
            self.assertIn(
                "2 000.75 PLN / 20 000.00 PLN", [w.text() for w in summary.findChildren(QLabel)]
            )
        finally:
            for widget in widgets:
                widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            db.close()

    def test_goal_tab_overview_currency_configuration_and_language(self):
        from home_finance_cockpit.ui.editors import CurrencyDialog
        from home_finance_cockpit.ui.main_window import FinanceApp
        from home_finance_cockpit.ui.savings_goals import GoalDialog
        from home_finance_cockpit.ui.settings import SettingsDialog

        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            db = Database(":memory:")
            db.save_wallet("Savings", "1000", "PLN", "2026-01-01")
            window = FinanceApp(db, settings=settings)
            window.exchange_rates.stop()
            dialog = None
            try:
                goal = GoalDialog(window, db)
                goal.mode.setCurrentIndex(1)
                goal.name.setText("Holiday")
                goal.target.setText("2000")
                goal.allocated.setText("600")
                goal.persist()
                goal.deleteLater()
                window.refresh_ui()
                self.assertEqual(window.goals_page.goal_list.count(), 1)
                self.assertEqual(
                    window.dashboard.goals_summary.findChildren(QProgressBar)[-1].value(), 30
                )
                self.assertFalse(window.dashboard.goals_summary.findChildren(QPushButton))
                window.tabs.setCurrentIndex(7)
                self.assertEqual(window.workspace.add_button.text(), "Dodaj cel")
                with patch.object(window.workspace, "add_goal") as add:
                    window.workspace.add_button.click()
                    add.assert_called_once()
                dialog = SettingsDialog(window, 2)
                self.assertEqual(dialog.currencies.exchange_settings.hours.value(), 24)
                dialog.currencies.exchange_settings.hours.setValue(6)
                dialog.currencies.exchange_settings.enabled.setChecked(False)
                self.assertTrue(dialog.save())
                self.assertEqual(db.exchange_config()["interval_hours"], 6)
                currency = CurrencyDialog(window, db)
                currency.code.setText("EUR")
                currency.symbol.setText("EUR")
                currency.rate_mode.setCurrentIndex(1)
                currency.manual_rate.setText("4.25")
                currency.persist()
                currency.deleteLater()
                db.save_wallet("Euro", "100", "EUR", "2026-01-01")
                window.refresh_ui()
                self.assertIn("1 425.00", window.dashboard.valuation.text())
                dialog.close()
                dialog.deleteLater()
                dialog = None
                window.change_language("en")
                self.assertEqual(window.tabs.tabText(7), "Savings goals")
                self.assertEqual(window.goals_page.goal_list.count(), 1)
            finally:
                if dialog:
                    dialog.close()
                    dialog.deleteLater()
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                set_language("pl")

    def test_wallet_half_progress_and_manual_add_amount_without_wallet(self):
        from home_finance_cockpit.ui.goal_workspace import SavingsGoalsPage
        from home_finance_cockpit.ui.savings_goals import GoalDialog, GoalSummary

        db = Database(":memory:")
        try:
            wallet = db.save_wallet("Main", "300", "PLN", "2026-01-01")
            automatic = GoalDialog(None, db)
            automatic.name.setText("Automatic")
            automatic.target.setText("600")
            automatic.persist()
            automatic.deleteLater()
            self.assertEqual(db.savings_goals()[0]["funded_minor"], 30000)
            manual = GoalDialog(None, db)
            manual.mode.setCurrentIndex(1)
            manual.name.setText("Manual")
            manual.target.setText("600")
            manual.persist()
            manual.deleteLater()
            record = db.savings_goals()[1]
            page = SavingsGoalsPage(db)
            page.selected_id = record["id"]
            page.load_editor(record)
            for value in ("100", "200"):
                page.amount.setText(value)
                page.apply_contribution()
            page.deleteLater()
            summary = GoalSummary(db)
            summary.refresh()
            self.assertEqual([p.value() for p in summary.findChildren(QProgressBar)], [50, 50])
            self.assertFalse(summary.findChildren(QPushButton))
            summary.deleteLater()
            self.assertEqual(db.wallet(wallet)["opening_minor"], 30000)
        finally:
            db.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
