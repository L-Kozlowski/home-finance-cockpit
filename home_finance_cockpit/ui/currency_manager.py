"""Embedded currency definitions and exchange-rate settings."""

import sqlite3

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.common import fill_table, selected_ids, show_error, table
from home_finance_cockpit.ui.editors import CurrencyDialog


class CurrencyManagerPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent, db, service=None):
        super().__init__(parent)
        self.db = db
        self.service = service
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for label, action in (
            ("Dodaj", self.add),
            ("Edytuj", self.edit),
            ("Usuń zaznaczone", self.delete),
        ):
            button = QPushButton(tr(label))
            button.clicked.connect(action)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        from home_finance_cockpit.ui.exchange_settings import ExchangeSettings

        self.exchange_settings = ExchangeSettings(db, service)
        layout.addWidget(self.exchange_settings)
        self.table = table(
            [
                tr(s)
                for s in (
                    "Kod",
                    "Symbol",
                    "Kurs do PLN",
                    "Tryb",
                    "Źródło kursu",
                    "Data kursu",
                    "Pobrano",
                    "Błąd API",
                )
            ]
        )
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.table)
        self.refresh()
        if service is not None:
            service.changed.connect(self.refresh)

    def notify_changed(self):
        self.refresh()
        if self.service is not None:
            self.service.start()
        self.changed.emit()

    def refresh(self):
        self.exchange_settings.refresh_status()
        from home_finance_cockpit.ui.chart_dates import format_date
        from home_finance_cockpit.ui.exchange_settings import RATE_SOURCES, rate_timestamp

        self.records = self.db.rate_records()
        rows = []
        for r in self.records:
            rate, source = self.db.effective_rate(r["code"])
            rows.append(
                [
                    r["code"],
                    r["symbol"],
                    str(rate) if rate is not None else "—",
                    tr("API") if r["mode"] == "api" and r["code"] != "PLN" else tr("Kurs ręczny"),
                    tr(RATE_SOURCES[source]),
                    format_date(r["quote_date"])
                    if r["quote_date"] and source in ("api", "cached")
                    else "—",
                    rate_timestamp(r["fetched_at"]) if source in ("api", "cached") else "—",
                    r["last_error"],
                ]
            )
        fill_table(self.table, rows, [r["id"] for r in self.records])
        for row, record in enumerate(self.records):
            self.table.item(row, 7).setToolTip(record["last_error"])

    def add(self):
        if CurrencyDialog(self, self.db).exec():
            self.notify_changed()

    def edit(self):
        ids = selected_ids(self.table)
        if len(ids) != 1:
            QMessageBox.information(self, tr("Edycja"), tr("Wybierz jeden rekord."))
            return
        record = next(r for r in self.records if r["id"] == ids[0])
        if CurrencyDialog(self, self.db, record).exec():
            self.notify_changed()

    def delete(self):
        ids = selected_ids(self.table)
        if not ids:
            QMessageBox.information(self, tr("Usuwanie"), tr("Zaznacz rekordy do usunięcia."))
            return
        if (
            QMessageBox.question(self, tr("Usuwanie"), tr("Usunąć {v0} rekordów?", v0=len(ids)))
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete("currencies", ids)
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
        self.notify_changed()
