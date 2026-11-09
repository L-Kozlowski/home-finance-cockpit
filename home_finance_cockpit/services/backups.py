"""Scheduled SQLite snapshots, published only after a successful integrity check."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from home_finance_cockpit.localization import tr


class BackupService(QObject):
    changed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, db, preferences, parent=None):
        super().__init__(parent)
        self.db, self.preferences = db, preferences
        self.last_error = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)

    def start(self):
        self.timer.start(1000)

    def stop(self):
        self.timer.stop()

    def last_backup(self):
        value = self.preferences.get("last_backup_time")
        path = str(self.preferences.get("last_backup_path"))
        try:
            stamp = datetime.fromisoformat(str(value))
            if stamp.tzinfo is None or not Path(path).is_file():
                return None
            return stamp
        except (ValueError, TypeError):
            return None

    def next_backup(self):
        enabled, interval, folder = self.preferences.backup_config()
        if not enabled or self.db.path == ":memory:":
            return None
        last = self.last_backup()
        if (
            last is None
            or Path(str(self.preferences.get("last_backup_path"))).parent != Path(folder).resolve()
        ):
            return datetime.now(timezone.utc)
        return last + timedelta(seconds=interval)

    def check_due(self):
        self.timer.setInterval(60000)
        due = self.next_backup()
        if due is not None and due <= datetime.now(timezone.utc):
            try:
                self.create_backup()
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.last_error = str(exc)
                self.changed.emit()
                self.failed.emit(self.last_error)

    def create_backup(self, folder=None):
        enabled, interval, configured_folder = self.preferences.backup_config()
        folder = Path(
            self.preferences.validate_backup(
                False, interval, configured_folder if folder is None else folder
            )
        )
        if self.db.conn.in_transaction:
            raise ValueError(
                tr("Trwa zapis do bazy. Spróbuj wykonać kopię po zakończeniu operacji.")
            )
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc)
        name = Path(self.db.path).stem if self.db.path != ":memory:" else "memory"
        target = folder / f"{name}_{stamp.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:12]}.db"
        temporary = target.with_suffix(".partial")
        try:
            self.db.backup(temporary)
            self.db.verify_backup(temporary)
            temporary.rename(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        self.preferences.settings.setValue(
            self.preferences.key + "last_backup_time", stamp.isoformat()
        )
        self.preferences.settings.setValue(self.preferences.key + "last_backup_path", str(target))
        self.preferences.sync()
        self.last_error = ""
        self.changed.emit()
        return target
