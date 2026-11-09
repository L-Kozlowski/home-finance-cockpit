"""Searchable counterparties with a focused monthly history and transactions."""

from collections import defaultdict
from statistics import median

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PyQt6.QtCore import QPointF, QSignalBlocker, Qt
from PyQt6.QtGui import QColor, QLinearGradient
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.common import selected_ids, table
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import TEXT, display_color


def recipient_records(data, root=None):
    groups = defaultdict(list)
    for contribution in data["contributions"]:
        if contribution["row"]["amount_minor"] < 0 and (
            root is None or contribution["root"] == root
        ):
            groups[contribution["merchant"]].append(contribution["row"])
    result = []
    for name, rows in groups.items():
        amounts = [-r["amount_minor"] for r in rows]
        monthly = defaultdict(int)
        for row in rows:
            monthly[row["date"][:7]] -= row["amount_minor"]
        result.append(
            dict(
                name=name,
                total=sum(amounts),
                count=len(rows),
                average=sum(amounts) / len(rows),
                median=median(amounts),
                first=min(r["date"] for r in rows),
                last=max(r["date"] for r in rows),
                roots={r["root_category_id"] for r in rows},
                rows=rows,
                monthly=monthly,
            )
        )
    return result


class RecipientItem(QTableWidgetItem):
    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole + 1) < other.data(Qt.ItemDataRole.UserRole + 1)


class RecipientDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        if index.column() != 1:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget
        )
        rect = option.rect.adjusted(8, 3, -8, -3)
        fraction = index.data(Qt.ItemDataRole.UserRole + 2) or 0
        painter.save()
        painter.setPen(QColor(display_color(TEXT)))
        painter.drawText(
            rect.adjusted(0, 0, -int(rect.width() * 0.4), 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            index.data(),
        )
        bar = rect.adjusted(
            int(rect.width() * 0.65), int(rect.height() * 0.3), 0, -int(rect.height() * 0.3)
        )
        painter.fillRect(bar, QColor(display_color("#1E3347")))
        bar.setWidth(int(bar.width() * fraction))
        gradient = QLinearGradient(QPointF(bar.topLeft()), QPointF(bar.bottomLeft()))
        gradient.setColorAt(0, QColor("#55E8FF"))
        gradient.setColorAt(1, QColor("#06B6D4"))
        painter.fillRect(bar, gradient)
        painter.restore()


def render_recipient(figure, key, data, percentage=True):
    figure.clear()
    figure._transparent_chart = True
    ax = figure.add_subplot(111)
    record = data["record"]
    months = data["months"]
    if not record or not months:
        return ax
    values = [record["monthly"].get(m, 0) / 100 for m in months]
    bars = ax.bar(range(len(months)), values, color="none", width=0.55)
    limits = ax.get_xlim(), ax.get_ylim()
    cmap = LinearSegmentedColormap.from_list("recipient", ["#06B6D4", "#22D3EE", "#55E8FF"])
    for bar in bars:
        if not bar.get_height():
            continue
        x = bar.get_x()
        image = ax.imshow(
            np.linspace(0, 1, 128).reshape(-1, 1),
            extent=(x, x + bar.get_width(), 0, bar.get_height()),
            origin="lower",
            aspect="auto",
            cmap=cmap,
            zorder=2,
        )
        image.set_clip_path(bar)
    ax.set_xlim(limits[0])
    ax.set_ylim(0, max(1, max(values) * 1.22))
    ax.bar_label(bars, labels=[amount_label(round(v * 100)) for v in values], padding=7, fontsize=9)
    ax.set_xticks(range(len(months)), [format_date(m) for m in months])
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.text(0, 1.02, data["currency"], transform=ax.transAxes, ha="left", va="bottom")
    return ax


class Counterparties(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.data = None
        self.records = {}
        self.current_name = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left, box = panel()
        heading = QHBoxLayout()
        heading.addWidget(label(tr("Odbiorcy"), "section"), 1)
        filters = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj kontrahenta…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.render_list)
        filters.addWidget(self.search)
        choices = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItem(tr("Wszystkie kategorie"), None)
        self.category.currentIndexChanged.connect(self.render_list)
        self.sort = QComboBox()
        for title, key in (
            ("Suma wydatków", "total"),
            ("Liczba transakcji", "count"),
            ("Średnia transakcja", "average"),
            ("Ostatnia płatność", "last"),
            ("Nazwa", "name"),
        ):
            self.sort.addItem(tr(title), key)
        self.sort.currentIndexChanged.connect(self.render_list)
        choices.addWidget(self.category, 1)
        choices.addWidget(self.sort, 1)
        filters.addLayout(choices)
        heading.addLayout(filters, 2)
        box.addLayout(heading)
        self.table = table(
            [
                tr(s)
                for s in (
                    "Nazwa",
                    "Suma wydatków",
                    "Transakcje",
                    "Średnia transakcja",
                    "Ostatnia płatność",
                )
            ]
        )
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.setItemDelegate(RecipientDelegate(self.table))
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setStyleSheet(
            "QTableWidget {background:transparent; border:0;} QTableWidget::item {border-bottom:1px solid #24394D; padding:6px;}"
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.select_recipient)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_transactions())
        self.table.horizontalHeader().sectionClicked.connect(self.sort_column)
        box.addWidget(self.table, 1)
        self.total = label("", "section")
        box.addWidget(self.total)
        footer = QHBoxLayout()
        self.count = label("")
        footer.addWidget(self.count, 1)
        self.transactions = QPushButton(tr("Zobacz transakcje"))
        self.transactions.setProperty("role", "primary")
        self.transactions.clicked.connect(self.open_transactions)
        footer.addWidget(self.transactions)
        box.addLayout(footer)
        self.splitter.addWidget(left)
        self.right = QSplitter(Qt.Orientation.Vertical)
        chart, box = panel()
        head = QHBoxLayout()
        self.chart_title = label("", "section")
        head.addWidget(self.chart_title, 1)
        self.chart_total = label("")
        head.addWidget(self.chart_total)
        box.addLayout(head)
        self.canvas = ExpandableCanvas(Figure(figsize=(5, 2.5), layout="constrained"))
        self.canvas.setMinimumSize(180, 130)
        self.canvas.enlarge_requested.connect(self.enlarge)
        box.addWidget(self.canvas, 1)
        self.right.addWidget(chart)
        details, box = panel()
        self.details_title = label("", "section")
        box.addWidget(self.details_title)
        self.details_grid = QGridLayout()
        box.addLayout(self.details_grid, 1)
        self.right.addWidget(details)
        recent, box = panel()
        head = QHBoxLayout()
        head.addWidget(label(tr("Ostatnie transakcje"), "section"), 1)
        self.view_all = QPushButton(tr("Zobacz wszystkie"))
        self.view_all.clicked.connect(self.open_transactions)
        head.addWidget(self.view_all)
        box.addLayout(head)
        self.view_all.setStyleSheet(
            "QPushButton {background:transparent; border:0; color:#22D3EE;}"
        )
        self.recent_layout = QVBoxLayout()
        box.addLayout(self.recent_layout)
        self.right.addWidget(recent)
        self.right.setSizes([310, 270, 180])
        self.right.setChildrenCollapsible(False)
        self.splitter.addWidget(self.right)
        self.splitter.setSizes([650, 450])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)

    def refresh(self, data):
        self.data = data
        current = self.category.currentData()
        with QSignalBlocker(self.category):
            self.category.clear()
            self.category.addItem(tr("Wszystkie kategorie"), None)
            if data:
                for root, name in data["category_names"].items():
                    if root is not None and root in data["gross_categories"]:
                        self.category.addItem(name, root)
            self.category.setCurrentIndex(max(0, self.category.findData(current)))
        self.render_list()

    def sort_column(self, column):
        self.sort.setCurrentIndex(
            self.sort.findData(("name", "total", "count", "average", "last")[column])
        )

    def render_list(self, *_):
        rows = recipient_records(self.data, self.category.currentData()) if self.data else []
        terms = normalize(self.search.text()).split()
        rows = [r for r in rows if all(t in normalize(r["name"]) for t in terms)]
        key = self.sort.currentData() or "total"
        rows.sort(key=lambda r: r[key], reverse=key != "name")
        self.table.horizontalHeader().setSortIndicator(
            ("name", "total", "count", "average", "last").index(key),
            Qt.SortOrder.AscendingOrder if key == "name" else Qt.SortOrder.DescendingOrder,
        )
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.records = {r["name"]: r for r in rows}
        maximum = max([r["total"] for r in rows] + [1])
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(rows))
            for index, record in enumerate(rows):
                texts = [
                    record["name"],
                    amount_label(record["total"]),
                    str(record["count"]),
                    amount_label(round(record["average"])),
                    format_date(record["last"]),
                ]
                for column, text in enumerate(texts):
                    item = RecipientItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, record["name"])
                    item.setToolTip(text)
                    item.setData(
                        Qt.ItemDataRole.UserRole + 1,
                        record[("name", "total", "count", "average", "last")[column]],
                    )
                    if column:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if column == 1:
                        item.setData(Qt.ItemDataRole.UserRole + 2, record["total"] / maximum)
                    self.table.setItem(index, column, item)
            if rows:
                self.table.selectRow(
                    next((i for i, r in enumerate(rows) if r["name"] == self.current_name), 0)
                )
        total = sum(r["total"] for r in rows)
        count = sum(r["count"] for r in rows)
        self.total.setText(
            tr("Suma wydatków")
            + ": "
            + amount_label(total, self.data["currency"] if self.data else "")
        )
        self.count.setText(tr("Transakcje") + f": {count}  ·  " + tr("Odbiorcy") + f": {len(rows)}")
        self.select_recipient()

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def select_recipient(self):
        names = selected_ids(self.table)
        self.current_name = names[0] if names else None
        record = self.records.get(self.current_name)
        self.transactions.setEnabled(record is not None)
        self.view_all.setEnabled(record is not None)
        self.transactions.setText(
            tr("Zobacz transakcje") + (" · " + record["name"] if record else "")
        )
        self.clear_layout(self.details_grid)
        self.clear_layout(self.recent_layout)
        if record is None:
            self.chart_title.setText(tr("Brak danych w wybranym zakresie"))
            self.chart_total.clear()
            self.details_title.clear()
            self.canvas.figure.clear()
            self.canvas.draw_idle()
            return
        self.chart_title.setText(record["name"] + " · " + tr("Wydatki miesięczne"))
        self.chart_total.setText(
            tr("Suma") + ": " + amount_label(record["total"], self.data["currency"])
        )
        self.plot_data = dict(
            record=record, months=self.data["months"], currency=self.data["currency"]
        )
        render_recipient(self.canvas.figure, None, self.plot_data)
        self.canvas.draw_idle()
        self.details_title.setText(record["name"] + " · " + tr("Szczegóły wydatków"))
        categories = ", ".join(
            sorted(self.data["category_names"].get(root, "—") for root in record["roots"])
        )
        values = [
            (tr("Kategoria"), categories),
            (tr("Transakcje"), str(record["count"])),
            (
                tr("Średnia transakcja"),
                amount_label(round(record["average"]), self.data["currency"]),
            ),
            (
                tr("Mediana transakcji"),
                amount_label(round(record["median"]), self.data["currency"]),
            ),
            (tr("Pierwsza płatność"), format_date(record["first"])),
            (tr("Ostatnia płatność"), format_date(record["last"])),
        ]
        for index, (caption, value) in enumerate(values):
            for column, field in enumerate((label(caption), label(value, ""))):
                field.ensurePolished()
                field.setMinimumHeight(field.fontMetrics().height() + px(8))
                field.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.details_grid.addWidget(field, index, column)
        for row in sorted(record["rows"], key=lambda r: (r["date"], r["id"]), reverse=True)[:3]:
            container = QWidget()
            row_layout = QHBoxLayout(container)
            row_layout.setContentsMargins(0, 3, 0, 3)
            row_layout.addWidget(label(format_date(row["date"])), 1)
            row_layout.addWidget(label(record["name"], ""), 1)
            amount = label(amount_label(-row["amount_minor"], self.data["currency"]), "")
            amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(amount, 1)
            button = QPushButton()
            button.setIcon(icon("more"))
            button.setToolTip(tr("Zobacz transakcje"))
            button.setFixedWidth(28)
            button.setStyleSheet("QPushButton {background:transparent; border:0;}")
            button.clicked.connect(
                lambda checked=False, identifier=row["id"]: self.owner.open_rows([identifier])
            )
            row_layout.addWidget(button)
            self.recent_layout.addWidget(container)

    def open_transactions(self):
        record = self.records.get(self.current_name)
        if record:
            self.owner.open_rows([r["id"] for r in record["rows"]])

    def enlarge(self):
        if self.current_name not in self.records:
            return
        dialog = ChartDialog(
            self,
            None,
            self.plot_data,
            renderer=render_recipient,
            title=self.current_name,
            context=self.owner.filter_summary.text(),
        )
        self.owner.chart_windows.append(dialog)
        dialog.finished.connect(
            lambda _: (
                self.owner.chart_windows.remove(dialog)
                if dialog in self.owner.chart_windows
                else None
            )
        )
        dialog.show()
