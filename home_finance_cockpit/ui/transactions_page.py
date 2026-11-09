"""Sortable transaction workspace with quick views and a draft inspector."""

import sqlite3

from PyQt6.QtCore import QEvent, QItemSelectionModel, QRect, QSignalBlocker, Qt
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.analysis_kinds import ANALYSIS_KINDS
from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.search import search_transactions
from home_finance_cockpit.ui.common import selected_ids, show_error, table
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.filters import filter_toolbar
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.text_halo import MoneyGlowDelegate, paint_halo
from home_finance_cockpit.ui.theme import ACCENT, RED, SUCCESS, display_color, is_light
from home_finance_cockpit.ui.transaction_filters import TransactionFilters
from home_finance_cockpit.ui.transaction_header import TransactionHeader
from home_finance_cockpit.ui.transaction_inspector import TransactionInspector
from home_finance_cockpit.ui.wallet_destination import WalletDestinationDialog

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class SortableItem(QTableWidgetItem):
    def __init__(self, text, transaction_id, value):
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, transaction_id)
        self.setData(SORT_ROLE, value)

    def __lt__(self, other):
        return (self.data(SORT_ROLE), self.data(Qt.ItemDataRole.UserRole)) < (
            other.data(SORT_ROLE),
            other.data(Qt.ItemDataRole.UserRole),
        )


class TransactionItem(SortableItem):
    def __init__(self, text, identifier, value, sort_values):
        super().__init__(text, identifier, value)
        self.sort_values = sort_values

    def __lt__(self, other):
        table = self.tableWidget()
        keys = getattr(table, "sort_keys", [])
        if len(keys) < 2 or self.column() != keys[0][0]:
            return super().__lt__(other)
        ascending = table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        for column, order in keys:
            first, second = self.sort_values[column], other.sort_values[column]
            if first != second:
                result = first < second if order == Qt.SortOrder.AscendingOrder else first > second
                return result if ascending else not result
        if self.data(Qt.ItemDataRole.UserRole) == other.data(Qt.ItemDataRole.UserRole):
            return False
        result = self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)
        return result if ascending else not result


class TransactionDelegate(MoneyGlowDelegate):
    @staticmethod
    def checkbox_rect(option):
        style = option.widget.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, None, option.widget)
        rect = QRect(0, 0, width, height)
        rect.moveCenter(option.rect.center())
        return rect

    def editorEvent(self, event, model, option, index):
        if index.column() == 10 and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if not index.flags() & Qt.ItemFlag.ItemIsEnabled:
                return False
            if not self.checkbox_rect(option).contains(event.position().toPoint()):
                return False
            if event.type() == QEvent.Type.MouseButtonRelease:
                checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
                return model.setData(
                    index,
                    Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole,
                )
            return True
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        adjusted = QStyleOptionViewItem(option)
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if index.column() == 10:
            self.initStyleOption(adjusted, index)
            adjusted.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
            option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, adjusted, painter, option.widget
            )
            check = QStyleOptionButton()
            check.rect = self.checkbox_rect(option)
            check.palette = adjusted.palette
            check.state = option.state & ~QStyle.StateFlag.State_HasFocus
            check.state |= (
                QStyle.StateFlag.State_On
                if index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
                else QStyle.StateFlag.State_Off
            )
            option.widget.style().drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorCheckBox, check, painter, option.widget
            )
        elif (index.column() == 3 and background) or (index.column() == 5 and selected):
            painter.save()
            painter.fillRect(
                option.rect, background if index.column() == 3 else option.palette.highlight()
            )
            painter.setPen(index.data(Qt.ItemDataRole.ForegroundRole).color())
            decoration = index.data(Qt.ItemDataRole.DecorationRole)
            if decoration is not None:
                decoration.paint(
                    painter,
                    option.rect.x() + px(8),
                    option.rect.y() + (option.rect.height() - px(16)) // 2,
                    px(16),
                    px(16),
                )
            if index.column() == 5:
                paint_halo(
                    painter,
                    option.rect.adjusted(px(12), 0, -px(8), 0),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    index.data(),
                )
            painter.drawText(
                option.rect.adjusted(px(32) if decoration is not None else px(12), 0, -px(8), 0),
                (Qt.AlignmentFlag.AlignRight if index.column() == 5 else Qt.AlignmentFlag.AlignLeft)
                | Qt.AlignmentFlag.AlignVCenter,
                index.data(),
            )
            painter.restore()
        else:
            super().paint(painter, adjusted, index)
        if selected:
            painter.save()
            painter.setPen(QPen(QColor(display_color(ACCENT)), 1))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            if index.column() == 0:
                painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())
            if index.column() == 12:
                painter.drawLine(option.rect.topRight(), option.rect.bottomRight())
            painter.restore()


class TransactionsPage(QWidget):
    def __init__(self, db, host):
        super().__init__()
        self.db, self.host, self.records = db, host, []
        self.mode, self.rendering = "all", False
        self.analysis_ids = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(px(10))
        layout.addWidget(self.splitter)
        left = QWidget()
        content = QVBoxLayout(left)
        content.setContentsMargins(0, 0, 0, 0)
        self.filters = TransactionFilters(db, self.refresh, self)
        toolbar, self.filter_button, self.filter_summary = filter_toolbar(
            host, transactions=True, reset_callback=self.clear_filters
        )
        self.clear_analysis_button = toolbar.clear_button
        self.income_total, self.expense_total = label(""), label("")
        self.income_total.setWordWrap(False)
        self.expense_total.setWordWrap(False)
        self.income_total.setStyleSheet(f"color:{SUCCESS}; font-weight:600;")
        self.expense_total.setStyleSheet(f"color:{RED}; font-weight:600;")
        toolbar.addWidget(self.income_total)
        toolbar.addWidget(self.expense_total)
        content.addLayout(toolbar)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj opisu, kontrahenta, kategorii, kwoty…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.refresh)
        content.addWidget(self.search)
        views = QHBoxLayout()
        self.view_group, self.view_buttons = QButtonGroup(self), {}
        for key, caption in (
            ("all", "Wszystkie"),
            ("uncategorized", "Bez kategorii"),
            ("conflicts", "Konflikty"),
        ):
            button = QPushButton(tr(caption))
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(lambda checked=False, value=key: self.set_mode(value))
            self.view_group.addButton(button)
            views.addWidget(button)
            self.view_buttons[key] = button
        views.addStretch()
        self.detail_button = QPushButton(tr("Szczegóły"))
        self.detail_button.clicked.connect(self.show_details)
        self.clear_selection_button = QPushButton(tr("Wyczyść zaznaczenie"))
        self.clear_selection_button.clicked.connect(lambda: self.table.clearSelection())
        views.addWidget(self.clear_selection_button)
        views.addWidget(self.detail_button)
        columns = QPushButton(tr("Kolumny"))
        columns.clicked.connect(lambda: self.columns_menu(columns))
        views.addWidget(columns)
        content.addLayout(views)
        self.table = table(
            [
                tr("Data"),
                tr("Portfel"),
                tr("Kontrahent"),
                tr("Kategoria"),
                tr("Podkategoria"),
                tr("Kwota"),
                tr("Waluta"),
                tr("Opis / kontrahent"),
                tr("Kategoryzacja"),
                tr("Konflikt"),
                tr("W raportach"),
                tr("Charakter"),
                tr("Saldo po transakcji"),
            ]
        )
        self.table.sort_keys = [(0, Qt.SortOrder.DescendingOrder)]
        self._applying_sort = False
        self.base_headers = [
            self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())
        ]
        self.column_filters = TransactionHeader(self)
        self.table.setHorizontalHeader(self.column_filters)
        self.table.setItemDelegate(TransactionDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(px(54))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for visual, logical in enumerate((0, 7, 1, 3, 5, 10, 2, 4, 6, 8, 9, 11, 12)):
            header.moveSection(header.visualIndex(logical), visual)
        for column in (2, 4, 6, 8, 9, 11):
            self.table.hideColumn(column)
        for column in range(13):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, px(145))
        header.resizeSection(7, px(360))
        header.resizeSection(3, px(180))
        header.resizeSection(12, px(180))
        header.enable_width_fitting()
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        header.sortIndicatorChanged.connect(self.sort_indicator_changed)
        self.table.itemChanged.connect(self.item_changed)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.cellClicked.connect(self.update_open_details)
        self.table.cellDoubleClicked.connect(
            lambda row, column: self.show_details() if column != 10 else None
        )
        content.addWidget(self.table, 1)
        footer = QHBoxLayout()
        self.selection_summary, self.count = label(""), label("")
        footer.addWidget(self.selection_summary, 1)
        footer.addWidget(self.count)
        content.addLayout(footer)
        actions = QHBoxLayout()
        actions.addStretch()
        self.move_button = QPushButton(tr("Przenieś zaznaczone"))
        self.copy_button = QPushButton(tr("Kopiuj zaznaczone"))
        self.move_button.clicked.connect(lambda: self.relocate_selection(copy=False))
        self.copy_button.clicked.connect(lambda: self.relocate_selection(copy=True))
        actions.addWidget(self.move_button)
        actions.addWidget(self.copy_button)
        for caption, callback in (
            ("Edytuj transakcję", host.edit_transaction),
            ("Usuń zaznaczone", lambda: host.delete_records("transactions", self.table)),
        ):
            button = QPushButton(tr(caption))
            if caption.startswith("Usuń"):
                button.setProperty("role", "danger")
            button.clicked.connect(callback)
            actions.addWidget(button)
        content.addLayout(actions)
        self.inspector = TransactionInspector(db)
        self.inspector.setObjectName("inspector")
        self.inspector.setStyleSheet("QWidget#inspector {background:#112233;}")
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setObjectName("card")
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setMinimumWidth(px(315))
        self.editor_scroll.setWidget(self.inspector)
        self.inspector.saved.connect(host.refresh_ui)
        self.inspector.close_requested.connect(self.editor_scroll.hide)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.editor_scroll)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([px(780), px(360)])
        self.editor_scroll.hide()

    def update_open_details(self, row, column):
        if not self.editor_scroll.isHidden():
            self.show_details()

    def set_mode(self, mode):
        self.mode = mode
        self.refresh()

    def sort_indicator_changed(self, column, order):
        if not self._applying_sort and not self.rendering:
            self.table.sort_keys = [(column, order)]
            self.update_sort_labels()

    def sort_column(self, column, multiple=False):
        keys = list(self.table.sort_keys)
        current = next((order for col, order in keys if col == column), None)
        order = (
            Qt.SortOrder.DescendingOrder
            if current == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        if not multiple:
            keys = [(column, order)]
        elif current is None:
            keys.append((column, order))
        else:
            keys = [(col, order if col == column else old) for col, old in keys]
        self.table.sort_keys = keys
        self._applying_sort = True
        try:
            primary, direction = keys[0]
            self.table.horizontalHeader().setSortIndicator(primary, direction)
            self.table.sortItems(primary, direction)
        finally:
            self._applying_sort = False
        self.update_sort_labels()

    def update_sort_labels(self):
        keys = self.table.sort_keys
        for column, caption in enumerate(self.base_headers):
            rank = next(
                ((i, order) for i, (col, order) in enumerate(keys, 1) if col == column), None
            )
            if len(keys) > 1 and rank:
                caption += f" [{rank[0]} {'↑' if rank[1] == Qt.SortOrder.AscendingOrder else '↓'}]"
            self.table.horizontalHeaderItem(column).setText(caption)

    def refresh(self, *_):
        self.column_filters.timer.stop()
        self.column_filters.sync()
        self.filter_summary.setText(self.filters.summary())
        from home_finance_cockpit.services.conflicts import annotate_conflicts

        rows = annotate_conflicts(self.db.transactions(), self.db.rules())
        balances = {w["id"]: w["opening_minor"] for w in self.db.wallets()}
        # Same-day transactions follow their stable database ID order.
        for transaction in sorted(rows, key=lambda r: (r["date"], r["id"])):
            wallet_id = transaction["wallet_id"]
            balances[wallet_id] += transaction["amount_minor"]
            transaction["balance_after_minor"] = balances[wallet_id]
        wallets = self.filters.selected_wallet_ids
        if wallets:
            rows = [r for r in rows if r["wallet_id"] in wallets]
        categories = getattr(self.filters, "selected_category_ids", set())
        if categories:
            rows = [
                r
                for r in rows
                if r["category_id"] in categories or r["root_category_id"] in categories
            ]
        if self.analysis_ids is not None:
            rows = [r for r in rows if r["id"] in self.analysis_ids]
        try:
            start, end = self.filters.period()
            rows = [
                r
                for r in rows
                if (
                    self.analysis_ids is not None
                    or r["currency"] == self.filters.currency.currentData()
                )
                and (start is None or r["date"] >= start)
                and (end is None or r["date"] <= end)
            ]
        except ValueError as exc:
            self.filter_summary.setText(str(exc))
            rows = []
        scope_count = len(rows)
        rows = search_transactions(rows, self.search.text())
        rows = self.column_filters.apply(rows)
        counts = dict(
            all=len(rows),
            uncategorized=sum(bool(r["is_uncategorized"]) for r in rows),
            conflicts=sum(bool(r["category_conflict"] or r["possible_conflict"]) for r in rows),
        )
        for key, caption in (
            ("all", "Wszystkie"),
            ("uncategorized", "Bez kategorii"),
            ("conflicts", "Konflikty"),
        ):
            self.view_buttons[key].setText(tr("{v0}  {v1}", v0=tr(caption), v1=counts[key]))
        self.records = [
            r
            for r in rows
            if self.mode == "all"
            or (self.mode == "uncategorized" and r["is_uncategorized"])
            or (self.mode == "conflicts" and (r["category_conflict"] or r["possible_conflict"]))
        ]
        self.record_map = {r["id"]: r for r in self.records}
        self.visible_income = sum(max(0, r["amount_minor"]) for r in self.records)
        self.visible_expense = sum(max(0, -r["amount_minor"]) for r in self.records)
        currency = self.filters.currency.currentData()
        self.income_total.setText((tr("Wpływy: ") + amount_label(self.visible_income, currency)))
        self.expense_total.setText((tr("Wydatki: ") + amount_label(self.visible_expense, currency)))
        self.count.setText(tr("{v0} / {v1}", v0=len(self.records), v1=scope_count))
        selected = set(selected_ids(self.table))
        current_id = self.inspector.transaction_id
        sort_column, order = (
            self.table.horizontalHeader().sortIndicatorSection(),
            self.table.horizontalHeader().sortIndicatorOrder(),
        )
        self.rendering = True
        with QSignalBlocker(self.table):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
            self.table.setRowCount(len(self.records))
            for row, transaction in enumerate(self.records):
                values = [
                    transaction["date"],
                    transaction["wallet"],
                    transaction["from_to"],
                    transaction["category"]
                    + ("\n" + transaction["subcategory"] if transaction["subcategory"] else ""),
                    transaction["subcategory"],
                    amount_label(transaction["amount_minor"]),
                    transaction["currency"],
                    transaction["description"]
                    + ("\n" + transaction["from_to"] if transaction["from_to"] else ""),
                    transaction["category_source"],
                    tr("Konflikt reguł")
                    if transaction["category_conflict"]
                    else tr("Możliwy konflikt")
                    if transaction["possible_conflict"]
                    else "",
                    "",
                    tr(ANALYSIS_KINDS[transaction["analysis_kind"]]),
                    amount_label(transaction["balance_after_minor"]),
                ]
                sort_values = tuple(
                    transaction["amount_minor"]
                    if col == 5
                    else transaction["balance_after_minor"]
                    if col == 12
                    else int(transaction["include_in_reports"])
                    if col == 10
                    else str(value).casefold()
                    for col, value in enumerate(values)
                )
                for col, value in enumerate(values):
                    item = TransactionItem(
                        str(value), transaction["id"], sort_values[col], sort_values
                    )
                    item.setToolTip(str(value))
                    if col in (3, 9) and transaction["conflict_explanation"]:
                        item.setToolTip(transaction["conflict_explanation"])
                        if col == 3:
                            item.setIcon(icon("alert", RED))
                    if col == 5:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                        item.setForeground(
                            QColor(
                                display_color(RED if transaction["amount_minor"] < 0 else SUCCESS)
                            )
                        )
                    if col == 1:
                        item.setIcon(icon(transaction["wallet_icon"]))
                    if col == 12:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                        item.setToolTip(
                            amount_label(
                                transaction["balance_after_minor"], transaction["currency"]
                            )
                        )
                    if col == 3:
                        from home_finance_cockpit.reports.presentation import category_color

                        chosen, base = (
                            QColor(
                                category_color(
                                    transaction["category"],
                                    {transaction["category"]: transaction["category_color"]},
                                )
                            ),
                            QColor(display_color("#112233")),
                        )
                        background = QColor(
                            *(
                                round(a * 0.22 + b * 0.78)
                                for a, b in zip(chosen.getRgb()[:3], base.getRgb()[:3])
                            )
                        )
                        item.setBackground(QBrush(background))
                        item.setForeground(
                            chosen.darker(200)
                            if is_light()
                            else QColor(
                                *(round(a * 0.55 + 255 * 0.45) for a in chosen.getRgb()[:3])
                            )
                        )
                    if col == 10:
                        item.setFlags(
                            Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsUserCheckable
                        )
                        checked = bool(transaction["include_in_reports"])
                        item.setCheckState(
                            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                        )
                        item.setToolTip(tr("Uwzględnij w raportach"))
                    self.table.setItem(row, col, item)
            self.table.setSortingEnabled(True)
            self.table.sortItems(sort_column, order)
            self.restore_selection(selected)
        self.rendering = False
        if current_id is not None and not self.inspector.dirty():
            self.inspector.reload()
        self.update_selection_summary()

    def restore_selection(self, ids):
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) in ids:
                self.table.selectionModel().select(
                    self.table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )

    def clear_analysis_scope(self):
        self.analysis_ids = None
        self.refresh()

    def clear_filters(self):
        self.analysis_ids = None
        self.column_filters.clear()
        self.filters.selected_category_ids = set()
        self.filters.selected_wallet_ids = set()
        with (
            QSignalBlocker(self.filters.wallet),
            QSignalBlocker(self.filters.preset),
            QSignalBlocker(self.search),
        ):
            self.filters.wallet.setCurrentIndex(0)
            self.filters.preset.setCurrentIndex(self.filters.preset.findData("all"))
            self.search.clear()
        self.mode = "all"
        self.view_buttons["all"].setChecked(True)
        self.refresh()

    def selection_changed(self):
        if self.rendering:
            return
        self.update_selection_summary()

    def update_selection_summary(self):
        ids = set(selected_ids(self.table))
        self.clear_selection_button.setEnabled(bool(ids))
        self.detail_button.setEnabled(bool(ids))
        self.move_button.setEnabled(bool(ids))
        self.copy_button.setEnabled(bool(ids))
        total = sum(
            self.record_map[value]["amount_minor"] for value in ids if value in self.record_map
        )
        self.selection_summary.setText(
            (
                tr(
                    "Zaznaczono: {v0} · {v1}",
                    v0=len(ids),
                    v1=amount_label(total, self.filters.currency.currentData()),
                )
                if ids
                else ""
            )
        )

    def item_changed(self, item):
        if self.rendering or item.column() != 10:
            return
        transaction_id = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        if self.inspector.transaction_id == transaction_id and not self.inspector.guard_pending():
            self.refresh()
            return
        try:
            self.db.set_report_inclusion(transaction_id, checked)
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
        self.host.refresh_ui()

    def relocate_selection(self, *, copy=False):
        identifiers = selected_ids(self.table)
        if not identifiers or not self.inspector.guard_pending():
            return
        selected = set(identifiers)
        rows = [r for r in self.db.transactions() if r["id"] in selected]
        currencies = {r["currency"] for r in rows}
        sources = {r["wallet_id"] for r in rows}
        choices = [
            w
            for w in self.db.wallets()
            if w["currency"] in currencies
            and len(currencies) == 1
            and not (len(sources) == 1 and w["id"] in sources)
        ]
        if not choices:
            show_error(
                self, tr("Wybierz transakcje w jednej walucie i utwórz inny portfel w tej walucie.")
            )
            return
        dialog = WalletDestinationDialog(
            self,
            tr("Kopiuj zaznaczone") if copy else tr("Przenieś zaznaczone"),
            choices,
            count=len(identifiers),
        )
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    self.db.relocate_transactions(identifiers, dialog.wallet_id, copy=copy)
                except (ValueError, sqlite3.Error) as exc:
                    show_error(self, exc)
                    return
                self.host.refresh_ui()
        finally:
            dialog.deleteLater()

    def show_details(self):
        ids = selected_ids(self.table)
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        target_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if target_id not in ids:
            target_id = ids[0] if ids else None
        if target_id not in self.record_map:
            return
        previous = self.inspector.transaction_id
        if target_id != previous and not self.inspector.guard_pending():
            with QSignalBlocker(self.table):
                self.restore_selection({previous})
            self.update_selection_summary()
            return
        self.inspector.load(self.record_map[target_id])
        self.editor_scroll.show()

    def columns_menu(self, button):
        menu = QMenu(self)
        for col in (2, 4, 6, 8, 9, 11):
            action = menu.addAction(self.table.horizontalHeaderItem(col).text())
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(col))
            action.toggled.connect(
                lambda checked, index=col: self.table.setColumnHidden(index, not checked)
            )
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.splitter.setOrientation(
            Qt.Orientation.Vertical if self.width() < px(1100) else Qt.Orientation.Horizontal
        )
