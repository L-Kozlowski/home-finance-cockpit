"""Editable, persistent keyboard shortcuts and action routing."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.services.shortcuts import defaults, load, validate
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.settings import SettingsDialog


class ShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = QSettings(
            str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat
        )

    def test_defaults_invalid_duplicates_and_prefix_conflicts(self):
        bindings = defaults()
        self.assertEqual(validate(bindings), bindings)
        for sequence in ("Ctrl+F", "Ctrl+F, Ctrl+K", "A", "Shift+A", "NotAKey"):
            with self.subTest(sequence=sequence):
                with self.assertRaises(ValueError):
                    validate(dict(bindings, overview=sequence))
        self.assertEqual(validate(dict(bindings, overview=""))["overview"], "")
        self.settings.setValue("general/shortcuts", "broken json")
        self.assertEqual(load(self.settings), bindings)

    def test_custom_binding_save_reload_reset_conflict_and_busy_state(self):
        window = FinanceApp(Database(":memory:"), settings=self.settings)
        dialog = SettingsDialog(window)
        try:
            self.assertEqual(dialog.sections.item(3).text(), "Skróty klawiszowe")
            editor = dialog.shortcut_page.editors["wallets"]
            editor.setKeySequence(QKeySequence("Ctrl+Shift+F8"))
            dialog.shortcut_page.editors["overview"].clear()
            self.assertTrue(dialog.save())
            self.assertEqual(load(self.settings)["wallets"], "Ctrl+Shift+F8")
            self.assertFalse(window.shortcuts["overview"].isEnabled())
            window.shortcuts["wallets"].activated.emit()
            self.assertEqual(window.tabs.currentIndex(), 2)
            window.set_report_busy(True)
            self.assertFalse(any(s.isEnabled() for s in window.shortcuts.values()))
            window.set_report_busy(False)
            self.assertFalse(window.shortcuts["overview"].isEnabled())
            editor.setKeySequence(QKeySequence("Ctrl+F"))
            with patch.object(QMessageBox, "warning") as warning:
                self.assertFalse(dialog.save())
                warning.assert_called_once()
            self.assertEqual(load(self.settings)["wallets"], "Ctrl+Shift+F8")
            dialog.shortcut_page.reset()
            self.assertTrue(dialog.save())
            self.assertEqual(load(self.settings), defaults())
            reopened = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
            self.assertEqual(load(reopened), defaults())
        finally:
            dialog.close()
            dialog.deleteLater()
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_new_default_does_not_replace_existing_custom_binding(self):
        previous = defaults()
        previous.pop("goals")
        previous.pop("add_goal")
        previous["wallets"] = "Ctrl+Shift+G"
        self.settings.setValue("general/shortcuts", json.dumps(previous))
        loaded = load(self.settings)
        self.assertEqual(loaded["wallets"], "Ctrl+Shift+G")
        self.assertEqual(loaded["goals"], "")
        self.assertEqual(loaded["add_goal"], "Ctrl+G")

    def test_real_keypress_navigation_and_shortcuts_survive_language_change(self):
        window = FinanceApp(Database(":memory:"), settings=self.settings)
        try:
            window.show()
            window.activateWindow()
            window.setFocus()
            self.app.processEvents()
            QTest.keyClick(
                window,
                Qt.Key.Key_T,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
            self.assertEqual(window.tabs.currentIndex(), 1)
            window.change_language("en")
            window.shortcuts["analytics"].activated.emit()
            self.assertEqual(window.tabs.currentIndex(), 4)
            self.assertEqual(len(window.shortcuts), len(defaults()))
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()
            from home_finance_cockpit.localization import set_language

            set_language("pl")

    def test_shortcuts_route_to_windows_and_database_chooser(self):
        from contextlib import ExitStack

        window = FinanceApp(Database(":memory:"), settings=self.settings)
        try:
            with ExitStack() as stack:
                methods = {
                    name: stack.enter_context(patch.object(window, name))
                    for name in (
                        "show_settings",
                        "manage",
                        "add_transaction",
                        "add_wallet",
                        "import_csv",
                        "backup",
                    )
                }
                window.apply_shortcuts()
                for action, method in (
                    ("settings", "show_settings"),
                    ("currencies", "manage"),
                    ("add_transaction", "add_transaction"),
                    ("add_wallet", "add_wallet"),
                    ("import", "import_csv"),
                    ("backup", "backup"),
                ):
                    window.shortcuts[action].activated.emit()
                    methods[method].assert_called_once()
                methods["manage"].assert_called_once_with("currencies")
                events = []
                window.open_database_requested.connect(lambda: events.append("open"))
                window.new_database_requested.connect(lambda: events.append("new"))
                window.shortcuts["open_database"].activated.emit()
                window.shortcuts["new_database"].activated.emit()
                self.assertEqual(events, ["open", "new"])
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()
