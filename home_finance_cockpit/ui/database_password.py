"""Password management for an individual database, independent of preferences."""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from home_finance_cockpit.localization import tr
from home_finance_cockpit.storage.encryption import validate_password


class DatabasePasswordDialog(QDialog):
    def __init__(self, parent, *, encrypted=False, remove=False):
        super().__init__(parent)
        self.remove = remove
        self.setWindowTitle(
            tr(
                "Usuń hasło bazy"
                if remove
                else "Zmień hasło bazy"
                if encrypted
                else "Ustaw hasło bazy"
            )
        )
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.current = QLineEdit()
        self.new = QLineEdit()
        self.confirm = QLineEdit()
        for field in (self.current, self.new, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(1024)
        if encrypted:
            form.addRow(tr("Aktualne hasło:"), self.current)
        if not remove:
            form.addRow(tr("Nowe hasło:"), self.new)
            form.addRow(tr("Powtórz hasło:"), self.confirm)
        notice = QLabel(
            tr(
                "Usunięcie hasła wyłączy szyfrowanie pliku bazy."
                if remove
                else "Minimum 8 znaków. Hasło szyfruje plik bazy. Utraconego hasła nie można odzyskać."
            )
        )
        notice.setWordWrap(True)
        root.addWidget(notice)
        self.error = QLabel()
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        (self.current if encrypted else self.new).setFocus()

    def validate(self):
        if not self.remove:
            try:
                validate_password(self.new.text())
                if self.new.text() != self.confirm.text():
                    raise ValueError(tr("Wpisane hasła nie są identyczne."))
            except ValueError as exc:
                self.error.setText(str(exc))
                return
        self.accept()

    def clear_passwords(self):
        for field in (self.current, self.new, self.confirm):
            field.clear()
