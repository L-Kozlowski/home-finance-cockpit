"""Wallet table, currency totals and ledger-backed balance history."""

from copy import deepcopy
from datetime import date

from matplotlib.dates import num2date
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from PyQt6.QtCore import QDate, QSignalBlocker, Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.analysis import group_wallet_balances, summarize
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas, render_chart
from home_finance_cockpit.ui.common import selected_ids, table
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import ACCENT, RED

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class WalletItem(QTableWidgetItem):
    def __init__(self, value, wallet_id, sort_value):
        super().__init__(str(value))
        self.setData(Qt.ItemDataRole.UserRole, wallet_id)
        self.setData(SORT_ROLE, sort_value)

    def __lt__(self, other):
        return (self.data(SORT_ROLE), self.data(Qt.ItemDataRole.UserRole)) < (
            other.data(SORT_ROLE),
            other.data(Qt.ItemDataRole.UserRole),
        )


class WalletDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setPen(QPen(QColor(ACCENT), 1))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            painter.restore()


def render_wallet_history(figure, index, data, percentage=True):
    ax = render_chart(figure, 2, data, percentage)
    ax.set_title("")
    if ax.get_legend() is not None:
        ax.get_legend().remove()
    if data.get("balance_trend"):
        day, balance = data["balance_trend"][-1]
        ax.annotate(
            amount_label(balance, data["currency"]),
            (date.fromisoformat(day), balance / 100),
            xytext=(-8, 12),
            textcoords="offset points",
            ha="right",
            color=ACCENT,
            fontsize=9,
            bbox=dict(boxstyle="round,pad=.4", fc="#1a2b3d", ec="#24394d"),
        )
        ax.margins(y=0.25)
        if any(v < 0 for _, v in data["balance_trend"]):
            ax.axhline(0, color="#a8bed5", linewidth=0.7, linestyle="--")
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, position: format_date(num2date(value).date().isoformat()))
        )
    return ax


class WalletsPage(QWidget):
    def __init__(self, db, host):
        super().__init__()
        self.db, self.host = db, host
        self.records, self.visible, self.chart_windows = [], {}, []
        self.period, self.rendering = "3m", False
        self.chart_data, self.chart_dirty = None, False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        summary, summary_layout = panel()
        self.summary = label("", "section")
        self.summary.setToolTip(
            tr(
                "Wszystkie salda, niezależnie od wyszukiwania i filtra waluty. Walut nie przeliczamy."
            )
        )
        summary_layout.addWidget(self.summary)
        layout.addWidget(summary)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(px(10))
        layout.addWidget(self.splitter, 1)
        upper = QWidget()
        top = QVBoxLayout(upper)
        top.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj portfela…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        self.currency = QComboBox()
        self.currency.setMinimumWidth(px(180))
        self.currency.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.currency)
        self.move_up = QPushButton(tr("Przenieś wyżej"))
        self.move_down = QPushButton(tr("Przenieś niżej"))
        self.move_up.clicked.connect(lambda: self.move_selected(-1))
        self.move_down.clicked.connect(lambda: self.move_selected(1))
        filters.addWidget(self.move_up)
        filters.addWidget(self.move_down)
        top.addLayout(filters)
        # Preserve logical column indexes used by the ledger's existing integrations.
        self.table = table(
            [
                tr("Portfel"),
                tr("Saldo początkowe"),
                tr("Od dnia"),
                tr("Saldo bieżące"),
                tr("Waluta"),
                tr("Transakcje"),
                tr("Ostatnia operacja"),
                tr("Akcje"),
            ]
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setItemDelegate(WalletDelegate(self.table))
        self.table.setMinimumHeight(px(125))
        self.table.verticalHeader().setDefaultSectionSize(px(40))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for visual, logical in enumerate((0, 4, 1, 3, 5, 6, 7, 2)):
            header.moveSection(header.visualIndex(logical), visual)
            header.setSectionResizeMode(logical, QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeaderItem(logical).setTextAlignment(
                (
                    Qt.AlignmentFlag.AlignRight
                    if logical in (1, 3, 5)
                    else Qt.AlignmentFlag.AlignLeft
                )
                | Qt.AlignmentFlag.AlignVCenter
            )
        self.table.hideColumn(2)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.cellDoubleClicked.connect(
            lambda row, col: host.edit_wallet() if col != 7 else None
        )
        top.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.selected_icon = label("")
        self.selected_icon.setFixedSize(px(26), px(26))
        actions.addWidget(self.selected_icon)
        self.selected_label = label("", "section")
        actions.addWidget(self.selected_label, 1)
        self.transactions_button = QPushButton(tr("Zobacz transakcje"))
        self.transactions_button.setProperty("role", "primary")
        self.transactions_button.clicked.connect(self.open_transactions)
        self.edit_button = QPushButton(tr("Edytuj portfel"))
        self.edit_button.setIcon(icon("edit"))
        self.edit_button.clicked.connect(host.edit_wallet)
        actions.addWidget(self.transactions_button)
        actions.addWidget(self.edit_button)
        top.addLayout(actions)
        self.count = label("")
        top.addWidget(self.count)
        chart, chart_layout = panel()
        controls = QHBoxLayout()
        self.chart_title = label(tr("Historia salda"), "section")
        controls.addWidget(self.chart_title, 1)
        self.period_group = QButtonGroup(self)
        self.period_buttons = {}
        for title, key in (("1M", "1m"), ("3M", "3m"), ("1R", "1y"), ("Wszystko", "all")):
            button = QPushButton(tr(title))
            button.setCheckable(True)
            button.setChecked(key == self.period)
            button.clicked.connect(lambda checked=False, value=key: self.set_period(value))
            self.period_group.addButton(button)
            self.period_buttons[key] = button
            controls.addWidget(button)
        chart_layout.addLayout(controls)
        self.canvas = ExpandableCanvas(Figure(figsize=(10, 3), layout="constrained"))
        self.canvas.setMinimumHeight(px(135))
        self.canvas.enlarge_requested.connect(self.enlarge_chart)
        chart_layout.addWidget(self.canvas, 1)
        self.chart_note = label(
            tr("Saldo odtworzone z zapisanych transakcji · Dwuklik powiększa wykres")
        )
        self.chart_note.hide()
        self.splitter.addWidget(upper)
        self.splitter.addWidget(chart)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([px(360), px(240)])

    def selected_wallet(self):
        ids = selected_ids(self.table)
        return self.visible.get(ids[0]) if ids else None

    def refresh(self, *_):
        previous = self.selected_wallet()
        previous_id = previous["id"] if previous else None
        self.records = [dict(w) for w in self.db.wallet_balances()]
        current_code = self.currency.currentData()
        with QSignalBlocker(self.currency):
            self.currency.clear()
            self.currency.addItem(tr("Waluta: wszystkie"), None)
            for code in sorted({w["currency"] for w in self.records}):
                self.currency.addItem(code, code)
            self.currency.setCurrentIndex(max(0, self.currency.findData(current_code)))
        totals = group_wallet_balances(self.records)
        self.summary.setText(
            (
                "   |   ".join(
                    tr(
                        "Łączne saldo {code}: {amount}",
                        code=code,
                        amount=amount_label(totals[code]["balance"], code),
                    )
                    for code in sorted(totals, key=lambda code: (code != "PLN", code))
                )
                + (
                    tr("   ·   Portfele: {v0}   ·   Bez przeliczania walut", v0=len(self.records))
                    if totals
                    else tr("Brak portfeli — użyj Dodaj portfel")
                )
            )
        )
        terms = normalize(self.search.text()).split()
        rows = [
            w
            for w in self.records
            if (self.currency.currentData() is None or w["currency"] == self.currency.currentData())
            and all(t in normalize(w["name"] + " " + w["currency"]) for t in terms)
        ]
        self.visible = {w["id"]: w for w in rows}
        header = self.table.horizontalHeader()
        sort_column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        self.rendering = True
        with QSignalBlocker(self.table):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for row, wallet in enumerate(rows):
                values = [
                    wallet["name"],
                    amount_label(wallet["opening_minor"]),
                    wallet["opening_date"],
                    amount_label(wallet["balance"]),
                    wallet["currency"],
                    wallet["transaction_count"],
                    wallet["last_transaction"] or "—",
                    "",
                ]
                for column, value in enumerate(values):
                    key = (
                        wallet["opening_minor"]
                        if column == 1
                        else wallet["balance"]
                        if column == 3
                        else wallet["transaction_count"]
                        if column == 5
                        else normalize(str(value))
                    )
                    item = WalletItem(value, wallet["id"], key)
                    item.setToolTip(str(value))
                    if column in (1, 3, 5):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    if column == 3 and wallet["balance"] < 0:
                        item.setForeground(QColor(RED))
                    if column == 0:
                        item.setIcon(icon(wallet["icon_name"]))
                        item.setToolTip(
                            tr(
                                "{v0} · Saldo początkowe od {v1}",
                                v0=wallet["name"],
                                v1=wallet["opening_date"],
                            )
                        )
                    self.table.setItem(row, column, item)
                menu = QToolButton()
                menu.setIcon(icon("more", "#a8bed5"))
                menu.setFixedSize(px(28), px(28))
                menu.setStyleSheet("QToolButton {padding:0; min-height:0;}")
                menu.setToolTip((tr("Działania portfela: ") + wallet["name"]))
                menu.clicked.connect(
                    lambda checked=False, wallet_id=wallet["id"], button=menu: self.actions_menu(
                        wallet_id, button
                    )
                )
                self.table.setCellWidget(row, 7, menu)
            self.table.setSortingEnabled(True)
            if sort_column >= 0:
                self.table.sortItems(sort_column, order)
            selected_row = next(
                (
                    row
                    for row in range(self.table.rowCount())
                    if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == previous_id
                ),
                0,
            )
            if rows:
                self.table.setCurrentCell(selected_row, 0)
                self.table.selectRow(selected_row)
        self.rendering = False
        self.count.setText(tr("Widoczne portfele: {v0} / {v1}", v0=len(rows), v1=len(self.records)))
        self.selection_changed()

    def selection_changed(self):
        if self.rendering:
            return
        wallet = self.selected_wallet()
        if wallet:
            self.selected_icon.setPixmap(icon(wallet["icon_name"]).pixmap(px(24), px(24)))
        else:
            self.selected_icon.clear()
        self.selected_label.setText(
            (
                wallet["name"]
                if wallet
                else (tr("Wybierz portfel") if self.records else tr("Dodaj pierwszy portfel"))
            )
        )
        self.transactions_button.setEnabled(wallet is not None)
        self.edit_button.setEnabled(wallet is not None)
        ids = [w["id"] for w in self.records]
        position = ids.index(wallet["id"]) if wallet else -1
        self.move_up.setEnabled(position > 0)
        self.move_down.setEnabled(0 <= position < len(ids) - 1)
        self.draw_history()

    def move_selected(self, direction):
        wallet = self.selected_wallet()
        if wallet is None:
            return
        self.db.move_wallet(wallet["id"], direction)
        # A column sort is a temporary view; movement restores the saved order.
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.host.refresh_ui()

    def set_period(self, period):
        self.period = period
        self.draw_history()

    def draw_history(self):
        wallet = self.selected_wallet()
        self.chart_data = None
        self.chart_title.setText(
            (tr("Historia salda") + ((" — " + wallet["name"]) if wallet else ""))
        )
        if wallet is not None:
            end = max(
                QDate.currentDate().toString("yyyy-MM-dd"),
                wallet["opening_date"],
                wallet["last_transaction"] or "",
            )
            last = QDate.fromString(end, "yyyy-MM-dd")
            months = {"1m": 1, "3m": 3, "1y": 12}
            first = last.addMonths(-months[self.period]) if self.period in months else None
            start = (
                max(wallet["opening_date"], first.toString("yyyy-MM-dd"))
                if first and first.isValid()
                else None
            )
            self.chart_data = summarize(self.db, wallet["id"], start, end, wallet["currency"])
            self.chart_note.setText(
                tr(
                    "Saldo odtworzone z zapisanych transakcji · Do {v0} · Dwuklik powiększa wykres",
                    v0=end,
                )
            )
        else:
            self.chart_note.setText(tr("Wybierz portfel, aby wyświetlić historię salda"))
        self.chart_dirty = True
        if self.isVisible():
            self.paint_history()

    def paint_history(self):
        self.canvas.figure.clear()
        if self.chart_data is None:
            ax = self.canvas.figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                tr("Brak portfeli w tym widoku"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
        else:
            render_wallet_history(self.canvas.figure, 2, self.chart_data)
        self.chart_dirty = False
        self.canvas.draw_idle()

    def showEvent(self, event):
        super().showEvent(event)
        if self.chart_dirty:
            self.paint_history()

    def open_transactions(self):
        wallet = self.selected_wallet()
        if wallet is None or not self.host.transaction_page.inspector.guard_pending():
            return
        filters = self.host.transaction_filters
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
            self.host.transaction_search.clear()
        self.host.transaction_page.mode = "all"
        self.host.transaction_page.analysis_ids = None
        self.host.transaction_page.view_buttons["all"].setChecked(True)
        self.host.refresh_transactions()
        self.host.tabs.setCurrentIndex(1)

    def actions_menu(self, wallet_id, button):
        row = next(
            (
                r
                for r in range(self.table.rowCount())
                if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == wallet_id
            ),
            None,
        )
        if row is None:
            return
        self.table.setCurrentCell(row, 0)
        self.table.selectRow(row)
        menu = QMenu(self)
        menu.addAction(tr("Zobacz transakcje"), self.open_transactions)
        menu.addAction(tr("Importuj CSV"), self.host.import_csv)
        menu.addAction(tr("Edytuj portfel"), self.host.edit_wallet)
        menu.addSeparator()
        menu.addAction(tr("Usuń portfel…"), lambda: self.host.delete_records("wallets", self.table))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def enlarge_chart(self):
        if self.chart_data is None:
            return
        dialog = ChartDialog(
            self,
            2,
            deepcopy(self.chart_data),
            context=self.chart_title.text(),
            renderer=render_wallet_history,
            title=self.chart_title.text(),
        )
        self.chart_windows.append(dialog)
        dialog.destroyed.connect(
            lambda: self.chart_windows.remove(dialog) if dialog in self.chart_windows else None
        )
        dialog.show()

    def close_chart_windows(self):
        for dialog in self.chart_windows[:]:
            dialog.close()
