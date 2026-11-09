"""Savings goal list with an inline editor and explicit contribution actions."""

import sqlite3

from PyQt6.QtCore import QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label, money_minor
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px


class SavingsGoalsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.records = []
        self.selected_id = None
        self.editor = None
        self.baseline = None
        self.loading = False
        self.creating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left, content = panel()
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj celu…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.status_filter = QComboBox()
        for caption, key in (
            ("Wszystkie", "all"),
            ("W trakcie", "active"),
            ("Cel osiągnięty", "complete"),
        ):
            self.status_filter.addItem(tr(caption), key)
        self.search.textChanged.connect(self.refresh_list)
        self.status_filter.currentIndexChanged.connect(self.refresh_list)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.status_filter)
        content.addLayout(filters)
        self.goal_list = QListWidget()
        self.goal_list.setSpacing(4)
        self.goal_list.setStyleSheet(
            "QListWidget {background:transparent; border:0;} QListWidget::item {border:1px solid transparent; border-bottom-color:#24394D; border-radius:5px;} QListWidget::item:selected {background:#15475b; border:1px solid #22D3EE;}"
        )
        self.goal_list.currentItemChanged.connect(self.select_item)
        content.addWidget(self.goal_list, 1)
        self.splitter.addWidget(left)
        right, content = panel()
        self.right = right
        content.setContentsMargins(18, 18, 18, 18)
        content.setSpacing(16)
        head = QHBoxLayout()
        self.goal_icon = label("")
        head.addWidget(self.goal_icon)
        self.title = label("", "section")
        head.addWidget(self.title, 1)
        self.title.setStyleSheet("font-size:24px; font-weight:600;")
        self.edit_button = QPushButton(tr("Edytuj"))
        self.edit_button.setIcon(icon("edit"))
        self.edit_button.clicked.connect(self.edit)
        self.delete_button = QPushButton(tr("Usuń cel"))
        self.delete_button.setIcon(icon("trash"))
        self.delete_button.setProperty("role", "danger")
        self.delete_button.clicked.connect(self.delete)
        head.addWidget(self.edit_button)
        head.addWidget(self.delete_button)
        content.addLayout(head)
        summary, box = panel()
        summary_head = QHBoxLayout()
        saved = QVBoxLayout()
        saved.addWidget(label(tr("Zebrano / cel")))
        self.saved_label = label("", "section")
        saved.addWidget(self.saved_label)
        remaining = QVBoxLayout()
        remaining.addWidget(label(tr("Pozostało")))
        self.remaining_label = label("", "section")
        remaining.addWidget(self.remaining_label)
        self.saved_label.setStyleSheet("font-size:22px; font-weight:600;")
        self.remaining_label.setStyleSheet("font-size:20px; font-weight:600;")
        summary_head.addLayout(saved, 2)
        summary_head.addLayout(remaining, 1)
        box.addLayout(summary_head)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 10000)
        self.progress.setTextVisible(False)
        self.percent = label("", "section")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.percent)
        box.addLayout(progress_row)
        self.progress.setFixedHeight(22)
        self.percent.setStyleSheet("font-size:16px;")
        self.deadline_label = label("")
        box.addWidget(self.deadline_label)
        content.addWidget(summary)
        self.detail_tabs = QTabBar()
        self.detail_tabs.addTab(tr("Szczegóły"))
        self.detail_tabs.setExpanding(False)
        content.addWidget(self.detail_tabs)
        from home_finance_cockpit.ui.theme import display_color

        background = display_color("#0B1623")
        border = display_color("#24394D")
        accent = display_color("#22D3EE")
        text = display_color("#EDF4FF")
        muted = display_color("#A8BED5")
        self.detail_tabs.setDrawBase(False)
        self.detail_tabs.setStyleSheet(
            "QTabBar::tab {background:transparent; color:"
            + muted
            + "; border:0; border-bottom:3px solid transparent; padding:10px 26px; margin:0; min-width:100px;} QTabBar::tab:selected {background:"
            + display_color("#112233")
            + "; color:"
            + text
            + "; border-bottom:3px solid "
            + accent
            + "; font-weight:600;}"
        )
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget {background:transparent;}"
        )
        inner = QWidget()
        body = QHBoxLayout(inner)
        body.setContentsMargins(0, 8, 0, 0)
        self.form_host = QWidget()
        self.form_layout = QVBoxLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.form_host, 3)
        self.contribution, box = panel("Szybka wpłata")
        box.addWidget(label(tr("Kwota")))
        amount_row = QHBoxLayout()
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.amount_currency = label("")
        from home_finance_cockpit.ui.amount_field import CurrencySuffix

        self.amount_suffix = CurrencySuffix(self.amount)
        self.amount_currency.hide()
        self.field_style = (
            "QLineEdit, QComboBox, QDateEdit {background:"
            + background
            + "; color:"
            + text
            + "; border:1px solid "
            + border
            + "; border-radius:5px; padding:6px 10px;} QLineEdit:focus, QComboBox:focus, QDateEdit:focus {border-color:"
            + accent
            + ";}"
        )
        self.amount.setStyleSheet(self.field_style)
        self.amount.setMinimumHeight(36)
        amount_row.addWidget(self.amount, 1)
        box.addLayout(amount_row)
        self.contribute_button = QPushButton(tr("Dodaj kwotę"))
        self.contribute_button.setIcon(icon("plus"))
        self.contribute_button.setProperty("role", "primary")
        self.contribute_button.clicked.connect(self.apply_contribution)
        self.contribute_button.setMinimumHeight(38)
        box.addWidget(self.contribute_button)
        box.addWidget(label(tr("Kwota ujemna koryguje wcześniejsze wpłaty.")))
        body.addWidget(self.contribution, 2, Qt.AlignmentFlag.AlignTop)
        self.editor_scroll.setWidget(inner)
        content.addWidget(self.editor_scroll, 1)
        self.hint = label("")
        content.addWidget(self.hint)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton(tr("Anuluj zmiany"))
        self.cancel_button.clicked.connect(self.cancel)
        self.save_button = QPushButton(tr("Zapisz zmiany"))
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        content.addLayout(buttons)
        self.splitter.addWidget(right)
        self.splitter.setSizes([350, 800])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)
        self.refresh()

    def record(self):
        return next((g for g in self.records if g["id"] == self.selected_id), None)

    def snapshot(self):
        if not self.editor:
            return None
        e = self.editor
        return (
            e.name.text(),
            e.mode.currentData(),
            e.wallet.currentData(),
            e.currency.currentData(),
            e.target.text(),
            e.allocated.text(),
            e.has_deadline.isChecked(),
            e.deadline.date().toString("yyyy-MM-dd"),
        )

    def dirty(self):
        return self.editor is not None and self.snapshot() != self.baseline

    def guard_pending(self):
        if not self.dirty():
            return True
        answer = QMessageBox.question(
            self,
            tr("Niezapisane zmiany"),
            tr("Zapisać zmiany celu przed przejściem dalej?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        self.cancel()
        return True

    def refresh(self):
        self.records = self.db.savings_goals()
        self.refresh_list(sync_editor=False)
        if not self.dirty() and not self.creating:
            self.load_editor(self.record())

    def refresh_list(self, *_, sync_editor=True):
        from home_finance_cockpit.ui.savings_goals import goal_status

        terms = normalize(self.search.text()).split()
        mode = self.status_filter.currentData()
        rows = [
            g
            for g in self.records
            if all(t in normalize(g["name"]) for t in terms)
            and (mode == "all" or (g["funded_minor"] >= g["target_minor"]) == (mode == "complete"))
        ]
        previous_id = self.selected_id
        with QSignalBlocker(self.goal_list):
            self.goal_list.clear()
            selected = None
            for goal in rows:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, goal["id"])
                self.goal_list.addItem(item)
                card = QWidget()
                card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                card.setStyleSheet("background:transparent;")
                card_layout = QHBoxLayout(card)
                glyph = label("")
                glyph.setPixmap(
                    icon(
                        "wallet" if goal["calculation_mode"] == "wallet" else "target", size=30
                    ).pixmap(30, 30)
                )
                card_layout.addWidget(glyph)
                fields = QVBoxLayout()
                top = QHBoxLayout()
                top.addWidget(label(goal["name"], "section"), 1)
                badge = label(goal_status(goal))
                completed = goal["funded_minor"] >= goal["target_minor"]
                badge.setStyleSheet(
                    "QLabel {color:"
                    + ("#D8B4FE" if completed else "#55E8FF")
                    + "; background:"
                    + ("#302347" if completed else "#153B4D")
                    + "; border:1px solid "
                    + ("#69458A" if completed else "#246075")
                    + "; border-radius:8px; padding:3px 6px;}"
                )
                top.addWidget(badge)
                fields.addLayout(top)
                fields.addWidget(
                    label(
                        amount_label(goal["funded_minor"])
                        + " / "
                        + amount_label(goal["target_minor"], goal["currency"])
                    )
                )
                bar_row = QHBoxLayout()
                bar = QProgressBar()
                bar.setRange(0, 10000)
                percent = min(10000, 10000 * goal["funded_minor"] // goal["target_minor"])
                bar.setValue(percent)
                bar.setTextVisible(False)
                bar_row.addWidget(bar, 1)
                bar_row.addWidget(label(f"{percent / 100:.2f}%"))
                fields.addLayout(bar_row)
                card_layout.addLayout(fields, 1)
                self.goal_list.setItemWidget(item, card)
                card.ensurePolished()
                card_layout.activate()
                item.setSizeHint(QSize(px(300), max(px(120), card.minimumSizeHint().height())))
                if goal["id"] == self.selected_id:
                    selected = item
            if selected:
                self.goal_list.setCurrentItem(selected)
            elif not self.dirty() and not self.creating:
                self.selected_id = rows[0]["id"] if rows else None
                if rows:
                    self.goal_list.setCurrentRow(0)
        if sync_editor and self.selected_id != previous_id:
            self.load_editor(self.record())

    def select_item(self, item, previous):
        if self.loading or item is None:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if identifier == self.selected_id and not self.creating:
            return
        if not self.guard_pending():
            with QSignalBlocker(self.goal_list):
                self.goal_list.setCurrentItem(previous)
            return
        self.selected_id = identifier
        self.creating = False
        self.load_editor(self.record())

    def load_editor(self, record, new=False):
        from home_finance_cockpit.ui.savings_goals import GoalDialog

        self.loading = True
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.editor = None
        self.baseline = None
        self.right.setEnabled(bool(record) or new)
        if record is None and not new:
            self.title.setText(tr("Brak celów oszczędnościowych"))
            self.saved_label.clear()
            self.remaining_label.clear()
            self.progress.setValue(0)
            self.percent.clear()
            self.deadline_label.clear()
            self.loading = False
            return
        self.editor = GoalDialog(self.form_host, self.db, record)
        self.editor.setWindowFlags(Qt.WindowType.Widget)
        self.editor.setMinimumWidth(0)
        self.editor.setStyleSheet("QDialog {background:transparent;}" + self.field_style)
        self.editor.buttons.hide()
        self.editor.hint.hide()
        self.editor.form.setContentsMargins(0, 0, 12, 0)
        self.editor.form.setVerticalSpacing(14)
        for field in (
            self.editor.name,
            self.editor.mode,
            self.editor.currency,
            self.editor.wallet,
            self.editor.target,
            self.editor.allocated,
            self.editor.deadline,
        ):
            field.setMinimumHeight(36)
        self.form_layout.addWidget(self.editor)
        self.form_layout.addStretch()
        self.title.setText(record["name"] if record else tr("Nowy cel"))
        self.goal_icon.setPixmap(
            icon(
                "wallet" if record and record["calculation_mode"] == "wallet" else "target", size=32
            ).pixmap(32, 32)
        )
        self.delete_button.setEnabled(record is not None)
        self.edit_button.setEnabled(record is not None)
        self.amount.clear()
        self.detail_tabs.setCurrentIndex(0)
        e = self.editor
        for field in (e.name, e.target, e.allocated):
            field.textChanged.connect(self.update_preview)
        for field in (e.mode, e.wallet, e.currency):
            field.currentIndexChanged.connect(self.update_preview)
        e.has_deadline.toggled.connect(self.update_preview)
        e.deadline.dateChanged.connect(self.update_preview)
        self.baseline = self.snapshot()
        self.loading = False
        self.update_preview()

    def update_preview(self, *_):
        if self.loading or not self.editor:
            return
        e = self.editor
        manual = e.mode.currentData() == "manual"
        record = self.record()
        currency = (
            e.currency.currentData()
            if manual
            else e.wallet_currencies.get(e.wallet.currentData(), "")
        )
        try:
            target = money_minor(e.target.text())
            saved = (
                money_minor(e.allocated.text())
                if manual
                else max(
                    0,
                    next(
                        (
                            w["balance"]
                            for w in self.db.wallet_balances()
                            if w["id"] == e.wallet.currentData()
                        ),
                        0,
                    ),
                )
            )
            valid = target > 0 and saved >= 0
        except ValueError:
            target, saved, valid = 0, 0, False
        self.saved_label.setText(
            amount_label(saved) + " / " + amount_label(target, currency) if valid else "—"
        )
        self.remaining_label.setText(
            amount_label(max(0, target - saved), currency) if valid else "—"
        )
        percent = min(10000, 10000 * saved // target) if valid else 0
        self.progress.setValue(percent)
        self.percent.setText(f"{percent / 100:.2f}%")
        self.deadline_label.setText(
            tr("Termin celu") + ": " + format_date(e.deadline.date().toString("yyyy-MM-dd"))
            if e.has_deadline.isChecked()
            else tr("Bez terminu")
        )
        self.contribution.setVisible(manual)
        self.contribute_button.setEnabled(manual and record is not None and not self.creating)
        self.amount_currency.setText(currency or "")
        self.amount_suffix.set_currency(currency)
        self.hint.setText(
            tr(
                "Kwoty dodajesz ręcznie, niezależnie od sald portfeli. Kwota ujemna koryguje wpłatę."
            )
            if manual
            else tr("Postęp odpowiada bieżącemu saldu wybranego portfela.")
        )

    def save(self):
        if not self.editor:
            return False
        e = self.editor
        try:
            identifier = self.db.save_savings_goal(
                e.name.text(),
                e.wallet.currentData(),
                e.target.text(),
                e.allocated.text(),
                e.deadline.date().toString("yyyy-MM-dd") if e.has_deadline.isChecked() else None,
                None if self.creating else self.selected_id,
                calculation_mode=e.mode.currentData(),
                currency=e.currency.currentData(),
            )
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return False
        self.selected_id = identifier
        self.creating = False
        self.baseline = self.snapshot()
        self.records = self.db.savings_goals()
        self.load_editor(self.record())
        self.refresh()
        self.changed.emit()
        return True

    def add(self):
        if not self.guard_pending():
            return
        self.creating = True
        self.selected_id = None
        with QSignalBlocker(self.goal_list):
            self.goal_list.clearSelection()
        self.load_editor(None, new=True)
        self.editor.name.setFocus()

    def edit(self):
        if self.editor:
            self.editor.name.setFocus()
            self.editor.name.selectAll()

    def cancel(self):
        self.creating = False
        if not self.record() and self.records:
            self.selected_id = self.records[0]["id"]
        self.load_editor(self.record())
        self.refresh_list()

    def apply_contribution(self):
        record = self.record()
        if not record or self.creating:
            return
        if self.dirty():
            QMessageBox.information(
                self,
                tr("Niezapisane zmiany"),
                tr("Zapisz lub anuluj zmiany celu przed dodaniem kwoty."),
            )
            return
        try:
            self.db.add_goal_amount(record["id"], self.amount.text())
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.amount.clear()
        self.baseline = self.snapshot()
        self.refresh()
        self.changed.emit()

    def delete(self):
        record = self.record()
        if not record:
            return
        if (
            QMessageBox.question(
                self, tr("Usuń cel"), tr("Usunąć wybrane cele? Pieniądze pozostaną w portfelach.")
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.db.delete("savings_goals", [record["id"]])
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.selected_id = None
        self.creating = False
        self.baseline = self.snapshot()
        self.refresh()
        self.changed.emit()
