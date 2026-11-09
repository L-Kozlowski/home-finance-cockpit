"""Database selection and window lifetime, without eager plotting imports."""

import sqlite3
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QTimer
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.preferences import application_settings
from home_finance_cockpit.storage.database import DEFAULT_PATH, LEGACY_PATH, Database
from home_finance_cockpit.storage.encryption import InvalidPassword, PasswordRequired
from home_finance_cockpit.ui.startup import StartupWindow


class OpenCanceled(Exception):
    pass


class ApplicationController(QObject):
    def __init__(self, app, *, settings=None, initial_path=None, window_factory=None):
        super().__init__()
        self.app = app
        self.settings = settings if settings is not None else application_settings()
        from home_finance_cockpit.localization import install_qt_language, set_language

        selected = self.settings.value("general/language", "pl")
        set_language(selected if selected in ("pl", "en") else "pl")
        install_qt_language(app)
        self.window_factory = window_factory
        self.window = None
        self.loading = False
        self.launcher = StartupWindow()
        self.launcher.language_selected.connect(self.change_startup_language)
        self.launcher.open_last_requested.connect(self.open_last)
        self.launcher.open_database_requested.connect(self.choose_existing)
        self.launcher.new_database_requested.connect(self.choose_new)
        stored = self.settings.value("last_database", "", type=str)
        self.last_path = (
            Path(initial_path).expanduser().resolve()
            if initial_path
            else Path(stored)
            if stored
            else None
        )
        if self.last_path is None and (DEFAULT_PATH.exists() or LEGACY_PATH.exists()):
            self.last_path = DEFAULT_PATH
        self.launcher.set_last_path(self.last_path)

    def show(self):
        self.launcher.show()

    def change_startup_language(self, value):
        from home_finance_cockpit.localization import install_qt_language, set_language

        if self.loading or value not in ("pl", "en"):
            self.launcher.retranslate()
            return
        if self.window is not None and hasattr(self.window, "change_language"):
            if not self.window.change_language(value):
                self.launcher.retranslate()
                return
        set_language(value)
        install_qt_language(self.app)
        self.settings.setValue("general/language", value)
        self.settings.sync()
        self.launcher.retranslate()

    def open_last(self):
        if self.last_path is not None:
            self.start_open(self.last_path)

    def choose_existing(self):
        if self.loading:
            return
        parent = self.window or self.launcher
        folder = str(self.last_path.parent if self.last_path else DEFAULT_PATH.parent)
        path, _ = QFileDialog.getOpenFileName(
            parent,
            tr("Otwórz bazę danych"),
            folder,
            tr("Bazy SQLite (*.db *.sqlite *.sqlite3);;Wszystkie pliki (*)"),
        )
        if path:
            self.start_open(Path(path))

    def choose_new(self):
        if self.loading:
            return
        parent = self.window or self.launcher
        DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Existing names are rejected even if a native file dialog offers overwrite.
        path, _ = QFileDialog.getSaveFileName(
            parent,
            tr("Utwórz nową bazę danych"),
            str(DEFAULT_PATH.parent / "nowa_baza.db"),
            tr("Baza SQLite (*.db)"),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            target = Path(path)
            if not target.suffix:
                target = target.with_suffix(".db")
            self.start_open(target, create=True)

    def start_open(self, path, *, create=False):
        if self.loading:
            return
        self.loading = True
        self.launcher.set_busy(True)
        self.launcher.show()
        if self.window is not None:
            self.window.setEnabled(False)
        # Let Qt paint the selection window and progress indicator before imports.
        QTimer.singleShot(30, lambda: self._finish_open(path, create=create))

    def _finish_open(self, path, *, create=False):
        candidate = None
        new_window = None
        old_window = self.window
        try:
            path = Path(path).expanduser().resolve()
            if create:
                from home_finance_cockpit.localization import language

                candidate = Database.create_new(path, starter_language=language())
            elif path == DEFAULT_PATH and not path.exists() and LEGACY_PATH.exists():
                candidate = Database()  # Preserve the original legacy file.
            else:
                try:
                    candidate = Database.open_existing(path)
                except PasswordRequired:
                    while True:
                        password, accepted = QInputDialog.getText(
                            self.launcher,
                            tr("Odblokuj bazę danych"),
                            tr("Hasło do bazy {v0}:", v0=path.name),
                            QLineEdit.EchoMode.Password,
                        )
                        if not accepted:
                            raise OpenCanceled()
                        try:
                            candidate = Database.open_existing(path, password)
                            break
                        except (InvalidPassword, PasswordRequired) as exc:
                            QMessageBox.warning(
                                self.launcher, tr("Nie można odblokować bazy"), str(exc)
                            )
                        finally:
                            password = None
            factory = self.window_factory
            if factory is None:
                from home_finance_cockpit.ui.main_window import FinanceApp

                new_window = FinanceApp(candidate, settings=self.settings)
            else:
                new_window = factory(candidate)
            new_window.open_database_requested.connect(self.choose_existing)
            new_window.new_database_requested.connect(self.choose_new)
            if hasattr(new_window, "language_changed"):
                new_window.language_changed.connect(lambda _: self.launcher.retranslate())
            new_window.show()
        except (OpenCanceled, ValueError, sqlite3.Error, OSError, ImportError, RuntimeError) as exc:
            if new_window is not None:
                new_window.deleteLater()
            if candidate is not None:
                candidate.close()
            self.launcher.set_busy(False)
            self.loading = False
            if old_window is not None:
                old_window.setEnabled(True)
                self.launcher.hide()
            if not isinstance(exc, OpenCanceled):
                QMessageBox.warning(
                    old_window or self.launcher, tr("Nie można otworzyć bazy"), str(exc)
                )
            return
        self.window = new_window
        self.last_path = path
        self.settings.setValue("last_database", str(path))
        self.settings.sync()
        if old_window is not None:
            old_window.close()
            old_window.deleteLater()
        self.launcher.set_busy(False)
        self.launcher.set_last_path(path)
        self.launcher.hide()
        self.loading = False
        if self.settings.status() != QSettings.Status.NoError:
            QMessageBox.warning(
                self.window,
                tr("Ustawienia"),
                tr(
                    "Otwarto bazę, ale nie udało się zapamiętać jej ścieżki na następne uruchomienie."
                ),
            )
