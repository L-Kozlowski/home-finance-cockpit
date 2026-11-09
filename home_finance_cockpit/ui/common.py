"""Small reusable Qt widgets and error handling."""

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.text_halo import MoneyGlowDelegate


def show_error(parent, error):
    if isinstance(error, sqlite3.IntegrityError):
        if "UNIQUE" in str(error):
            message = "Taka nazwa, kod lub reguła już istnieje. Wybierz inną wartość."
        elif "FOREIGN KEY" in str(error):
            message = "Nie można wykonać operacji: rekord jest używany przez transakcje, portfele, cele oszczędnościowe, reguły lub historię importów."
        else:
            message = "Dane nie spełniają wymagań bazy. Sprawdź wprowadzone wartości."
    else:
        message = str(error)
    QMessageBox.warning(parent, tr("Nie udało się wykonać operacji"), tr(message))


class CopyTableWidget(QTableWidget):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            indexes = [
                index for index in self.selectedIndexes() if not self.isColumnHidden(index.column())
            ]
            if indexes:
                values = {
                    (i.row(), i.column()): str(i.data()) if i.data() is not None else ""
                    for i in indexes
                }
                rows = sorted({i.row() for i in indexes})
                columns = sorted(
                    {i.column() for i in indexes}, key=self.horizontalHeader().visualIndex
                )
                QApplication.clipboard().setText(
                    "\n".join(
                        "\t".join(values.get((row, col), "") for col in columns) for row in rows
                    )
                )
            event.accept()
            return
        super().keyPressEvent(event)


def table(headers):
    widget = CopyTableWidget(0, len(headers))
    widget.setItemDelegate(MoneyGlowDelegate(widget))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(px(30))
    widget.horizontalHeader().setMinimumSectionSize(50)
    return widget


def fill_table(widget, rows, ids=None, *, resize_columns=True):
    widget.setSortingEnabled(False)
    widget.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            header = widget.horizontalHeaderItem(col)
            if header and any(
                word in header.text().casefold() for word in ("kwota", "saldo", "suma sald")
            ):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                from home_finance_cockpit.ui.theme import RED, SUCCESS, display_color

                item.setForeground(
                    QColor(display_color(RED if str(value).startswith("-") else SUCCESS))
                )
            if ids is not None:
                item.setData(Qt.ItemDataRole.UserRole, ids[row])
            widget.setItem(row, col, item)
    if resize_columns:
        widget.resizeColumnsToContents()


def selected_ids(widget):
    return [
        widget.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        for index in widget.selectionModel().selectedRows()
    ]


class FormDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(tr(title))
        self.setMinimumWidth(440)
        self.form = QFormLayout(self)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)

    def finish(self):
        self.form.addRow(self.buttons)

    def persist(self):
        raise NotImplementedError

    def save(self):
        try:
            self.persist()
        except (ValueError, sqlite3.Error, OSError) as exc:
            show_error(self, exc)
        else:
            self.accept()
