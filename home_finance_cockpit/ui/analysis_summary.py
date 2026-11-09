"""Monthly overview with shared, exact chart and table totals."""

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QHeaderView, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.chart_helpers import category_chart_color, show_empty_chart
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.common import table
from home_finance_cockpit.ui.components import panel
from home_finance_cockpit.ui.theme import ACCENT, RED, SUCCESS, display_color


def summary_rows(data):
    months = data["months"]
    roots = sorted(
        data["categories"],
        key=lambda k: (-data["categories"][k], data["category_names"].get(k, "")),
    )
    rows = [
        (root, [data["monthly"][m]["categories"].get(root, 0) for m in months]) for root in roots
    ]
    return months, rows


def change_text(current, previous):
    if previous is None:
        return "—", "—", None
    delta = current - previous
    prefix = "+" if delta > 0 else ""
    return (
        prefix + amount_label(delta),
        (f"{prefix}{100 * delta / abs(previous):.2f}%" if previous else "—"),
        delta,
    )


def render_summary(figure, key, data, percentage=True):
    figure.clear()
    ax = figure.add_subplot(111)
    months, rows = summary_rows(data)
    ax.set_title(
        tr("Wydatki miesięczne") if key == "months" else tr("Udział kategorii"), loc="left", pad=18
    )
    if not months or not rows:
        show_empty_chart(ax)
        return ax
    if key == "months":
        values = [data["monthly"][m]["cost"] for m in months]
        bars = ax.bar(
            range(len(months)), [v / 100 for v in values], color=display_color(ACCENT), width=0.55
        )
        ax.bar_label(bars, labels=[amount_label(v) for v in values], padding=8, fontsize=9)
        for i, (month, value) in enumerate(zip(months, values)):
            from home_finance_cockpit.reports.data import previous_month

            previous = data["monthly"].get(previous_month(month))
            if previous is not None and previous["cost"]:
                _, percent, delta = change_text(value, previous["cost"])
                annotation = ax.annotate(
                    percent,
                    (i, value / 100),
                    xytext=(0, 26),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
                annotation._semantic_color = RED if delta > 0 else SUCCESS
        ax.set_xticks(range(len(months)), [format_date(m) for m in months])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.grid(axis="y", alpha=0.15)
        ax.set_axisbelow(True)
        ax.margins(y=0.28)
    else:
        roots = [r for r, _ in rows]
        values = [data["categories"][r] for r in roots]
        bars = ax.barh(
            range(len(roots)),
            [v / 100 for v in values],
            color=[category_chart_color(data, r) for r in roots],
            height=0.55,
        )
        ax.set_yticks(range(len(roots)), [data["category_names"].get(r, "—") for r in roots])
        ax.invert_yaxis()
        total = data["cost"]
        ax.bar_label(
            bars,
            labels=[
                amount_label(v) + (f"  ·  {100 * v / total:.2f}%" if total > 0 else "")
                for v in values
            ],
            padding=6,
            fontsize=8,
        )
        ax.margins(x=0.75, y=0.08)
        ax.set_xticks([])
        ax._analysis_targets = {bar: ("category", root) for bar, root in zip(bars, roots)}
        for bar in bars:
            bar.set_picker(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    return ax


class AnalysisSummary(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.data = owner, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter(Qt.Orientation.Horizontal)
        self.canvases = []
        for key in ("months", "categories"):
            frame, content = panel()
            canvas = ExpandableCanvas(Figure(figsize=(6, 3), layout="constrained"))
            canvas.setMinimumSize(180, 140)
            canvas.enlarge_requested.connect(lambda key=key: self.enlarge(key))
            canvas.mpl_connect("pick_event", owner.pick_category)
            content.addWidget(canvas)
            upper.addWidget(frame)
            self.canvases.append(canvas)
        upper.setStretchFactor(0, 3)
        upper.setStretchFactor(1, 2)
        upper.setSizes([650, 450])
        lower, content = panel("Miesięczny podział kategorii")
        self.table = table([])
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(self.table.SelectionMode.NoSelection)
        content.addWidget(self.table)
        self.splitter.addWidget(upper)
        self.splitter.addWidget(lower)
        self.splitter.setSizes([380, 340])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)

    def refresh(self, data):
        self.data = data
        for canvas, key in zip(self.canvases, ("months", "categories")):
            if data is None:
                canvas.figure.clear()
            else:
                render_summary(canvas.figure, key, data)
            canvas.draw_idle()
        months, rows = summary_rows(data) if data else ([], [])
        headers = [
            tr("Kategoria"),
            *[format_date(m) for m in months],
            tr("Zmiana kwoty"),
            tr("Zmiana %"),
        ]
        if len(months) > 1:
            comparison = f"{format_date(months[-2])} → {format_date(months[-1])}"
            headers[-2] += "\n" + comparison
            headers[-1] += "\n" + comparison
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for col in range(1, len(headers)):
            self.table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setRowCount(len(rows) + bool(months))
        for index, (root, values) in enumerate(
            [*rows, *([(None, [data["monthly"][m]["cost"] for m in months])] if months else [])]
        ):
            total_row = index == len(rows)
            title = tr("Suma") if total_row else data["category_names"].get(root, "—")
            previous = (
                values[-2] if len(values) > 1 and self.adjacent(months[-2], months[-1]) else None
            )
            delta, percent, sign = change_text(values[-1], previous)
            for col, text in enumerate([title, *[amount_label(v) for v in values], delta, percent]):
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if total_row:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if col >= len(headers) - 2 and sign:
                    item.setForeground(QColor(display_color(RED if sign > 0 else SUCCESS)))
                if col == 0 and not total_row:
                    item.setForeground(QColor(category_chart_color(data, root)))
                self.table.setItem(index, col, item)
        if len(months) > 1:
            tip = f"{format_date(months[-2])} → {format_date(months[-1])}"
            for col in (len(headers) - 2, len(headers) - 1):
                self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )

    @staticmethod
    def adjacent(previous, current):
        from home_finance_cockpit.reports.data import previous_month

        return previous_month(current) == previous

    def enlarge(self, key):
        if self.data is None:
            return
        dialog = ChartDialog(
            self,
            key,
            self.data,
            renderer=render_summary,
            title=tr("Wydatki miesięczne") if key == "months" else tr("Udział kategorii"),
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
