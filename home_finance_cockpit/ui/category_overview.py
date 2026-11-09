"""Category overview and the existing category detail view in two subtabs."""

from decimal import ROUND_HALF_UP, Decimal

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import language, tr
from home_finance_cockpit.ui.chart_helpers import category_chart_color
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import display_color


def overview_amount(value, currency):
    text = amount_label(value, currency)
    return text.replace(".", ",") if language() == "pl" else text


def overview_share(value, total):
    text = f"{value / total:.1%}" if total else "0%"
    return text.replace(".", ",") if language() == "pl" else text


def expense_groups(data):
    """Aggregate only outgoing transactions, preserving real category IDs/icons."""
    groups = {}
    uncategorized = [0, 0]
    for row in data["rows"]:
        if row["amount_minor"] >= 0:
            continue
        value = -row["amount_minor"]
        root = row["root_category_id"]
        group = groups.setdefault(root, {"amount": 0, "count": 0, "children": {}})
        group["amount"] += value
        group["count"] += 1
        child_id = row["category_id"]
        child = group["children"].setdefault(
            child_id,
            {"name": row["subcategory"] or tr("Bez podkategorii"), "amount": 0, "count": 0},
        )
        child["amount"] += value
        child["count"] += 1
        if row["is_uncategorized"]:
            uncategorized[0] += value
            uncategorized[1] += 1
    return dict(sorted(groups.items(), key=lambda pair: -pair[1]["amount"])), uncategorized


class ExpenseRing(QWidget):
    def __init__(self):
        super().__init__()
        self.values = []
        self.total, self.count, self.currency = 0, 0, ""
        self.setMinimumSize(px(190), px(190))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Include the stroke outside the arc's bounds in the available space.
        side = max(0, min((self.width() - px(24)) / 1.13, (self.height() - px(24)) / 1.13, px(300)))
        thickness = side * 0.13
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        pen = QPen(QColor(display_color("#24394d")), thickness)
        painter.setPen(pen)
        painter.drawEllipse(box)
        start = 90 * 16
        for value, color in self.values:
            span = value / self.total * 360 * 16
            pen.setColor(QColor(color))
            painter.setPen(pen)
            painter.drawArc(box, round(start - 16), -round(max(0, span - 32)))
            start -= span
        center = self.rect().center().y()
        painter.setPen(QColor(display_color("#a8bed5")))
        font = self.font()
        font.setPixelSize(px(11))
        painter.setFont(font)
        painter.drawText(
            QRectF(0, center - px(40), self.width(), px(22)),
            Qt.AlignmentFlag.AlignCenter,
            tr("WYDATKI"),
        )
        font.setPixelSize(px(19))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(display_color("#edf4ff")))
        painter.drawText(
            QRectF(0, center - px(13), self.width(), px(30)),
            Qt.AlignmentFlag.AlignCenter,
            overview_amount(self.total, self.currency),
        )
        font.setPixelSize(px(11))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(display_color("#a8bed5")))
        caption = tr("Transakcje: {v0}", v0=self.count) if self.total else tr("Brak wydatków")
        painter.drawText(
            QRectF(0, center + px(20), self.width(), px(24)), Qt.AlignmentFlag.AlignCenter, caption
        )


class CategoryOverview(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        cards = QHBoxLayout()
        self.metrics = []
        for title in ("Wydatki łącznie", "Największa kategoria", "Średni wydatek", "Bez kategorii"):
            card, content = panel()
            content.setContentsMargins(px(12), px(8), px(12), px(8))
            content.setSpacing(px(3))
            content.addWidget(label(tr(title)))
            value, detail = label("—", "section"), label("—")
            value.setMinimumWidth(0)
            content.addWidget(value)
            content.addWidget(detail)
            cards.addWidget(card, 1)
            self.metrics.append((value, detail))
        layout.addLayout(cards)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        chart, chart_layout = panel("Struktura wydatków")
        self.ring = ExpenseRing()
        chart_layout.addWidget(self.ring, 3)
        self.legend = QTreeWidget()
        self.legend.setColumnCount(2)
        self.legend.setHeaderHidden(True)
        self.legend.setRootIsDecorated(False)
        self.legend.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.legend.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.legend.setStyleSheet("QTreeWidget {background: transparent; border: 0;}")
        self.legend.setMinimumHeight(px(100))
        self.legend.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.legend.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.legend.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        chart_layout.addWidget(self.legend, 2)
        split.addWidget(chart)
        frame, content = panel()
        heading = QHBoxLayout()
        heading.addWidget(label(tr("Kategorie i podkategorie"), "section"), 1)
        self.expand = QPushButton(tr("Zwiń wszystkie"))
        self.expand.clicked.connect(self.toggle_expansion)
        heading.addWidget(self.expand)
        content.addLayout(heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [tr(t) for t in ("Kategoria / podkategoria", "Transakcje", "Suma wydatków", "Udział")]
        )
        for column in range(4):
            self.tree.headerItem().setTextAlignment(
                column, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(px(19), px(19)))
        self.tree.setIndentation(px(22))
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setMinimumSectionSize(px(100))
        for column, width in ((1, 135), (2, 185), (3, 110)):
            self.tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(column, px(width))
        self.tree.itemExpanded.connect(self.sync_expand)
        self.tree.itemCollapsed.connect(self.sync_expand)
        content.addWidget(self.tree)
        split.addWidget(frame)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([360, 800])
        layout.addWidget(split, 1)

    def sync_expand(self, *_):
        self.expand.setText(
            tr("Zwiń wszystkie")
            if any(
                self.tree.topLevelItem(i).isExpanded() for i in range(self.tree.topLevelItemCount())
            )
            else tr("Rozwiń wszystkie")
        )

    def toggle_expansion(self):
        if any(
            self.tree.topLevelItem(i).isExpanded() for i in range(self.tree.topLevelItemCount())
        ):
            self.tree.collapseAll()
        else:
            self.tree.expandAll()
        self.sync_expand()

    def refresh(self, data):
        collapsed = {
            self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.tree.topLevelItemCount())
            if not self.tree.topLevelItem(i).isExpanded()
        }
        self.tree.clear()
        self.legend.clear()
        groups, uncategorized = expense_groups(data) if data else ({}, [0, 0])
        total = sum(g["amount"] for g in groups.values())
        count = sum(g["count"] for g in groups.values())
        currency = data["currency"] if data else ""
        largest = next(iter(groups), None)
        average = (
            int((Decimal(total) / count).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if count
            else 0
        )
        values = [
            (overview_amount(total, currency), tr("Transakcje: {v0}", v0=count)),
            (
                data["category_names"].get(largest, "—") if groups else "—",
                overview_share(groups[largest]["amount"], total) if total else "—",
            ),
            (overview_amount(average, currency), tr("na jedną transakcję")),
            (
                overview_amount(uncategorized[0], currency),
                tr("Do przypisania: {v0}", v0=uncategorized[1]),
            ),
        ]
        for (value, detail), (v, d) in zip(self.metrics, values):
            value.setText(v)
            detail.setText(d)
        self.metrics[0][0].setStyleSheet(f"color: {display_color('#22d3ee')}; font-weight: 600;")
        self.ring.total, self.ring.count, self.ring.currency = total, count, currency
        self.ring.values = []
        for root, group in groups.items():
            color = category_chart_color(data, root)
            name = data["category_names"].get(root, tr("Bez kategorii"))
            self.ring.values.append((group["amount"], color))
            legend = QTreeWidgetItem([name, overview_amount(group["amount"], currency)])
            legend.setSizeHint(0, QSize(0, px(29)))
            legend.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            legend.setForeground(0, QColor(color))
            legend.setToolTip(0, name)
            self.legend.addTopLevelItem(legend)
            parent = self.make_item(name, root, group, total, currency, data, color)
            self.tree.addTopLevelItem(parent)
            for child_id, child in sorted(
                group["children"].items(), key=lambda pair: -pair[1]["amount"]
            ):
                # A direct assignment to a root is shown as "Bez podkategorii".
                parent.addChild(
                    self.make_item(child["name"], child_id, child, total, currency, data, color)
                )
            parent.setExpanded(root not in collapsed)
        self.ring.update()
        self.sync_expand()

    @staticmethod
    def make_item(name, category_id, values, total, currency, data, color):
        item = QTreeWidgetItem(
            [
                name,
                str(values["count"]),
                overview_amount(values["amount"], currency),
                overview_share(values["amount"], total),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, category_id)
        item.setIcon(0, icon(data.get("category_icons", {}).get(category_id) or "tag", color))
        item.setToolTip(0, name)
        item.setSizeHint(0, QSize(0, px(35)))
        for column in range(4):
            item.setTextAlignment(
                column, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        return item


class CategoryViews(QWidget):
    def __init__(self, owner, details):
        super().__init__(owner)
        self.data = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabBar()
        self.tabs.setObjectName("categoryViewTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setStyleSheet(
            "QTabBar#categoryViewTabs {background: transparent;"
            f"border-bottom: 1px solid {display_color('#24394d')};}}"
            "QTabBar#categoryViewTabs::tab {"
            "background: transparent; border: 0; border-bottom: 3px solid transparent;"
            f"color: {display_color('#a8bed5')};"
            f"padding: {px(10)}px {px(20)}px; margin-right: {px(4)}px;"
            "} QTabBar#categoryViewTabs::tab:selected {"
            f"color: {display_color('#22d3ee')};"
            f"border-bottom: 3px solid {display_color('#22d3ee')}; font-weight: 600;"
            "} QTabBar#categoryViewTabs::tab:hover:!selected {"
            f"background: {display_color('#112233')};"
            f"color: {display_color('#edf4ff')};"
            "}"
        )
        self.tabs.addTab(tr("Przegląd"))
        self.tabs.addTab(tr("Szczegóły"))
        layout.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.overview = CategoryOverview(owner)
        self.stack.addWidget(self.overview)
        self.stack.addWidget(details)
        layout.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.change_view)

    def change_view(self, index):
        self.stack.setCurrentIndex(index)
        self.stack.currentWidget().refresh(self.data)

    def refresh(self, data):
        self.data = data
        self.stack.currentWidget().refresh(data)
