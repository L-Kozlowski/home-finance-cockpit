"""Draft category/report edits for the selected transaction."""

import sqlite3

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.analysis_kinds import ANALYSIS_KINDS
from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.review import save_review
from home_finance_cockpit.ui.color_picker import ColorPicker
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.components import label
from home_finance_cockpit.ui.scaling import px


class TransactionInspector(QWidget):
    saved = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.current, self.loading = db, None, False
        self.classify = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(px(16), px(14), px(16), px(14))
        layout.setSpacing(px(12))
        header = QHBoxLayout()
        header.addWidget(label(tr("Szczegóły transakcji"), "section"), 1)
        close = QPushButton(tr("×"))
        close.setToolTip(tr("Zamknij szczegóły"))
        close.clicked.connect(self.request_close)
        header.addWidget(close)
        layout.addLayout(header)
        self.empty = label(
            tr("Wybierz transakcję z tabeli, aby zobaczyć szczegóły i przypisać kategorię.")
        )
        layout.addWidget(self.empty)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(px(12))
        self.title, self.description = label("", "section"), label("")
        self.amount = QLabel()
        body.addWidget(self.title)
        body.addWidget(self.description)
        body.addWidget(self.amount)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.day, self.wallet = label(""), label("")
        self.root, self.child = QComboBox(), QComboBox()
        self.analysis_kind = QComboBox()
        for key, title in ANALYSIS_KINDS.items():
            self.analysis_kind.addItem(tr(title), key)
        self.color = ColorPicker()
        self.report = QCheckBox(tr("Uwzględniaj w raportach"))
        self.source, self.rule, self.status = label(""), label(""), label("")
        for caption, widget in (
            ("Data", self.day),
            ("Portfel", self.wallet),
            ("Kategoria", self.root),
            ("Podkategoria", self.child),
            ("Kolor kategorii", self.color),
        ):
            form.addRow((tr(caption) + ":"), widget)
        body.addLayout(form)
        form.addRow(tr("Charakter transakcji:"), self.analysis_kind)
        body.addWidget(
            label(
                tr(
                    "Zwroty i rozliczenia oznaczaj przy wpływach. Ustaw im kategorię zwracanego wydatku. Pensja nie pomniejsza kosztów."
                )
            )
        )
        body.addWidget(label(tr("Kolor dotyczy całej kategorii, także w analizach i raportach.")))
        body.addWidget(self.report)
        for title, value in (("Źródło", self.source), ("Reguła", self.rule), ("Stan", self.status)):
            body.addWidget(label(tr(title), "section"))
            body.addWidget(value)
        self.confirm_category = QPushButton(tr("Potwierdź wybraną kategorię"))
        self.confirm_category.clicked.connect(self.resolve_conflict)
        body.addWidget(self.confirm_category)
        body.addStretch()
        actions = QHBoxLayout()
        self.cancel_button, self.save_button = (
            QPushButton(tr("Anuluj")),
            QPushButton(tr("Zapisz zmiany")),
        )
        self.save_button.setProperty("role", "primary")
        self.cancel_button.clicked.connect(self.reload)
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        body.addLayout(actions)
        layout.addWidget(self.content, 1)
        self.content.hide()
        self.root.currentIndexChanged.connect(self.root_changed)
        self.child.currentIndexChanged.connect(self.category_changed)
        self.color.color_changed.connect(self.update_dirty)
        self.report.toggled.connect(self.update_dirty)
        self.analysis_kind.currentIndexChanged.connect(self.update_dirty)

    @property
    def transaction_id(self):
        return self.current["id"] if self.current else None

    def state(self):
        return (
            self.child.currentData() or self.root.currentData(),
            self.report.isChecked(),
            self.color.value,
            self.classify,
            self.analysis_kind.currentData(),
        )

    def dirty(self):
        return self.current is not None and self.state() != self.baseline

    def update_dirty(self, *_):
        if not self.loading:
            self.save_button.setEnabled(self.dirty())
            self.cancel_button.setEnabled(self.dirty())

    def category_changed(self, *_):
        if not self.loading:
            self.classify = True
            self.update_dirty()

    def root_changed(self, *_):
        selected = self.root.currentData()
        root = next((c for c in self.categories if c["id"] == selected), None)
        with QSignalBlocker(self.child):
            self.child.clear()
            self.child.addItem(tr("Brak podkategorii"), None)
            for child in self.categories:
                if child["parent_id"] == selected:
                    self.child.addItem(child["name"], child["id"])
        self.expected_color = root["color"] if root else None
        self.color.set_value(self.expected_color)
        self.category_changed()

    def load(self, record, *, force=False):
        if not force and self.dirty() and self.transaction_id == record["id"]:
            return
        self.loading = True
        self.current = dict(record)
        self.categories = [dict(c) for c in self.db.categories()]
        with QSignalBlocker(self.root):
            self.root.clear()
            for category in self.categories:
                if category["parent_id"] is None:
                    self.root.addItem(category["name"], category["id"])
            self.root.setCurrentIndex(max(0, self.root.findData(record["root_category_id"])))
        self.root_changed()
        with QSignalBlocker(self.child):
            self.child.setCurrentIndex(max(0, self.child.findData(record["category_id"])))
        self.report.setChecked(bool(record["include_in_reports"]))
        self.analysis_kind.setCurrentIndex(
            max(0, self.analysis_kind.findData(record["analysis_kind"]))
        )
        self.title.setText(record["description"] or record["from_to"] or "Transakcja")
        self.description.setText((record["from_to"] if record["description"] else ""))
        value = amount_label(record["amount_minor"], record["currency"])
        self.amount.setText((("+" if record["amount_minor"] > 0 else "") + value))
        from home_finance_cockpit.ui.theme import RED, SUCCESS, display_color

        self.amount.setStyleSheet(
            f"font-size:{px(25)}px; font-weight:600; color:{display_color(SUCCESS if record['amount_minor'] > 0 else RED)}"
        )
        self.day.setText(record["date"])
        self.wallet.setText(record["wallet"])
        imported = self.db.execute(
            "SELECT file_name,imported_at FROM imports WHERE id=?", (record["import_id"],)
        ).fetchone()
        from home_finance_cockpit.ui.chart_dates import format_timestamp

        self.source.setText(
            (
                tr(
                    "Import pliku · {v0}\n{v1}",
                    v0=imported["file_name"],
                    v1=format_timestamp(imported["imported_at"]),
                )
                if imported
                else (
                    tr("Wpis ręczny")
                    if record["raw_json"] is None
                    else tr("Import pliku · brak wpisu w historii")
                )
            )
        )
        rule = self.db.execute(
            "SELECT * FROM rules WHERE id=?", (record["matched_rule_id"],)
        ).fetchone()
        from home_finance_cockpit.domain.categories import describe_rule
        from home_finance_cockpit.services.conflicts import annotate_conflicts

        annotated = next(
            (
                r
                for r in annotate_conflicts(self.db.transactions(), self.db.rules())
                if r["id"] == record["id"]
            ),
            dict(record),
        )
        self.rule.setText((describe_rule(rule) if rule else tr("Brak przypisanej reguły")))
        self.status.setText(
            annotated.get("conflict_explanation")
            or {
                "rule": tr("Przypisano regułą"),
                "bank": tr("Kategoria z pliku"),
                "manual": tr("Przypisano ręcznie"),
                "unassigned": tr("Bez przypisanej kategorii"),
            }[record["category_source"]]
        )
        self.confirm_category.setVisible(bool(record["category_conflict"]))
        self.classify = False
        self.baseline = self.state()
        self.loading = False
        self.empty.hide()
        self.content.show()
        self.update_dirty()

    def clear(self):
        self.current = None
        self.content.hide()
        self.empty.show()

    def reload(self):
        rows = self.db.transactions(transaction_id=self.transaction_id) if self.current else []
        if rows:
            self.load(rows[0], force=True)
        else:
            self.clear()

    def resolve_conflict(self):
        self.classify = True
        self.update_dirty()

    def save(self):
        if self.current is None:
            return True
        category_id, included, color, classify, analysis_kind = self.state()
        try:
            save_review(
                self.db,
                self.transaction_id,
                category_id,
                included,
                color,
                classify=classify,
                expected=self.current,
                expected_color=self.expected_color,
                analysis_kind=analysis_kind,
            )
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return False
        self.reload()
        self.saved.emit()
        return True

    def guard_pending(self):
        if not self.dirty():
            return True
        choice = QMessageBox.question(
            self,
            tr("Niezapisane zmiany"),
            tr("Zapisać zmiany w szczegółach transakcji?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self.save()
        if choice == QMessageBox.StandardButton.Discard:
            self.reload()
            return True
        return False

    def request_close(self):
        if self.guard_pending():
            self.close_requested.emit()
