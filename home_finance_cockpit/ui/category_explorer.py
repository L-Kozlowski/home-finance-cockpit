"""Category tree, monthly subcategory matrix and matching individual trends."""

from decimal import ROUND_HALF_UP, Decimal

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PyQt6.QtCore import QPoint, QRect, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap, QPolygon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.chart_helpers import category_chart_color, show_empty_chart
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.common import table
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.theme import SURFACE, TEXT, display_color


class CategoryTreeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyleOptionViewItem

        option = QStyleOptionViewItem(option)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            self.initStyleOption(option, index)
            painter.save()
            painter.fillRect(option.rect, QColor(display_color("#15475b")))
            painter.setPen(QPen(QColor(display_color("#22D3EE")), 1))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            rect = option.rect.adjusted(
                5,
                0,
                (-90 if self.parent().edit_controls else -24) if index.column() == 1 else -5,
                0,
            )
            if not option.icon.isNull():
                size = 18
                option.icon.paint(painter, rect.left(), rect.center().y() - size // 2, size, size)
                rect.adjust(size + 6, 0, 0, 0)
            painter.setPen(QColor(display_color("#EDF4FF")))
            painter.setFont(option.font)
            painter.drawText(rect, option.displayAlignment, option.text)
            painter.restore()
            return
        option.state &= ~QStyle.StateFlag.State_Selected
        if index.column() == 1:
            option.rect.adjust(0, 0, -90 if self.parent().edit_controls else -24, 0)
        super().paint(painter, option, index)


class CategoryTree(QTreeWidget):
    """Keep native tree navigation while placing expand controls on the right."""

    edit_requested = pyqtSignal(object)
    add_requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setRootIsDecorated(False)
        self.setIndentation(26)
        self.setExpandsOnDoubleClick(False)
        self.edit_controls = False
        self.setItemDelegate(CategoryTreeDelegate(self))
        self.setStyleSheet(
            "QTreeWidget {background: transparent; border: 0; alternate-background-color: transparent;} "
            "QTreeWidget::item {background: transparent; padding: 4px 0;} "
            "QTreeWidget::item:selected {background: #15475b; border: 1px solid #22d3ee; border-radius: 5px;}"
        )

    def drawBranches(self, painter, rect, index):
        if not index.parent().isValid():
            return
        painter.save()
        painter.setPen(QPen(QColor(display_color("#7B8FA6")), 1))
        x = rect.right() - 13
        y = rect.center().y()
        last = index.row() == self.model().rowCount(index.parent()) - 1
        painter.drawLine(x, rect.top(), x, y if last else rect.bottom())
        painter.drawLine(x, y, rect.right(), y)
        painter.restore()

    def drawRow(self, painter, option, index):
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            painter.setPen(QPen(QColor(display_color("#22D3EE")), 1))
            painter.setBrush(QColor(display_color("#15475b")))
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 5, 5)
            painter.restore()
        super().drawRow(painter, option, index)
        if self.edit_controls:
            icon("edit").paint(
                painter, QRect(self.viewport().width() - 53, option.rect.center().y() - 9, 18, 18)
            )
            item = self.itemFromIndex(index)
            if not index.parent().isValid() and not item.data(0, Qt.ItemDataRole.UserRole + 1):
                icon("plus").paint(
                    painter,
                    QRect(self.viewport().width() - 84, option.rect.center().y() - 9, 18, 18),
                )
        if index.parent().isValid():
            return
        painter.save()
        painter.setPen(QPen(QColor(display_color("#A8BED5")), 1.4))
        x = self.viewport().width() - 13
        y = option.rect.center().y()
        item = self.itemFromIndex(index)
        if item and item.childCount():
            points = (
                [QPoint(x - 4, y - 2), QPoint(x, y + 2), QPoint(x + 4, y - 2)]
                if item.isExpanded()
                else [QPoint(x - 2, y - 4), QPoint(x + 2, y), QPoint(x - 2, y + 4)]
            )
            painter.drawPolyline(QPolygon(points))
        painter.restore()

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if (
            self.edit_controls
            and item
            and item.parent() is None
            and not item.data(0, Qt.ItemDataRole.UserRole + 1)
            and event.button() == Qt.MouseButton.LeftButton
            and self.viewport().width() - 90 <= event.position().x() < self.viewport().width() - 60
        ):
            self.add_requested.emit(item)
            return
        if (
            self.edit_controls
            and item
            and event.button() == Qt.MouseButton.LeftButton
            and self.viewport().width() - 60 <= event.position().x() < self.viewport().width() - 28
        ):
            self.edit_requested.emit(item)
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item and item.childCount():
            if (
                self.edit_controls
                and self.viewport().width() - 60
                <= event.position().x()
                < self.viewport().width() - 28
            ):
                event.accept()
                return
            item.setExpanded(not item.isExpanded())
            self.setCurrentItem(item)
            self.viewport().update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def dot(color):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(3, 3, 18, 18)
    painter.end()
    return QIcon(pixmap)


class HeatLegend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tint = "#22D3EE"
        self.setFixedHeight(12)
        self.setMinimumWidth(140)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        base = QColor(display_color(SURFACE))
        accent = QColor(self.tint)
        for stop, weight in ((0, 0.08), (1, 0.53)):
            mixed = QColor(
                *[
                    round(a * (1 - weight) + b * weight)
                    for a, b in zip(base.getRgb()[:3], accent.getRgb()[:3])
                ]
            )
            gradient.setColorAt(stop, mixed)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(self.rect(), 4, 4)


class MatrixDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is None:
            return super().paint(painter, option, index)
        painter.save()
        painter.fillRect(option.rect, brush)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        painter.setPen(foreground.color() if foreground else QColor(display_color(TEXT)))
        painter.setFont(option.font)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(index.data() or ""))
        painter.restore()


def child_name(contribution):
    row = contribution["row"]
    return row["subcategory"] or (
        tr("Zwroty do przypisania") if contribution["root"] is None else tr("Bez podkategorii")
    )


def category_series(data, root, child=None):
    months = data["months"]
    keys = [
        key for key in data["children"] if key[0] == root and (child is None or key[1] == child)
    ]
    keys.sort(key=lambda key: (-data["children"][key], key[1]))
    return months, [
        (key[1], [data["monthly"][month]["children"].get(key, 0) for month in months])
        for key in keys
    ]


def average_minor(values):
    return (
        int((Decimal(sum(values)) / len(values)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if values
        else 0
    )


def shade(data, root, index):
    base = QColor(category_chart_color(data, root))
    return base.lighter(100 + index % 5 * 15).name()


def render_trend(figure, key, data, percentage=True):
    figure._transparent_chart = True
    figure.clear()
    ax = figure.add_subplot(111)
    months, rows = category_series(data, data["explorer_root"], key)
    if not rows:
        show_empty_chart(ax)
        return ax
    values = rows[0][1]
    ax.plot(
        range(len(months)),
        [v / 100 for v in values],
        color=data["explorer_color"],
        marker="o",
        markersize=3,
        linewidth=1.8,
    )
    ax.set_xticks(range(len(months)), [format_date(m) for m in months])
    ax.yaxis.set_major_locator(MaxNLocator(nbins=3))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))
    ax.grid(alpha=0.15)
    ax.margins(x=0.08, y=0.2)
    if len(months) == 1:
        ax.set_xlim(-0.5, 0.5)
    return ax


class CategoryExplorer(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.data, self.selection = owner, None, None
        self.trend_canvases = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left, content = panel()
        headings = QHBoxLayout()
        headings.addWidget(label(tr("Kategorie"), "section"), 1)
        self.period_total_label = label(tr("Suma w okresie"))
        headings.addWidget(self.period_total_label)
        content.addLayout(headings)
        self.tree = CategoryTree()
        self.tree.setHeaderLabels([tr("Kategoria"), tr("Suma")])
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self.select_item)
        content.addWidget(self.tree)
        self.transactions = QPushButton(tr("Zobacz transakcje"))
        self.transactions.setIcon(icon("transactions"))
        self.transactions.setText(tr("Zobacz transakcje"))
        self.transactions.setMinimumHeight(40)
        self.transactions.clicked.connect(lambda: self.open_transactions())
        content.addWidget(self.transactions)
        self.splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb = label("", "section")
        self.breadcrumb.setContentsMargins(16, 10, 16, 10)
        self.breadcrumb.setTextFormat(Qt.TextFormat.RichText)
        right_layout.addWidget(self.breadcrumb)
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        matrix, content = panel()
        header = QHBoxLayout()
        self.matrix_title = label(tr("Miesięczna macierz podkategorii"), "section")
        header.addWidget(self.matrix_title, 1)
        self.display = QComboBox()
        self.display.addItem(tr("Kwota"), False)
        self.display.addItem(tr("Udział %"), True)
        self.display.currentIndexChanged.connect(self.render_selection)
        header.addWidget(self.display)
        content.addLayout(header)
        self.matrix = table([])
        self.matrix.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.matrix.setItemDelegate(MatrixDelegate(self.matrix))
        self.matrix.cellDoubleClicked.connect(self.open_cell_transactions)
        content.addWidget(self.matrix)
        legend_row = QHBoxLayout()
        legend_row.addWidget(label(tr("Niższe wydatki")))
        self.legend = HeatLegend()
        legend_row.addWidget(self.legend, 1)
        legend_row.addWidget(label(tr("Wyższe wydatki")))
        legend_row.addStretch(2)
        content.addLayout(legend_row)
        trends, content = panel("Trendy podkategorii")
        self.trends = table(
            [tr("Podkategoria"), tr("Trend miesięczny"), tr("Suma"), tr("Średnia miesięczna")]
        )
        self.trends.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.trends.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trends.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        content.addWidget(self.trends)
        self.right_splitter.addWidget(matrix)
        self.right_splitter.addWidget(trends)
        self.right_splitter.setSizes([350, 350])
        self.right_splitter.setChildrenCollapsible(False)
        right_layout.addWidget(self.right_splitter)
        self.splitter.addWidget(right)
        self.splitter.setSizes([280, 1000])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)

    def refresh(self, data):
        self.data = data
        self.period_total_label.setText(
            tr("Suma w okresie") + (f" ({data['currency']})" if data else "")
        )
        expanded = {
            self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)[0]
            for i in range(self.tree.topLevelItemCount())
            if self.tree.topLevelItem(i).isExpanded()
        }
        with QSignalBlocker(self.tree):
            self.tree.clear()
            selected = None
            first = None
            if data:
                for root in sorted(
                    data["categories"],
                    key=lambda r: (-data["categories"][r], data["category_names"].get(r, "")),
                ):
                    parent = QTreeWidgetItem(
                        [
                            data["category_names"].get(root, "—"),
                            amount_label(data["categories"][root]),
                        ]
                    )
                    parent.setData(0, Qt.ItemDataRole.UserRole, (root, None))
                    parent.setSizeHint(0, QSize(0, 42))
                    parent.setTextAlignment(
                        1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    parent.setForeground(1, QColor(display_color(TEXT)))
                    font = parent.font(1)
                    font.setBold(True)
                    parent.setFont(1, font)
                    parent.setForeground(0, QColor(category_chart_color(data, root)))
                    parent.setIcon(
                        0,
                        icon(
                            data.get("category_icons", {}).get(root, "tag"),
                            category_chart_color(data, root),
                        ),
                    )
                    self.tree.addTopLevelItem(parent)
                    if first is None:
                        first = parent
                    if self.selection == (root, None):
                        selected = parent
                    _, rows = category_series(data, root)
                    for index, (name, values) in enumerate(rows):
                        item = QTreeWidgetItem([name, amount_label(sum(values))])
                        item.setData(0, Qt.ItemDataRole.UserRole, (root, name))
                        item.setSizeHint(0, QSize(0, 34))
                        item.setTextAlignment(
                            1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                        item.setForeground(1, QColor(display_color(TEXT)))
                        item.setForeground(0, QColor(shade(data, root, index)))
                        parent.addChild(item)
                        item.setIcon(0, dot(shade(data, root, index)))
                        if self.selection == (root, name):
                            selected = item
                    parent.setExpanded(root in expanded)
                selected = selected or first
                if selected:
                    self.tree.setCurrentItem(selected)
                    (selected.parent() or selected).setExpanded(True)
        item = self.tree.currentItem()
        self.selection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.render_selection()

    def select_item(self, item, previous=None):
        self.selection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.render_selection()

    def render_selection(self, *_):
        self.trend_canvases = []
        self.trends.setRowCount(0)
        self.matrix.clear()
        self.matrix.setRowCount(0)
        self.transactions.setEnabled(self.selection is not None)
        if not self.data or self.selection is None:
            self.breadcrumb.setText(tr("Brak danych w wybranym zakresie"))
            self.matrix.setColumnCount(0)
            return
        root, child = self.selection
        months, rows = category_series(self.data, root, child)
        self.current_months, self.current_rows = months, rows
        name = self.data["category_names"].get(root, "—")
        from html import escape

        self.breadcrumb.setText(
            escape(tr("Wszystkie"))
            + " &nbsp; / &nbsp; "
            + f'<span style="color:{category_chart_color(self.data, root)}">{escape(name)}</span>'
            + (" &nbsp; / &nbsp; " + escape(child) if child else "")
        )
        self.legend.tint = category_chart_color(self.data, root)
        self.legend.update()
        self.matrix_title.setText(name + " · " + tr("Miesięczna macierz podkategorii"))
        headers = [
            tr("Podkategoria"),
            *[format_date(m) for m in months],
            tr("Suma"),
            tr("Średnia miesięczna"),
        ]
        self.matrix.setColumnCount(len(headers))
        self.matrix.setHorizontalHeaderLabels(headers)
        self.matrix.setRowCount(len(rows) + 1)
        totals = [sum(values[i] for _, values in rows) for i in range(len(months))]
        maximum = max([abs(v) for _, values in rows for v in values], default=0)
        share = self.display.currentData()
        for r, (title, values) in enumerate([*rows, (tr("Suma"), totals)]):
            footer = r == len(rows)
            total = sum(values)
            denominator = sum(totals)
            texts = [title]
            for i, v in enumerate(values):
                texts.append(
                    f"{100 * v / totals[i]:.2f}%"
                    if share and totals[i]
                    else "—"
                    if share
                    else amount_label(v)
                )
            texts.extend(
                [
                    f"{100 * total / denominator:.2f}%"
                    if share and denominator
                    else "—"
                    if share
                    else amount_label(total),
                    amount_label(average_minor(values)),
                ]
            )
            for c, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif not footer:
                    item.setIcon(dot(shade(self.data, root, r)))
                if footer or c > len(months):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if not footer and 1 <= c <= len(months) and maximum:
                    base = QColor(display_color(SURFACE))
                    accent = QColor(category_chart_color(self.data, root))
                    weight = 0.08 + 0.45 * abs(values[c - 1]) / maximum
                    mixed = QColor(
                        *[
                            round(a * (1 - weight) + b * weight)
                            for a, b in zip(base.getRgb()[:3], accent.getRgb()[:3])
                        ]
                    )
                    item.setBackground(mixed)
                    item.setForeground(QColor("#062536" if mixed.lightnessF() > 0.6 else "#EDF4FF"))
                self.matrix.setItem(r, c, item)
        header = self.matrix.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.trends.setRowCount(len(rows))
        for index, (name, values) in enumerate(rows):
            self.trends.setRowHeight(index, 115)
            for col, text in (
                (0, name),
                (2, amount_label(sum(values))),
                (3, amount_label(average_minor(values))),
            ):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setIcon(dot(shade(self.data, root, index)))
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.trends.setItem(index, col, item)
            canvas = ExpandableCanvas(Figure(figsize=(5, 1.3), layout="constrained"))
            canvas.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            canvas.setAutoFillBackground(False)
            canvas.setStyleSheet("background: transparent;")
            canvas.setMinimumWidth(180)
            plot_data = dict(
                self.data, explorer_root=root, explorer_color=shade(self.data, root, index)
            )
            render_trend(canvas.figure, name, plot_data)
            canvas.enlarge_requested.connect(
                lambda name=name, data=plot_data: self.enlarge(name, data)
            )
            self.trends.setCellWidget(index, 1, canvas)
            self.trend_canvases.append(canvas)
            canvas.draw_idle()

    def open_transactions(self, *, child=None, month=None):
        if self.data is None or self.selection is None:
            return
        root, selected_child = self.selection
        child = selected_child if child is None else child
        ids = [
            c["row"]["id"]
            for c in self.data["contributions"]
            if c["root"] == root
            and (child is None or child_name(c) == child)
            and (month is None or c["row"]["date"][:7] == month)
        ]
        self.owner.open_rows(ids)

    def open_cell_transactions(self, row, column):
        if self.selection is None:
            return
        child = self.current_rows[row][0] if row < len(self.current_rows) else self.selection[1]
        month = self.current_months[column - 1] if 1 <= column <= len(self.current_months) else None
        self.open_transactions(child=child, month=month)

    def enlarge(self, name, data):
        dialog = ChartDialog(
            self,
            name,
            data,
            renderer=render_trend,
            title=name,
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
