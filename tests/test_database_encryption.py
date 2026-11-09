"""Real SQLCipher interoperability, conversion failures and password UI flows."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from sqlcipher3 import dbapi2 as cipher

from home_finance_cockpit.services.backups import BackupService
from home_finance_cockpit.services.preferences import Preferences
from home_finance_cockpit.storage import Database
from home_finance_cockpit.storage.encryption import InvalidPassword, PasswordRequired


class EncryptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "personal.db"
        self.db = Database.create_new(self.path)
        self.addCleanup(lambda: self.db.close())
        self.wallet = self.db.save_wallet("PRIVATE WALLET", "300", "PLN", "2026-01-01")
        self.password = " Hasło 'Żółć' 123 "

    def test_encrypted_file_requires_password_in_app_and_external_tool(self):
        self.db.change_password(self.password)
        self.assertNotIn(b"PRIVATE WALLET", self.path.read_bytes())
        with closing(sqlite3.connect(self.path)) as ordinary:
            with self.assertRaises(sqlite3.DatabaseError):
                ordinary.execute("SELECT * FROM wallets").fetchall()
        before = self.path.read_bytes()
        with self.assertRaises(PasswordRequired):
            Database.open_existing(self.path)
        with self.assertRaises(InvalidPassword):
            Database.open_existing(self.path, "wrong password")
        self.assertEqual(before, self.path.read_bytes())
        # Independent connection: no application wrapper or metadata is needed.
        with closing(cipher.connect(str(self.path))) as external:
            external.set_key(self.password)
            self.assertEqual(
                external.execute("SELECT name FROM wallets").fetchone()[0], "PRIVATE WALLET"
            )
        reopened = Database.open_existing(self.path, self.password)
        try:
            self.assertEqual(reopened.wallet(self.wallet)["opening_minor"], 30000)
        finally:
            reopened.close()

    def test_change_and_remove_password_preserve_data_and_old_backups(self):
        self.db.change_password(self.password)
        backup = self.root / "old.db"
        self.db.backup(backup)
        self.db.change_password("different password", self.password)
        with self.assertRaises(InvalidPassword):
            Database.open_existing(self.path, self.password)
        old = Database.open_existing(backup, self.password)
        old.close()
        self.db.change_password(None, "different password")
        self.assertFalse(self.db.is_encrypted)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT name FROM wallets").fetchone()[0], "PRIVATE WALLET"
            )
        self.assertNotEqual(backup.read_bytes()[:16], b"SQLite format 3\x00")

    def test_current_password_and_validation_never_modify_the_file(self):
        self.db.change_password(self.password)
        before = self.path.read_bytes()
        for new, current in [
            ("another password", "bad"),
            (None, None),
            ("short", self.password),
            ("bad\x00password", self.password),
        ]:
            with self.assertRaises(ValueError):
                self.db.change_password(new, current)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(self.db.wallet(self.wallet)["name"], "PRIVATE WALLET")

    def test_export_verification_or_replace_failure_keeps_original_usable(self):
        for stage in ("export", "verify_file", "os.replace"):
            with self.subTest(stage=stage):
                before = self.path.read_bytes()
                with patch(
                    "home_finance_cockpit.storage.database." + stage,
                    side_effect=OSError("Disk failure"),
                ):
                    with self.assertRaises(OSError):
                        self.db.change_password(self.password)
                self.assertFalse(self.db.is_encrypted)
                self.assertEqual(before, self.path.read_bytes())
                self.assertEqual(self.db.wallet(self.wallet)["name"], "PRIVATE WALLET")
                self.assertEqual(list(self.root.glob("*.secure")), [])

    def test_failed_rekey_keeps_old_password(self):
        self.db.change_password(self.password)
        with patch(
            "home_finance_cockpit.storage.database.os.replace",
            side_effect=PermissionError("File in use"),
        ):
            with self.assertRaises(PermissionError):
                self.db.change_password("replacement password", self.password)
        reopened = Database.open_existing(self.path, self.password)
        reopened.close()
        self.assertTrue(self.db.is_encrypted)
        self.assertEqual(self.db.wallet(self.wallet)["name"], "PRIVATE WALLET")

    def test_backup_service_publishes_encrypted_verified_copy_without_storing_password(self):
        self.db.change_password(self.password)
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        service = BackupService(self.db, Preferences(self.db.path, settings))
        backup = service.create_backup(str(self.root / "copies"))
        with self.assertRaises(PasswordRequired):
            Database.open_existing(backup)
        reopened = Database.open_existing(backup, self.password)
        reopened.close()
        settings.sync()
        self.assertNotIn(self.password, Path(settings.fileName()).read_text(encoding="utf-8"))
        self.assertEqual(list(backup.parent.glob("*.partial")), [])

    def test_memory_snapshot_is_independent_and_constraints_use_standard_errors(self):
        self.db.change_password(self.password)
        copy = self.db.memory_snapshot()
        try:
            self.assertEqual(copy.wallet(self.wallet)["name"], "PRIVATE WALLET")
            copy.save_wallet("PREVIEW ONLY", "10", "PLN", "2026-01-01")
            self.assertEqual(len(self.db.wallets()), 1)
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("INSERT INTO currencies(code,symbol) VALUES('PLN','duplicate')")
        finally:
            copy.close()

    def test_password_change_refuses_pending_transactions(self):
        with self.db.transaction():
            with self.assertRaises(ValueError):
                self.db.change_password(self.password)
        self.assertFalse(self.db.is_encrypted)

    def test_encrypted_batch_import_and_report_snapshot(self):
        from home_finance_cockpit.reports.data import ReportOptions, snapshot
        from home_finance_cockpit.services.import_files import (
            commit_import_batch,
            prepare_import_batch,
        )
        from home_finance_cockpit.services.importing import read_csv, suggested_mapping

        path = self.root / "bank.csv"
        path.write_text(
            "Date,Amount,Description,Currency\n2026-10-01,-20,Purchase,PLN\n", encoding="utf-8"
        )
        self.db.change_password(self.password)
        file = read_csv(path)
        plans = prepare_import_batch(self.db, [file], self.wallet, suggested_mapping(file.headers))
        self.assertFalse(plans[0].errors)
        self.assertEqual(self.db.transactions(), [])
        self.assertEqual(commit_import_batch(self.db, plans), [1])
        data = snapshot(self.db, ReportOptions(currency="PLN"))
        self.assertEqual(data["monthly_months"], ("2026-10",))
        self.assertEqual(self.db.transactions()[0]["amount_minor"], -2000)
        self.assertNotEqual(self.path.read_bytes()[:16], b"SQLite format 3\x00")

    def test_settings_change_password_without_rebuilding_or_closing_database(self):
        from PyQt6.QtWidgets import QDialog

        from home_finance_cockpit.ui.database_password import DatabasePasswordDialog
        from home_finance_cockpit.ui.main_window import FinanceApp
        from home_finance_cockpit.ui.settings import SettingsDialog

        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        window = FinanceApp(self.db, settings=settings)
        dialog = SettingsDialog(window, section=1)
        try:

            def set_password(editor):
                editor.new.setText(self.password)
                editor.confirm.setText(self.password)
                return QDialog.DialogCode.Accepted

            with patch.object(DatabasePasswordDialog, "exec", set_password):
                dialog.password_button.click()
            self.assertTrue(self.db.is_encrypted)
            self.assertIn("SQLCipher", dialog.encryption_status.text())
            # Existing pages and services retain the same Database object after conversion.
            window.refresh_ui()
            self.assertIs(window.db, self.db)
            self.assertEqual(self.db.wallet(self.wallet)["name"], "PRIVATE WALLET")

            def remove_password(editor):
                editor.current.setText(self.password)
                return QDialog.DialogCode.Accepted

            with patch.object(DatabasePasswordDialog, "exec", remove_password):
                dialog.remove_password_button.click()
            self.assertFalse(self.db.is_encrypted)
            self.assertFalse(dialog.remove_password_button.isVisible())
            window.refresh_ui()
        finally:
            dialog.reject()
            dialog.deleteLater()
            window.close()
            window.deleteLater()

    def test_encrypted_schema_upgrade_creates_encrypted_migration_backup(self):
        self.db.change_password(self.password)
        with self.db.transaction():
            self.db.execute("DROP TABLE currency_history_requests")
            self.db.execute("DROP TABLE currency_rate_history")
            self.db.execute("PRAGMA user_version=11")
        self.db.close()
        self.db = Database.open_existing(self.path, self.password)
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 12)
        backups = list((self.root / "backups").glob("before_v12_*.db"))
        self.assertEqual(len(backups), 1)
        self.assertNotEqual(backups[0].read_bytes()[:16], b"SQLite format 3\x00")
        self.db.verify_backup(backups[0])


class PasswordLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_retry_and_cancel_preserve_current_window_and_settings(self):
        from home_finance_cockpit.application import ApplicationController
        from tests.test_startup import StubWindow

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ordinary, protected = root / "plain.db", root / "secret.db"
            Database.create_new(ordinary).close()
            db = Database.create_new(protected)
            db.change_password("secret password")
            db.close()
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            controller = ApplicationController(
                self.app, settings=settings, window_factory=StubWindow
            )
            try:
                controller._finish_open(ordinary)
                old_window = controller.window
                with (
                    patch(
                        "home_finance_cockpit.application.QInputDialog.getText",
                        return_value=("", False),
                    ),
                    patch("home_finance_cockpit.application.QMessageBox.warning") as warning,
                ):
                    controller._finish_open(protected)
                    warning.assert_not_called()
                self.assertIs(controller.window, old_window)
                self.assertTrue(old_window.isEnabled())
                self.assertEqual(settings.value("last_database"), str(ordinary))
                with (
                    patch(
                        "home_finance_cockpit.application.QInputDialog.getText",
                        side_effect=[("bad", True), ("secret password", True)],
                    ),
                    patch("home_finance_cockpit.application.QMessageBox.warning") as warning,
                ):
                    controller._finish_open(protected)
                    warning.assert_called_once()
                self.assertTrue(controller.window.db.is_encrypted)
                self.assertEqual(settings.value("last_database"), str(protected))
                settings.sync()
                self.assertNotIn("secret password", Path(settings.fileName()).read_text())
            finally:
                if controller.window:
                    controller.window.close()
                    controller.window.deleteLater()
                controller.launcher.close()
                controller.launcher.deleteLater()

    def test_password_dialog_requires_matching_confirmation(self):
        from home_finance_cockpit.ui.database_password import DatabasePasswordDialog

        dialog = DatabasePasswordDialog(None)
        try:
            dialog.new.setText("secure password")
            dialog.confirm.setText("other password")
            dialog.validate()
            self.assertEqual(dialog.result(), 0)
            self.assertTrue(dialog.error.text())
            dialog.confirm.setText("secure password")
            dialog.validate()
            self.assertEqual(dialog.result(), 1)
            dialog.clear_passwords()
            self.assertEqual(dialog.new.text(), "")
        finally:
            dialog.deleteLater()
