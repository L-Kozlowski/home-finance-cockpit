"""Explicit editors avoid saving partially edited table rows."""

from datetime import date
from decimal import Decimal

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.categories import RULE_MODES, category_name, column_label
from home_finance_cockpit.domain.validation import amount_label, money_minor
from home_finance_cockpit.domain.wallet_icons import WALLET_ICONS
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.calendar import MonthCalendar
from home_finance_cockpit.ui.color_picker import ColorPicker
from home_finance_cockpit.ui.common import FormDialog
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.icon_picker import WalletIconDialog


def date_editor(value):
    widget = QDateEdit(QDate.fromString(value, "yyyy-MM-dd"))
    widget.setCalendarPopup(True)
    widget.setCalendarWidget(MonthCalendar(widget))
    widget.setDisplayFormat("yyyy-MM-dd")
    widget.setMinimumDate(QDate(1, 1, 1))
    widget.setMaximumDate(QDate(9999, 12, 31))
    return widget


def select_data(combo, value):
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


class WalletDialog(FormDialog):
    def __init__(self, parent, db, record=None):
        super().__init__(parent, "Edytuj portfel" if record else "Dodaj portfel")
        self.db, self.record = db, record
        self.icon_name = record["icon_name"] if record else "wallet"
        self.icon_button = QPushButton(tr(WALLET_ICONS[self.icon_name]))
        self.icon_button.setIcon(icon(self.icon_name))
        self.icon_button.clicked.connect(self.choose_icon)
        self.name = QLineEdit(record["name"] if record else "")
        self.balance = QLineEdit(amount_label(record["opening_minor"]) if record else "0.00")
        self.currency = QComboBox()
        for cur in db.currencies():
            self.currency.addItem(tr("{v0} ({v1})", v0=cur["code"], v1=cur["symbol"]), cur["code"])
        select_data(self.currency, record["currency"] if record else "PLN")
        self.day = date_editor(
            record["opening_date"] if record else date.today().replace(day=1).isoformat()
        )
        self.form.addRow(tr("Nazwa:"), self.name)
        self.form.addRow(tr("Ikona:"), self.icon_button)
        self.form.addRow(tr("Waluta (2 miejsca dziesiętne):"), self.currency)
        self.form.addRow(tr("Saldo przed pierwszą operacją:"), self.balance)
        self.form.addRow(tr("Obowiązuje od:"), self.day)
        note = QLabel(
            tr("Wybierz datę nie późniejszą niż najstarsza transakcja, którą chcesz importować.")
        )
        note.setWordWrap(True)
        self.form.addRow(note)
        self.finish()

    def persist(self):
        self.db.save_wallet(
            self.name.text(),
            self.balance.text(),
            self.currency.currentData(),
            self.day.date().toString("yyyy-MM-dd"),
            self.record["id"] if self.record else None,
            icon_name=self.icon_name,
        )

    def choose_icon(self):
        dialog = WalletIconDialog(self, self.icon_name)
        if dialog.exec():
            self.icon_name = dialog.selected_icon
            self.icon_button.setIcon(icon(self.icon_name))
            self.icon_button.setText(tr(WALLET_ICONS[self.icon_name]))


class TransactionDialog(FormDialog):
    def __init__(self, parent, db, record=None):
        super().__init__(parent, "Edytuj transakcję" if record else "Dodaj transakcję")
        self.db, self.record = db, record
        self.wallet = QComboBox()
        for w in db.wallets():
            self.wallet.addItem(tr("{v0} ({v1})", v0=w["name"], v1=w["currency"]), w["id"])
        self.kind = QComboBox()
        self.kind.addItem(tr("Wydatek"), -1)
        self.kind.addItem(tr("Wpływ"), 1)
        from home_finance_cockpit.domain.analysis_kinds import ANALYSIS_KINDS

        self.analysis_kind = QComboBox()
        for key, title in ANALYSIS_KINDS.items():
            self.analysis_kind.addItem(tr(title), key)
        if record:
            select_data(self.analysis_kind, record["analysis_kind"])
        self.amount = QLineEdit(amount_label(abs(record["amount_minor"])) if record else "")
        self.category = QComboBox()
        self.category.addItem(tr("Automatycznie / do przypisania"), None)
        for c in db.categories():
            self.category.addItem(c["display_name"], c["id"])
        self.counterparty = QLineEdit(record["from_to"] if record else "")
        self.description = QPlainTextEdit(record["description"] if record else "")
        self.description.setMaximumHeight(100)
        self.day = date_editor(record["date"] if record else date.today().isoformat())
        if record:
            select_data(self.wallet, record["wallet_id"])
            select_data(self.kind, 1 if record["amount_minor"] > 0 else -1)
            select_data(
                self.category,
                record["category_id"] if record["category_source"] in ("manual", "bank") else None,
            )
        self.form.addRow(tr("Portfel:"), self.wallet)
        self.form.addRow(tr("Typ:"), self.kind)
        self.form.addRow(tr("Charakter transakcji:"), self.analysis_kind)
        self.form.addRow(tr("Kwota bez znaku:"), self.amount)
        self.form.addRow(tr("Data:"), self.day)
        self.form.addRow(tr("Kontrahent:"), self.counterparty)
        self.form.addRow(tr("Kategoria:"), self.category)
        self.form.addRow(tr("Opis:"), self.description)
        self.finish()

    def persist(self):
        from home_finance_cockpit.services.categorization import classify

        minor = money_minor(self.amount.text())
        if minor <= 0:
            raise ValueError(tr("Wpisz dodatnią kwotę, a kierunek operacji wybierz w polu Typ."))
        category = self.category.currentData()
        source, matched, conflict = "manual", None, False
        if category is None:
            data = dict(self.record) if self.record is not None else {}
            data.update(
                description=self.description.toPlainText(),
                from_to=self.counterparty.text(),
                date=self.day.date().toString("yyyy-MM-dd"),
                currency=self.db.wallet(self.wallet.currentData())["currency"],
            )
            matched, conflict = classify(data, self.db.rules())
            category = matched["category_id"] if matched else self.db.default_category_id()
            source = "rule" if matched else "unassigned"
        with self.db.transaction():
            record_id = self.db.save_transaction(
                self.wallet.currentData(),
                Decimal(minor * self.kind.currentData()) / 100,
                category,
                self.description.toPlainText(),
                self.day.date().toString("yyyy-MM-dd"),
                self.counterparty.text(),
                self.record["id"] if self.record else None,
                source=source,
                analysis_kind=self.analysis_kind.currentData(),
            )
            self.db.set_classification_details(
                record_id, matched["id"] if matched else None, conflict
            )


class CategoryDialog(FormDialog):
    def __init__(self, parent, db, record=None, parent_id=None):
        super().__init__(parent, "Kategoria")
        self.db, self.record = db, record
        self.name = QLineEdit(record["name"] if record else "")
        if record is not None and record["is_default"]:
            self.name.setText(category_name(record))
            self.name.setReadOnly(True)
        self.parent_category = QComboBox()
        self.parent_category.addItem(tr("Brak — kategoria"), None)
        for category in db.categories():
            if (
                category["parent_id"] is None
                and not category["is_default"]
                and (record is None or category["id"] != record["id"])
            ):
                self.parent_category.addItem(category["name"], category["id"])
        select_data(self.parent_category, record["parent_id"] if record else parent_id)
        if record is not None and record["is_default"]:
            self.parent_category.setEnabled(False)
        self.form.addRow(tr("Kategoria nadrzędna:"), self.parent_category)
        self.form.addRow(tr("Nazwa:"), self.name)
        self.color = ColorPicker()
        self.color.set_value(record["color"] if record else None)
        self.form.addRow(tr("Kolor kategorii 1:"), self.color)
        self.color_note = QLabel(
            tr(
                "Podkategorie dziedziczą kolor kategorii nadrzędnej. Brak koloru pozostawia neutralną tabelę."
            )
        )
        self.color_note.setWordWrap(True)
        self.form.addRow(self.color_note)
        self.icon_name = record["icon_name"] if record else "tag"
        self.icon_button = QPushButton(tr("Wybierz ikonę kategorii"))
        self.icon_button.clicked.connect(self.choose_category_icon)
        self.form.addRow(tr("Ikona:"), self.icon_button)
        self.color.color_changed.connect(self.preview_category_icon)
        self.name.textChanged.connect(self.preview_category_icon)
        self.parent_category.currentIndexChanged.connect(self.update_color_state)
        self.update_color_state()
        self.finish()
        self.name.setFocus(Qt.FocusReason.OtherFocusReason)
        self.name.selectAll()

    def persist(self):
        self.db.save_category(
            self.name.text(),
            self.record["id"] if self.record else None,
            parent_id=self.parent_category.currentData(),
            color=self.color.value if self.parent_category.currentData() is None else None,
            icon_name=self.icon_name if self.parent_category.currentData() is None else "tag",
        )

    def category_icon_color(self):
        from home_finance_cockpit.reports.presentation import category_color

        parent = self.parent_category.currentData()
        row = self.db.category(parent) if parent else None
        return (
            category_color(row["name"], {row["name"]: row["color"]})
            if row
            else category_color(self.name.text(), {self.name.text(): self.color.value})
        )

    def preview_category_icon(self, *_):
        self.icon_button.setIcon(icon(self.icon_name, self.category_icon_color()))

    def choose_category_icon(self):
        if self.parent_category.currentData() is not None:
            return
        from home_finance_cockpit.ui.icon_picker import CategoryIconDialog

        dialog = CategoryIconDialog(self, self.icon_name, self.category_icon_color())
        if dialog.exec():
            self.icon_name = dialog.selected_icon
            self.preview_category_icon()

    def update_color_state(self):
        self.color.setEnabled(self.parent_category.currentData() is None)
        self.form.setRowVisible(self.color, self.parent_category.currentData() is None)
        self.form.setRowVisible(self.icon_button, self.parent_category.currentData() is None)
        self.preview_category_icon()


class CurrencyDialog(FormDialog):
    def __init__(self, parent, db, record=None):
        super().__init__(parent, "Waluta")
        self.db, self.record = db, record
        self.code = QLineEdit(record["code"] if record else "")
        self.symbol = QLineEdit(record["symbol"] if record else "")
        self.form.addRow(tr("Kod (3 litery):"), self.code)
        self.form.addRow(tr("Symbol / nazwa:"), self.symbol)
        records = db.rate_records()
        rate = next((r for r in records if record and r["code"] == record["code"]), {})
        self.rate_mode = QComboBox()
        self.rate_mode.addItem(tr("API"), "api")
        self.rate_mode.addItem(tr("Kurs ręczny"), "manual")
        select_data(self.rate_mode, rate.get("mode", "api"))
        self.manual_rate = QLineEdit(rate.get("manual_rate") or "")
        self.form.addRow(tr("Źródło kursu:"), self.rate_mode)
        self.api_currency = QComboBox()
        self.api_currency.setMinimumContentsLength(20)
        self.api_currency.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.api_status = QLabel()
        self.form.addRow(tr("Waluta z API NBP:"), self.api_currency)
        self.form.addRow(self.api_status)
        from home_finance_cockpit.services.currency_catalog import CurrencyCatalog

        self.catalog = CurrencyCatalog(self)
        self.catalog.updated.connect(self.populate_api_currencies)
        self.api_currency.currentIndexChanged.connect(self.select_api_currency)
        self.rate_mode.currentIndexChanged.connect(self.update_api_visibility)
        self.selected_quote = None
        self.populate_api_currencies()
        self.form.addRow(tr("Kurs ręczny / zastępczy:"), self.manual_rate)
        self.form.addRow(
            QLabel(
                tr(
                    "PLN za 1 jednostkę waluty. W trybie API pusta wartość oznacza brak ręcznego kursu zastępczego."
                )
            )
        )
        self._rate_code = self.code.text().strip().upper()
        self.code.textChanged.connect(self.update_rate_state)
        self.update_rate_state()
        self.update_api_visibility()
        self.form.addRow(
            QLabel(tr("Aktualnie obsługiwane są kwoty z dwoma miejscami dziesiętnymi."))
        )
        self.finish()

    def persist(self):
        with self.db.transaction():
            self.db.save_currency(
                self.code.text(), self.symbol.text(), self.record["id"] if self.record else None
            )
            code = self.code.text().strip().upper()
            if code != "PLN":
                self.db.save_rate_config(
                    code, self.rate_mode.currentData(), self.manual_rate.text().strip()
                )
            if (
                self.rate_mode.currentData() == "api"
                and self.selected_quote
                and self.selected_quote["code"] == code
            ):
                self.db.store_quote(code, self.selected_quote["rate"], self.selected_quote["date"])

    def showEvent(self, event):
        super().showEvent(event)
        if self.rate_mode.currentData() == "api":
            self.catalog.start()
            self.populate_api_currencies()

    def populate_api_currencies(self):
        from PyQt6.QtCore import QSignalBlocker

        previous = self.api_currency.currentData()
        with QSignalBlocker(self.api_currency):
            self.api_currency.clear()
            self.api_currency.addItem(tr("Wybierz walutę…"), None)
            for code, row in sorted(self.catalog.rows.items()):
                self.api_currency.addItem(code + " — " + row["name"], code)
            self.api_currency.setCurrentIndex(max(0, self.api_currency.findData(previous)))
        self.api_status.setText(
            tr("Pobieranie listy walut…")
            if self.catalog.pending
            else tr("Lista walut NBP jest niedostępna. Możesz wpisać dane ręcznie.")
            if not self.catalog.rows
            else tr("Wybór uzupełnia pola. Możesz je później edytować.")
        )

    def select_api_currency(self, *_):
        code = self.api_currency.currentData()
        row = self.catalog.rows.get(code)
        if not row:
            return
        self.selected_quote = row
        self.code.setText(code)
        self.symbol.setText(row["name"])
        self.manual_rate.setText(row["rate"])

    def update_api_visibility(self, *_):
        automatic = self.rate_mode.currentData() == "api"
        self.form.setRowVisible(self.api_currency, automatic)
        self.form.setRowVisible(self.api_status, automatic)
        if automatic and self.isVisible():
            self.catalog.start()
            self.populate_api_currencies()

    def update_rate_state(self):
        code = self.code.text().strip().upper()
        if code != self._rate_code:
            self._rate_code = code
        foreign = code != "PLN"
        self.rate_mode.setEnabled(foreign)
        self.manual_rate.setEnabled(foreign)


class RuleDialog(FormDialog):
    def __init__(self, parent, db, record=None, category_id=None):
        super().__init__(parent, "Reguła kategoryzacji")
        self.db, self.record = db, record
        self.category = QComboBox()
        for c in db.categories():
            if not c["is_default"]:
                self.category.addItem(c["display_name"], c["id"])
        select_data(self.category, category_id)
        self.column = QComboBox()
        for key in db.rule_columns():
            self.column.addItem(column_label(key), key)
        self.mode = QComboBox()
        for key, label in RULE_MODES.items():
            self.mode.addItem(tr(label), key)
        self.pattern = QLineEdit(record["pattern"] if record else "")
        if record:
            select_data(self.category, record["category_id"])
            if self.column.findData(record["column_name"]) < 0:
                self.column.setPlaceholderText(tr("Wybierz pole aplikacji"))
            self.column.setCurrentIndex(self.column.findData(record["column_name"]))
            select_data(self.mode, record["mode"])
        self.form.addRow(tr("Kategoria:"), self.category)
        self.form.addRow(tr("Pole:"), self.column)
        self.form.addRow(tr("Dopasowanie:"), self.mode)
        self.form.addRow(tr("Tekst / wzorzec:"), self.pattern)
        self.conditions = []
        self.extra_content = QWidget()
        self.extra_layout = QVBoxLayout(self.extra_content)
        self.extra_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.extra_scroll = QScrollArea()
        self.extra_scroll.setWidgetResizable(True)
        self.extra_scroll.setWidget(self.extra_content)
        self.extra_scroll.setMaximumHeight(230)
        self.form.addRow(self.extra_scroll)
        self.add_condition_button = QPushButton(tr("+ Dodaj warunek (ORAZ)"))
        self.add_condition_button.clicked.connect(lambda: self.add_condition())
        self.form.addRow(self.add_condition_button)
        if record:
            from home_finance_cockpit.domain.categories import rule_conditions

            for condition in rule_conditions(record)[1:]:
                self.add_condition(condition)
        self.extra_scroll.setVisible(bool(self.conditions))
        self.setSizeGripEnabled(True)
        self.resize(780, 380)
        self.finish()

    def add_condition(self, condition=None):
        if len(self.conditions) >= 11:
            return
        condition = condition or dict(
            column_name=self.column.currentData(), mode="not_contains", pattern=""
        )
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        column, mode, pattern = QComboBox(), QComboBox(), QLineEdit(condition["pattern"])
        for key in self.db.rule_columns():
            column.addItem(column_label(key), key)
        if column.findData(condition["column_name"]) < 0:
            column.setPlaceholderText(tr("Wybierz pole aplikacji"))
        for key, caption in RULE_MODES.items():
            mode.addItem(tr(caption), key)
        column.setCurrentIndex(column.findData(condition["column_name"]))
        select_data(mode, condition["mode"])
        remove = QPushButton("−")
        entry = (row, column, mode, pattern)
        remove.clicked.connect(lambda: self.remove_condition(entry))
        for widget in (QLabel(tr("ORAZ")), column, mode, pattern, remove):
            layout.addWidget(widget)
        self.extra_layout.addWidget(row)
        self.conditions.append(entry)
        self.extra_scroll.show()
        self.extra_scroll.setFixedHeight(min(230, max(55, len(self.conditions) * 45)))
        self.add_condition_button.setEnabled(len(self.conditions) < 11)

    def remove_condition(self, entry):
        self.conditions.remove(entry)
        self.extra_layout.removeWidget(entry[0])
        entry[0].deleteLater()
        self.extra_scroll.setVisible(bool(self.conditions))
        self.extra_scroll.setFixedHeight(min(230, max(55, len(self.conditions) * 45)))
        self.add_condition_button.setEnabled(True)

    def persist(self):
        if self.category.currentData() is None:
            raise ValueError(tr("Najpierw dodaj kategorię inną niż domyślna."))
        self.db.save_rule(
            self.category.currentData(),
            self.column.currentData(),
            self.pattern.text(),
            self.mode.currentData(),
            self.record["id"] if self.record else None,
            conditions=[
                dict(column_name=c.currentData(), mode=m.currentData(), pattern=p.text())
                for _, c, m, p in self.conditions
            ],
        )
