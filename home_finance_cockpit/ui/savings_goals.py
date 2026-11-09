"""Savings goal editing and overview progress for wallet and manual goals."""

from datetime import date

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.common import FormDialog
from home_finance_cockpit.ui.components import label


class GoalDialog(FormDialog):
    def __init__(self, parent, db, record=None):
        super().__init__(parent, "Cel oszczędnościowy")
        self.db, self.record = db, record
        self.name = QLineEdit(record["name"] if record else "")
        self.mode = QComboBox()
        self.mode.addItem(tr("Saldo portfela"), "wallet")
        self.mode.addItem(tr("Ręczne dodawanie kwot"), "manual")
        if record:
            self.mode.setCurrentIndex(self.mode.findData(record["calculation_mode"]))
        self.currency = QComboBox()
        for c in db.currencies():
            self.currency.addItem(c["code"], c["code"])
        self.currency.setCurrentIndex(
            max(0, self.currency.findData(record["currency"] if record else "PLN"))
        )
        self.wallet = QComboBox()
        for w in db.wallet_balances():
            self.wallet.addItem(
                f"{w['name']} · {amount_label(w['balance'], w['currency'])}", w["id"]
            )
        if record:
            self.wallet.setCurrentIndex(self.wallet.findData(record["wallet_id"]))
        self.target = QLineEdit(amount_label(record["target_minor"]) if record else "")
        self.allocated = QLineEdit(amount_label(record["allocated_minor"]) if record else "0.00")
        from home_finance_cockpit.ui.amount_field import CurrencySuffix

        self.target_currency = CurrencySuffix(self.target)
        self.allocated_currency = CurrencySuffix(self.allocated)
        self.has_deadline = QCheckBox(tr("Termin celu"))
        self.deadline = QDateEdit(
            QDate.fromString(record["deadline"], "yyyy-MM-dd")
            if record and record["deadline"]
            else QDate.currentDate().addYears(1)
        )
        self.deadline.setCalendarPopup(True)
        from home_finance_cockpit.ui.calendar import MonthCalendar

        self.deadline.setCalendarWidget(MonthCalendar(self.deadline))
        self.deadline.setMinimumDate(QDate(1, 1, 1))
        self.deadline.setMaximumDate(QDate(9999, 12, 31))
        from home_finance_cockpit.ui.chart_dates import get_date_format

        self.deadline.setDisplayFormat(get_date_format())
        self.has_deadline.setChecked(bool(record and record["deadline"]))
        self.deadline.setEnabled(self.has_deadline.isChecked())
        self.has_deadline.toggled.connect(self.deadline.setEnabled)
        self.form.addRow(tr("Nazwa:"), self.name)
        self.form.addRow(tr("Sposób liczenia:"), self.mode)
        self.form.addRow(tr("Portfel:"), self.wallet)
        self.form.addRow(tr("Waluta:"), self.currency)
        self.form.addRow(tr("Kwota docelowa:"), self.target)
        self.form.addRow(tr("Zebrana kwota:"), self.allocated)
        self.form.addRow(self.has_deadline, self.deadline)
        self.hint = label("")
        self.form.addRow(self.hint)
        self.wallet_currencies = {w["id"]: w["currency"] for w in db.wallets()}
        self.last_currency = record["currency"] if record else None
        self.wallet.currentIndexChanged.connect(self.wallet_changed)
        self.currency.currentIndexChanged.connect(self.wallet_changed)
        self.mode.currentIndexChanged.connect(self.wallet_changed)
        self.wallet_changed()
        self.finish()

    def wallet_changed(self):
        automatic = self.mode.currentData() == "wallet"
        self.form.setRowVisible(self.wallet, automatic)
        self.form.setRowVisible(self.currency, not automatic)
        self.form.setRowVisible(self.allocated, not automatic)
        currency = (
            self.wallet_currencies.get(self.wallet.currentData())
            if automatic
            else self.currency.currentData()
        )
        self.target_currency.set_currency(currency)
        self.allocated_currency.set_currency(currency)
        if self.last_currency is not None and currency != self.last_currency:
            self.target.clear()
            self.allocated.setText("0.00")
        self.last_currency = currency
        self.hint.setText(
            tr("Postęp odpowiada bieżącemu saldu wybranego portfela.")
            if automatic
            else tr(
                "Kwoty dodajesz ręcznie, niezależnie od sald portfeli. Kwota ujemna koryguje wpłatę."
            )
        )

    def persist(self):
        self.db.save_savings_goal(
            self.name.text(),
            self.wallet.currentData(),
            self.target.text(),
            self.allocated.text(),
            self.deadline.date().toString("yyyy-MM-dd") if self.has_deadline.isChecked() else None,
            self.record["id"] if self.record else None,
            calculation_mode=self.mode.currentData(),
            currency=self.currency.currentData(),
        )


def goal_status(goal):
    if goal["funded_minor"] >= goal["target_minor"]:
        return tr("Cel osiągnięty")
    if goal["deadline"] and goal["deadline"] < date.today().isoformat():
        return tr("Po terminie")
    return tr("W trakcie")


class GoalSummary(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.rows = QVBoxLayout(self)

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        goals = self.db.savings_goals()
        if not goals:
            self.rows.addWidget(label(tr("Brak celów oszczędnościowych")))
        for goal in sorted(
            goals,
            key=lambda g: (
                g["funded_minor"] >= g["target_minor"],
                g["deadline"] or "9999",
                g["id"],
            ),
        )[:3]:
            self.rows.addWidget(label(goal["name"], "section"))
            self.rows.addWidget(
                label(
                    amount_label(goal["funded_minor"], goal["currency"])
                    + " / "
                    + amount_label(goal["target_minor"], goal["currency"])
                )
            )
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(min(100, 100 * goal["funded_minor"] // goal["target_minor"]))
            progress.setTextVisible(True)
            progress.setFormat("%p%")
            progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rows.addWidget(progress)
        self.rows.addStretch()
