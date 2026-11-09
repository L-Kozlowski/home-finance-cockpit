"""Persistent per-database backups and embedded management navigation."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from home_finance_cockpit.services.backups import BackupService
from home_finance_cockpit.services.preferences import Preferences
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.settings import SettingsDialog


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.db = Database.create_new(self.root / "source.db")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "10", "PLN", "2026-01-01")
        self.preferences = Preferences(self.db.path, self.settings)
        self.backups = BackupService(self.db, self.preferences)
        self.addCleanup(self.backups.stop)
        self.folder = self.root / "copies"

    def test_defaults_and_per_database_preferences_survive_restart(self):
        enabled, interval, folder = self.preferences.backup_config()
        self.assertFalse(enabled)
        self.assertEqual(interval, 86400)
        self.preferences.save(True, 3600, str(self.folder), 5)
        reopened = Preferences(
            self.db.path, QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        )
        self.assertEqual(reopened.backup_config(), (True, 3600, str(self.folder.resolve())))
        self.assertEqual(reopened.start_page(), 5)
        other = Preferences(str(self.root / "other.db"), self.settings)
        self.assertFalse(other.backup_config()[0])
        self.assertEqual(other.start_page(), 5)

    def test_invalid_settings_are_not_persisted(self):
        for enabled, interval, folder, page in (
            (True, 1, str(self.folder), 0),
            (True, 3600, self.db.path, 0),
            (True, 3600, "", 0),
            (True, 3600, str(self.folder), 99),
        ):
            with self.assertRaises(ValueError):
                self.preferences.save(enabled, interval, folder, page)
        self.assertFalse(self.preferences.backup_config()[0])
        with self.assertRaises(ValueError):
            Preferences(":memory:", self.settings).save(True, 3600, str(self.folder), 0)

    def test_scheduled_backup_is_valid_does_not_repeat_and_catches_up(self):
        self.preferences.save(True, 86400, str(self.folder), 0)
        self.backups.check_due()
        copies = list(self.folder.glob("*.db"))
        self.assertEqual(len(copies), 1)
        with closing(sqlite3.connect(copies[0])) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT name FROM wallets").fetchone()[0], "Main")
        self.backups.check_due()
        self.assertEqual(len(list(self.folder.glob("*.db"))), 1)
        self.settings.setValue(
            self.preferences.key + "last_backup_time",
            (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        )
        self.backups.check_due()
        self.assertEqual(len(list(self.folder.glob("*.db"))), 2)
        self.assertEqual(self.backups.last_error, "")

    def test_deleted_copy_and_changed_destination_trigger_new_copy(self):
        self.preferences.save(True, 86400, str(self.folder), 0)
        path = self.backups.create_backup()
        path.unlink()
        self.backups.check_due()
        self.assertEqual(len(list(self.folder.glob("*.db"))), 1)
        second = self.root / "new-folder"
        self.preferences.save(True, 86400, str(second), 0)
        self.backups.check_due()
        self.assertEqual(len(list(second.glob("*.db"))), 1)

    def test_partial_failure_never_publishes_or_records_success(self):
        self.preferences.save(True, 3600, str(self.folder), 0)

        def fail(destination):
            Path(destination).write_bytes(b"incomplete")
            raise OSError("Disk full")

        errors = []
        self.backups.failed.connect(errors.append)
        with patch.object(self.db, "backup", side_effect=fail):
            self.backups.check_due()
        self.assertEqual(errors, ["Disk full"])
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertIsNone(self.backups.last_backup())
        self.assertEqual(self.preferences.get("last_backup_path"), "")

    def test_backup_refuses_active_transaction_and_never_modifies_source(self):
        with self.db.transaction():
            with self.assertRaises(ValueError):
                self.backups.create_backup(str(self.folder))
        first = self.backups.create_backup(str(self.folder))
        second = self.backups.create_backup(str(self.folder))
        self.assertNotEqual(first, second)
        self.assertEqual(self.db.wallet(self.wallet)["name"], "Main")
        with self.assertRaises(ValueError):
            self.backups.create_backup("")


class SettingsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.db = Database.create_new(self.root / "source.db")
        self.window = FinanceApp(self.db, settings=self.settings)
        self.addCleanup(self.window.close)

    def test_categories_are_a_normal_page_and_menu_uses_same_page(self):
        self.window.show()
        QTest.mouseClick(self.window.workspace.nav_buttons[5], Qt.MouseButton.LeftButton)
        self.assertIs(self.window.tabs.currentWidget(), self.window.category_page)
        self.assertFalse(self.window.category_page.isWindow())
        self.assertTrue(self.window.workspace.nav_buttons[5].isChecked())
        self.window.tabs.setCurrentIndex(0)
        self.window.manage("categories")
        self.assertIs(self.window.tabs.currentWidget(), self.window.category_page)
        self.assertFalse(
            any(isinstance(w, QDialog) and w.isVisible() for w in self.app.topLevelWidgets())
        )

    def test_database_menu_opens_to_the_right_of_its_button(self):
        from PyQt6.QtCore import QPoint

        self.window.show()
        self.app.processEvents()
        button = self.window.workspace.database_button
        button.click()
        self.app.processEvents()
        menu = button.menu()
        try:
            self.assertTrue(menu.isVisible())
            self.assertGreaterEqual(menu.x(), button.mapToGlobal(QPoint(button.width(), 0)).x())
        finally:
            menu.hide()

    def test_light_theme_and_point_sizes_apply_and_save_close_refreshes_after_finish(self):
        from home_finance_cockpit.services.preferences import FONT_POINTS
        from home_finance_cockpit.ui.theme import is_light

        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.reject)
        self.assertEqual(
            [dialog.font_size.itemData(i) for i in range(dialog.font_size.count())],
            list(FONT_POINTS),
        )
        dialog.font_size.setCurrentText("11")
        dialog.theme.setCurrentIndex(dialog.theme.findData("light"))
        finished = []
        dialog.finished.connect(lambda *_: finished.append(True))
        refresh = self.window.refresh_ui
        refreshed_after_finish = []

        def capture():
            refreshed_after_finish.append(bool(finished))
            refresh()

        with patch.object(self.window, "refresh_ui", side_effect=capture):
            dialog.save_and_close()
        self.assertTrue(refreshed_after_finish[-1])
        self.assertTrue(is_light())
        self.assertEqual(self.window.preferences.font_points(), 11)
        self.assertEqual(self.window.preferences.theme(), "light")
        self.assertIn("#f4f7fb", self.app.styleSheet())
        from home_finance_cockpit.ui.theme import apply_theme

        apply_theme(self.app, "dark")
        self.assertFalse(is_light())

    def test_settings_sections_save_per_database_and_manual_backup(self):
        dialog = SettingsDialog(self.window)
        self.addCleanup(dialog.reject)
        self.assertEqual(dialog.database_path.text(), self.db.path)
        dialog.sections.setCurrentRow(2)
        self.assertEqual(dialog.pages.currentIndex(), 2)
        self.db.save_currency("EUR", "Euro")
        dialog.currencies.notify_changed()
        self.assertIn(
            "EUR",
            [
                dialog.currencies.table.item(row, 0).text()
                for row in range(dialog.currencies.table.rowCount())
            ],
        )
        dialog.sections.setCurrentRow(1)
        dialog.backup_folder.setText(str(self.root / "backup"))
        dialog.backup_enabled.setChecked(True)
        dialog.frequency.setCurrentIndex(dialog.frequency.findData(3600))
        dialog.start_page.setCurrentIndex(dialog.start_page.findData(5))
        dialog.date_format.setCurrentText("yyyy-MM-dd")
        dialog.font_size.setCurrentText("12")
        dialog.chart_palette.setCurrentIndex(dialog.chart_palette.findData("business"))
        self.assertTrue(dialog.save())
        self.assertEqual(dialog.save_button.text(), "Zapisano")
        self.assertIn("Zapisano ustawienia", dialog.message.text())
        dialog.create_backup()
        self.assertTrue(Path(dialog.last_path.text()).is_file())
        self.assertEqual(
            self.window.preferences.backup_config(), (True, 3600, str(self.root / "backup"))
        )
        self.window.backups.stop()
        another = SettingsDialog(self.window)
        self.addCleanup(another.reject)
        self.assertTrue(another.backup_enabled.isChecked())
        self.assertEqual(another.frequency.currentData(), 3600)
        self.assertEqual(another.start_page.currentData(), 5)
        self.assertEqual(another.date_format.currentText(), "yyyy-MM-dd")
        self.assertEqual(another.font_size.currentData(), 12)
        self.assertEqual(another.chart_palette.currentData(), "business")
        self.assertAlmostEqual(self.app.property("fontScale"), 1.2)
        another.save_and_close()
        self.assertEqual(another.result(), QDialog.DialogCode.Accepted)

    def test_category_changes_refresh_transaction_colors_immediately(self):
        wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        food = self.db.save_category("Food")
        self.db.save_transaction(wallet, "-1", food, "Shop", "2026-01-02")
        self.window.refresh_ui()
        self.db.set_category_color(food, "#78DFC1")
        self.window.category_page.notify_changed()
        self.assertEqual(self.window.transactions[0]["category_color"], "#78DFC1")

    def test_saved_start_page_is_applied_and_timer_stops_on_close(self):
        self.window.preferences.save(False, 86400, str(self.root / "backup"), 5)
        self.window.close()
        self.assertFalse(self.window.backups.timer.isActive())
        self.db = Database.open_existing(self.root / "source.db")
        self.window = FinanceApp(self.db, settings=self.settings)
        self.addCleanup(self.window.close)
        self.assertEqual(self.window.tabs.currentIndex(), 5)
        self.assertTrue(self.window.backups.timer.isActive())
