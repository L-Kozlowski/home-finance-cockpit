"""Independent transaction filter state edited through the shared modal dialog."""

from PyQt6.QtCore import QDate, QSignalBlocker
from PyQt6.QtWidgets import QComboBox, QDateEdit, QLineEdit, QWidget

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.periods import PERIOD_PRESETS, period_range


class TransactionFilters(QWidget):
    def __init__(self, db, refresh, parent):
        super().__init__(parent)
        self.db, self.callback = db, refresh
        self.selected_wallet_ids = set()
        self.amount_min, self.amount_max = QLineEdit(self), QLineEdit(self)
        self.currency, self.wallet, self.preset = (QComboBox(self) for _ in range(3))
        self.start, self.end = (
            QDateEdit(QDate.currentDate().addMonths(-1), self),
            QDateEdit(QDate.currentDate(), self),
        )
        for caption, value in PERIOD_PRESETS:
            self.preset.addItem(tr(caption), value)
        self.currency.currentIndexChanged.connect(self.currency_changed)
        self.wallet.currentIndexChanged.connect(self.wallet_changed)
        for signal in (
            self.preset.currentIndexChanged,
            self.start.dateChanged,
            self.end.dateChanged,
        ):
            signal.connect(self.refresh_transactions)
        self.hide()

    def refresh_choices(self):
        current = self.currency.currentData()
        with QSignalBlocker(self.currency):
            self.currency.clear()
            for code in sorted({w["currency"] for w in self.db.wallets()}) or ["PLN"]:
                self.currency.addItem(code, code)
            self.currency.setCurrentIndex(max(0, self.currency.findData(current or "PLN")))
        self.populate_wallets()

    def populate_wallets(self):
        current = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(tr("Wszystkie w tej walucie"), None)
            for wallet in self.db.wallets():
                if wallet["currency"] == self.currency.currentData():
                    self.wallet.addItem(icon(wallet["icon_name"]), wallet["name"], wallet["id"])
            self.wallet.setCurrentIndex(max(0, self.wallet.findData(current)))
        available = {self.wallet.itemData(i) for i in range(1, self.wallet.count())}
        self.selected_wallet_ids.intersection_update(available)
        with QSignalBlocker(self.wallet):
            self.wallet.setCurrentIndex(
                self.wallet.findData(next(iter(self.selected_wallet_ids)))
                if len(self.selected_wallet_ids) == 1
                else 0
            )

    def wallet_changed(self):
        value = self.wallet.currentData()
        self.selected_wallet_ids = {value} if value is not None else set()
        self.refresh_transactions()

    def currency_changed(self):
        self.populate_wallets()
        self.refresh_transactions()

    def refresh_transactions(self, *_):
        self.callback()

    def period(self):
        return period_range(self.preset.currentData(), self.start.date(), self.end.date())

    def summary(self):
        scope = self.preset.currentText()
        if self.preset.currentData() == "custom":
            scope = f"{self.start.date().toString('yyyy-MM-dd')} — {self.end.date().toString('yyyy-MM-dd')}"
        from home_finance_cockpit.ui.filters import category_summary

        wallet = (
            tr("Wybrano: {count}", count=len(self.selected_wallet_ids))
            if len(self.selected_wallet_ids) > 1
            else self.wallet.currentText()
        )
        return f"{self.currency.currentText()} · {wallet} · {scope}" + category_summary(self)
