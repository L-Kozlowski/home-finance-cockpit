"""Searchable, paginated import register and file drop target."""

import sqlite3
from datetime import date, timedelta
from math import ceil
from pathlib import Path

from PyQt6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.chart_dates import format_timestamp
from home_finance_cockpit.ui.common import selected_ids, show_error, table
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import ACCENT, RED, display_color
from home_finance_cockpit.ui.transactions_page import SortableItem
from home_finance_cockpit.ui.wallet_destination import WalletDestinationDialog


def import_file_extension(name):
    # Excel import names include the selected sheet after the filename.
    direct = Path(str(name)).suffix.lstrip(".").upper()
    if direct in ("CSV", "XLSX", "XLSM", "XLS"):
        return direct
    filename = str(name).rsplit(" [", 1)[0]
    suffix = Path(filename).suffix.lstrip(".").upper()
    return suffix if suffix in ("CSV", "XLSX", "XLSM", "XLS") else ""


class ImportDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        adjusted = QStyleOptionViewItem(option)
        if index.column() == 0:
            self.initStyleOption(adjusted, index)
            adjusted.text = adjusted.fontMetrics.elidedText(
                str(index.data()),
                Qt.TextElideMode.ElideMiddle,
                max(20, option.rect.width() - px(112)),
            )
            style = option.widget.style() if option.widget else self.parent().style()
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, adjusted, painter, option.widget
            )
        else:
            super().paint(painter, option, index)
        painter.save()
        painter.setPen(QColor(display_color("#24394D")))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor(display_color(ACCENT)), 1))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            if index.column() == 0:
                painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())
            if index.column() == 5:
                painter.drawLine(option.rect.topRight(), option.rect.bottomRight())
        if index.column() == 0:
            suffix = import_file_extension(index.data())
            if suffix:
                badge = option.rect.adjusted(option.rect.width() - px(62), 0, -px(10), 0)
                badge.setTop(option.rect.center().y() - px(11))
                badge.setHeight(px(22))
                painter.fillRect(badge, QColor(display_color("#1E3347")))
                painter.setPen(QColor(display_color("#A8BED5")))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, suffix)
        painter.restore()


class DropArea(QPushButton):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.setAcceptDrops(True)
        self.setMinimumHeight(px(100))
        self.setIcon(icon("upload"))
        self.setIconSize(QSize(px(32), px(32)))
        self.setText(tr("Przeciągnij pliki CSV lub Excel tutaj") + "\n" + tr("lub wybierz pliki"))
        self.clicked.connect(lambda: host.import_csv())
        self.setObjectName("importDropArea")

    def dragEnterEvent(self, event):
        from home_finance_cockpit.ui.import_dialog import ImportDialog

        if ImportDialog.dropped_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        from home_finance_cockpit.ui.import_dialog import ImportDialog

        paths = ImportDialog.dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.host.import_csv(paths)
        else:
            event.ignore()


class ImportHistoryPage(QWidget):
    def __init__(self, db, host):
        super().__init__()
        self.db = db
        self.host = host
        self.records = []
        self.filtered = []
        self.page = 0
        self.page_size = 11
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(12))
        controls, box = panel()
        row = QHBoxLayout()
        box.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj importów…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        row.addWidget(self.search, 2)
        self.wallet = QComboBox()
        self.period = QComboBox()
        wallet_icon = label("")
        wallet_icon.setPixmap(icon("wallet").pixmap(px(20), px(20)))
        row.addWidget(wallet_icon)
        row.addWidget(label(tr("Portfel:")))
        row.addWidget(self.wallet, 1)
        date_icon = label("")
        date_icon.setPixmap(icon("calendar").pixmap(px(20), px(20)))
        row.addWidget(date_icon)
        row.addWidget(label(tr("Zaimportowano:")))
        row.addWidget(self.period, 1)
        for caption, value in [
            ("Wszystkie daty", "all"),
            ("Ostatnie 7 dni", "week"),
            ("Ostatnie 30 dni", "month"),
            ("Bieżący rok", "year"),
        ]:
            self.period.addItem(tr(caption), value)
        layout.addWidget(controls)
        strip, box = panel()
        box.setContentsMargins(px(14), px(8), px(14), px(8))
        self.summary = label("")
        box.addWidget(self.summary)
        layout.addWidget(strip)
        register, box = panel()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.table = table(
            [
                tr(s)
                for s in (
                    "Plik",
                    "Portfel",
                    "Dodano łącznie",
                    "Obecne transakcje",
                    "Usuń",
                    "Data importu",
                )
            ]
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setItemDelegate(ImportDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(px(44))
        self.table.horizontalHeader().setMinimumHeight(px(44))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, px(55))
        self.table.setColumnWidth(0, px(350))
        self.table.setIconSize(QSize(px(22), px(22)))
        self.table.horizontalHeader().setSortIndicator(5, Qt.SortOrder.DescendingOrder)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.sort_changed)
        self.table.viewport().installEventFilter(self)
        box.addWidget(self.table, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(px(16), px(14), px(16), px(14))
        self.selection = label("")
        self.selection.setWordWrap(False)
        footer.addWidget(self.selection, 1)
        self.view = QPushButton(tr("Zobacz transakcje"))
        self.view.clicked.connect(self.open_transactions)
        footer.addWidget(self.view)
        self.move = QPushButton(tr("Zmień portfel importu"))
        self.move.clicked.connect(self.move_selected_import)
        footer.addWidget(self.move)
        self.previous = QPushButton()
        self.previous.setText(tr("Poprzednie"))
        self.previous.clicked.connect(lambda: self.change_page(self.page - 1))
        footer.addWidget(self.previous)
        self.page_label = label("")
        footer.addWidget(self.page_label)
        self.next = QPushButton()
        self.next.setText(tr("Następne"))
        self.next.clicked.connect(lambda: self.change_page(self.page + 1))
        footer.addWidget(self.next)
        self.range = label("")
        footer.addWidget(self.range)
        box.addLayout(footer)
        layout.addWidget(register, 1)
        self.drop = DropArea(host)
        layout.addWidget(self.drop)
        self.search.textChanged.connect(self.filter_records)
        self.wallet.currentIndexChanged.connect(self.filter_records)
        self.period.currentIndexChanged.connect(self.filter_records)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_transactions())

    def refresh(self):
        self.records = list(self.db.import_history())
        selected = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(tr("Wszystkie portfele"), None)
            for wallet in self.db.wallets():
                self.wallet.addItem(icon(wallet["icon_name"]), wallet["name"], wallet["id"])
            self.wallet.setCurrentIndex(max(0, self.wallet.findData(selected)))
        self.apply_style()
        self.filter_records(reset=False)

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.resize_register)
        return super().eventFilter(watched, event)

    def resize_register(self):
        width = self.table.viewport().width()
        for col, fraction in enumerate((0.30, 0.18, 0.11, 0.16, 0.05, 0.20)):
            self.table.setColumnWidth(col, max(px(45), int(width * fraction)))
        self.table.verticalHeader().setDefaultSectionSize(
            max(px(44), self.table.viewport().height() // self.page_size)
        )

    def apply_style(self):
        bg = display_color("#0B1623")
        border = display_color("#24394D")
        surface = display_color("#112233")
        selected = display_color("#153B4D")
        self.setStyleSheet(
            "QLineEdit,QComboBox {background:"
            + bg
            + ";border:1px solid "
            + border
            + ";padding:9px;border-radius:5px;} QTableWidget {background:"
            + surface
            + ";border:0;} QTableWidget::item {padding:8px;} QTableWidget::item:selected {background:"
            + selected
            + ";} QHeaderView::section {background:"
            + display_color("#1E3347")
            + ";padding:12px;border:0;border-right:1px solid "
            + border
            + ";font-weight:600;} QPushButton#importDropArea {min-height:80px;background:"
            + bg
            + ";border:1px dashed "
            + border
            + ";border-radius:5px;}"
        )

    def filter_records(self, *_, reset=True):
        terms = normalize(self.search.text()).split()
        wallet = self.wallet.currentData()
        period = self.period.currentData()
        today = date.today()
        start = {
            "week": today - timedelta(days=6),
            "month": today - timedelta(days=29),
            "year": today.replace(month=1, day=1),
        }.get(period)
        self.filtered = [
            r
            for r in self.records
            if (wallet is None or r["wallet_id"] == wallet)
            and (start is None or str(r["imported_at"])[:10] >= start.isoformat())
            and all(t in normalize(r["file_name"] + " " + r["wallet"]) for t in terms)
        ]
        if reset:
            self.page = 0
        self.summary.setText(
            tr(
                "Importy: {v0}   |   Transakcje: {v1}   |   Portfele: {v2}",
                v0=len(self.filtered),
                v1=sum(r["current_count"] for r in self.filtered),
                v2=len({r["wallet_id"] for r in self.filtered}),
            )
        )
        self.render()

    def change_page(self, index):
        self.page = max(0, min(index, max(0, ceil(len(self.filtered) / self.page_size) - 1)))
        self.render()

    def sort_changed(self, *_):
        self.page = 0
        self.render()

    def render(self):
        selection = selected_ids(self.table)
        self.page = min(self.page, max(0, ceil(len(self.filtered) / self.page_size) - 1))
        wallets = {w["id"]: w for w in self.db.wallets()}
        header = self.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        keys = {0: "file_name", 1: "wallet", 2: "row_count", 3: "current_count", 5: "imported_at"}
        key = keys.get(sort_col, "id")
        self.filtered.sort(
            key=lambda r: (r[key], r["id"]), reverse=sort_order == Qt.SortOrder.DescendingOrder
        )
        visible = self.filtered[self.page * self.page_size : (self.page + 1) * self.page_size]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, record in enumerate(visible):
            values = [
                record["file_name"],
                record["wallet"],
                record["row_count"],
                record["current_count"],
                "",
                format_timestamp(record["imported_at"]),
            ]
            for col, value in enumerate(values):
                key = record["imported_at"] if col == 5 else value
                item = SortableItem(str(value), record["id"], key)
                self.table.setItem(row, col, item)
                if col == 0:
                    item.setIcon(icon("file", display_color("#EDF4FF")))
                    item.setToolTip(record["file_name"])
                if col == 1:
                    item.setIcon(icon(wallets[record["wallet_id"]]["icon_name"]))
                if col in (2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            delete = QToolButton()
            delete.setIcon(icon("trash", RED))
            delete.setToolTip(
                tr(
                    "Usuń import i jego transakcje: {v0} ({v1})",
                    v0=record["file_name"],
                    v1=record["current_count"],
                )
            )
            delete.setFixedSize(px(32), px(32))
            delete.setIconSize(QSize(px(18), px(18)))
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setStyleSheet(
                "QToolButton {background:transparent;border:1px solid transparent;border-radius:5px;padding:0;min-width:0;min-height:0;}"
                f"QToolButton:hover {{background:{display_color('#482c3b')};border-color:{display_color(RED)};}}"
                f"QToolButton:pressed {{background:{display_color('#613043')};}}"
            )
            delete.clicked.connect(
                lambda checked=False, identifier=record["id"]: self.host.delete_import_transactions(
                    identifier
                )
            )
            cell = QWidget()
            centered = QHBoxLayout(cell)
            centered.setContentsMargins(0, 0, 0, 0)
            centered.addWidget(delete, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row, 4, cell)
            if record["id"] in selection:
                self.table.selectRow(row)
        self.table.setSortingEnabled(True)
        if sort_col >= 0:
            self.table.sortItems(sort_col, sort_order)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled((self.page + 1) * self.page_size < len(self.filtered))
        self.page_label.setText(
            f"{self.page + 1} / {max(1, ceil(len(self.filtered) / self.page_size))}"
        )
        self.range.setText(
            f"{self.page * self.page_size + 1 if visible else 0}–{self.page * self.page_size + len(visible)} / {len(self.filtered)}"
        )
        self.resize_register()
        self.update_selection()

    def update_selection(self):
        ids = selected_ids(self.table)
        record = next((r for r in self.records if r["id"] in ids), None)
        self.selection.setText(tr("Wybrano: {v0}", v0=record["file_name"]) if record else "")
        self.view.setEnabled(record is not None)
        self.move.setEnabled(len(ids) == 1)

    def move_selected_import(self):
        identifiers = selected_ids(self.table)
        record = next(
            (r for r in self.records if len(identifiers) == 1 and r["id"] == identifiers[0]), None
        )
        if record is None or not self.host.transaction_page.inspector.guard_pending():
            return
        currency = self.db.wallet(record["wallet_id"])["currency"]
        choices = [
            w
            for w in self.db.wallets()
            if w["currency"] == currency and w["id"] != record["wallet_id"]
        ]
        if not choices:
            show_error(self, tr("Utwórz inny portfel w tej samej walucie."))
            return
        dialog = WalletDestinationDialog(
            self, tr("Zmień portfel importu"), choices, count=record["current_count"]
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    self.db.move_import(record["id"], dialog.wallet_id)
                except (ValueError, sqlite3.Error) as exc:
                    show_error(self, exc)
                    return
                self.host.refresh_ui()
        finally:
            dialog.deleteLater()

    def open_transactions(self):
        ids = selected_ids(self.table)
        record = next((r for r in self.records if r["id"] in ids), None)
        if record is None or not self.host.transaction_page.inspector.guard_pending():
            return
        filters = self.host.transaction_filters
        wallet = self.db.wallet(record["wallet_id"])
        with (
            QSignalBlocker(filters.currency),
            QSignalBlocker(filters.wallet),
            QSignalBlocker(filters.preset),
            QSignalBlocker(self.host.transaction_search),
        ):
            filters.currency.setCurrentIndex(filters.currency.findData(wallet["currency"]))
            filters.populate_wallets()
            filters.wallet.setCurrentIndex(filters.wallet.findData(wallet["id"]))
            filters.selected_wallet_ids = {wallet["id"]}
            filters.preset.setCurrentIndex(filters.preset.findData("all"))
            filters.selected_category_ids = set()
            self.host.transaction_search.clear()
        page = self.host.transaction_page
        page.mode = "all"
        page.view_buttons["all"].setChecked(True)
        page.analysis_ids = {
            r["id"]
            for r in self.db.execute(
                "SELECT id FROM transactions WHERE import_id=?", (record["id"],)
            )
        }
        self.host.refresh_transactions()
        self.host.tabs.setCurrentIndex(1)
