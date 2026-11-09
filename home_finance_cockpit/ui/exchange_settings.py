"""Per-database automatic FX schedule and immediate refresh."""

from datetime import datetime

from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout, QWidget

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.chart_dates import format_timestamp
from home_finance_cockpit.ui.components import label

RATE_SOURCES = {
    "base": "Stały kurs bazowy",
    "api": "NBP",
    "manual": "Kurs ręczny",
    "fallback": "Ręczny kurs zastępczy",
    "cached": "Ostatni zapisany kurs NBP",
    "missing": "Brak kursu",
}


def rate_timestamp(value):
    return (
        format_timestamp(datetime.fromisoformat(value).astimezone().isoformat()) if value else "—"
    )


class ExchangeSettings(QWidget):
    def __init__(self, db, service=None):
        super().__init__()
        self.db, self.service = db, service
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        config = db.exchange_config()
        self.enabled = QCheckBox(tr("Automatycznie aktualizuj kursy"))
        self.enabled.setChecked(bool(config["enabled"]))
        self.hours = QSpinBox()
        self.hours.setRange(1, 720)
        self.hours.setValue(config["interval_hours"])
        row.addWidget(self.enabled)
        row.addWidget(label(tr("Co ile godzin:")))
        row.addWidget(self.hours)
        self.refresh_button = QPushButton(tr("Odśwież teraz"))
        self.refresh_button.setEnabled(service is not None and not service.busy)
        row.addStretch()
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.status = label("")
        layout.addWidget(self.status)
        layout.addWidget(
            label(
                tr(
                    "NBP · kurs średni: PLN za 1 jednostkę waluty. Kurs ręczny i zastępczy ustawisz przy edycji waluty."
                )
            )
        )
        self.refresh_button.clicked.connect(self.refresh_now)
        if service is not None:
            service.changed.connect(self.refresh_status)
            service.busy_changed.connect(self.busy_changed)
        self.refresh_status()

    def busy_changed(self, busy):
        self.refresh_button.setEnabled(not busy)
        self.refresh_status()

    def refresh_status(self):
        config = self.db.exchange_config()
        available = any(r["code"] != "PLN" and r["mode"] == "api" for r in self.db.rate_records())
        self.refresh_button.setEnabled(bool(self.service and not self.service.busy and available))
        self.status.setText(
            tr("Brak walut w trybie API.")
            if not available
            else tr("Pobieranie kursów…")
            if self.service and self.service.busy
            else tr("Ostatnia próba: {time}", time=rate_timestamp(config["last_attempt"]))
            if config["last_attempt"]
            else tr("Kursy nie były jeszcze pobierane.")
        )

    def refresh_now(self):
        if self.service:
            self.service.refresh_now()

    def save(self):
        self.db.save_exchange_config(self.enabled.isChecked(), self.hours.value())
        if self.service:
            self.service.start()
