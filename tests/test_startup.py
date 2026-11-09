"""Database chooser and switching tests use only disposable databases."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from home_finance_cockpit.application import ApplicationController
from home_finance_cockpit.storage import Database


class DatabaseSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_new_database_reopens_and_never_overwrites(self):
        path = self.root / "new.db"
        db = Database.create_new(path)
        db.save_wallet("A", "12.34", "PLN", "2026-01-01")
        db.close()
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            Database.create_new(path)
        self.assertEqual(before, path.read_bytes())
        db = Database.open_existing(path)
        self.assertEqual(db.wallets()[0]["opening_minor"], 1234)
        db.close()

    def test_open_missing_file_does_not_create_it(self):
        path = self.root / "missing.db"
        with self.assertRaises(ValueError):
            Database.open_existing(path)
        self.assertFalse(path.exists())

    def test_foreign_database_is_not_modified(self):
        path = self.root / "other.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE important(value TEXT)")
            connection.commit()
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            Database.open_existing(path)
        self.assertEqual(before, path.read_bytes())

    def test_empty_and_non_sqlite_files_are_rejected(self):
        for data in (b"", b"not a database"):
            path = self.root / "invalid.db"
            path.write_bytes(data)
            with self.assertRaises((ValueError, sqlite3.Error)):
                Database.open_existing(path)
            self.assertEqual(path.read_bytes(), data)

    def test_newer_version_is_rejected(self):
        path = self.root / "future.db"
        db = Database.create_new(path)
        db.execute("PRAGMA user_version=999")
        db.close()
        with self.assertRaises(ValueError):
            Database.open_existing(path)


class StubWindow(QWidget):
    open_database_requested = pyqtSignal()
    new_database_requested = pyqtSignal()

    def __init__(self, db):
        super().__init__()
        self.db = db

    def closeEvent(self, event):
        self.db.close()
        event.accept()


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.controller = ApplicationController(
            self.app, settings=self.settings, window_factory=StubWindow
        )
        self.addCleanup(self.dispose)

    def dispose(self):
        if self.controller.window:
            self.controller.window.close()
            self.controller.window.deleteLater()
        self.controller.launcher.close()
        self.controller.launcher.deleteLater()
        self.app.processEvents()

    def create_file(self, name):
        path = self.root / name
        Database.create_new(path).close()
        return path

    def test_new_selection_saves_last_path(self):
        path = self.root / "fresh.db"
        self.controller._finish_open(path, create=True)
        self.assertEqual(self.settings.value("last_database"), str(path.resolve()))
        self.assertFalse(self.controller.launcher.isVisible())
        self.assertEqual(len(self.controller.window.db.wallets()), 1)
        self.assertEqual(self.controller.window.db.wallets()[0]["opening_minor"], 0)

    def test_switch_only_closes_old_database_after_success(self):
        first, second = self.create_file("a.db"), self.create_file("b.db")
        self.controller._finish_open(first)
        old_db = self.controller.window.db
        self.controller._finish_open(second)
        with self.assertRaises(sqlite3.ProgrammingError):
            old_db.wallets()
        self.assertEqual(self.controller.window.db.path, str(second.resolve()))
        self.assertEqual(self.settings.value("last_database"), str(second.resolve()))

    def test_failed_switch_keeps_current_database_and_last_setting(self):
        first = self.create_file("a.db")
        self.controller._finish_open(first)
        window = self.controller.window
        with patch("home_finance_cockpit.application.QMessageBox.warning"):
            self.controller._finish_open(self.root / "missing.db")
        self.assertIs(self.controller.window, window)
        self.assertTrue(window.isEnabled())
        self.assertEqual(window.db.wallets(), [])
        self.assertEqual(self.settings.value("last_database"), str(first.resolve()))

    def test_failed_window_creation_keeps_previous_window(self):
        first, second = self.create_file("a.db"), self.create_file("b.db")
        self.controller._finish_open(first)
        window = self.controller.window
        with (
            patch.object(self.controller, "window_factory", side_effect=RuntimeError("UI failed")),
            patch("home_finance_cockpit.application.QMessageBox.warning"),
        ):
            self.controller._finish_open(second)
        self.assertIs(self.controller.window, window)
        self.assertEqual(self.settings.value("last_database"), str(first.resolve()))
        self.assertEqual(window.db.wallets(), [])

    def test_canceled_dialogs_do_not_switch_or_create(self):
        with (
            patch(
                "home_finance_cockpit.application.QFileDialog.getOpenFileName",
                return_value=("", ""),
            ),
            patch(
                "home_finance_cockpit.application.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ),
        ):
            self.controller.choose_existing()
            self.controller.choose_new()
        self.assertIsNone(self.controller.window)
        self.assertFalse(self.settings.contains("last_database"))

    def test_last_path_is_restored_on_next_launch(self):
        first = self.create_file("a.db")
        self.controller._finish_open(first)
        another = ApplicationController(self.app, settings=self.settings, window_factory=StubWindow)
        self.assertEqual(another.last_path, first.resolve())
        self.assertIn("a.db", another.launcher.last_path.text())
        another.launcher.deleteLater()

    def test_deleted_last_database_is_reported_and_does_not_reappear(self):
        missing = self.root / "gone.db"
        with patch("home_finance_cockpit.application.QMessageBox.warning") as warning:
            self.controller._finish_open(missing)
        warning.assert_called_once()
        self.assertFalse(missing.exists())
        self.assertFalse(self.settings.contains("last_database"))

    def test_startup_is_visible_before_deferred_open(self):
        path = self.create_file("a.db")
        self.controller.start_open(path)
        self.assertTrue(self.controller.launcher.isVisible())
        self.assertTrue(self.controller.loading)
        self.assertIsNone(self.controller.window)
        for _ in range(40):
            if not self.controller.loading:
                break
            QTest.qWait(50)
        self.assertFalse(self.controller.loading)
        self.assertIsNotNone(self.controller.window)

    def test_new_filename_gets_db_extension(self):
        with (
            patch(
                "home_finance_cockpit.application.QFileDialog.getSaveFileName",
                return_value=(str(self.root / "fresh"), ""),
            ),
            patch.object(self.controller, "start_open") as opened,
        ):
            self.controller.choose_new()
        opened.assert_called_once_with(self.root / "fresh.db", create=True)


class LightweightStartupTests(unittest.TestCase):
    def test_importing_entry_point_does_not_load_plotting_or_main_window(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import main,sys; assert 'matplotlib' not in sys.modules; assert 'home_finance_cockpit.ui.main_window' not in sys.modules; print('OK')",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)


class WindowShutdownTests(unittest.TestCase):
    def test_transaction_page_destruction_has_no_qt_callback_errors(self):
        script = """
import sys
from unittest.mock import MagicMock
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.transactions_page import TransactionsPage
app = QApplication([])
errors = []
sys.excepthook = lambda kind, value, tb: errors.append(str(value))
for _ in range(3):
    db = Database(':memory:')
    page = TransactionsPage(db, MagicMock())
    page.show()
    app.processEvents()
    page.resize(1500, 800)
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    db.close()
assert not errors, errors
print('OK')
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)
