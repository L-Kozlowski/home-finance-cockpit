"""Comparison controls, change drivers, period profile and paired amounts."""

from matplotlib.figure import Figure
from matplotlib.text import Annotation
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.period_comparison import comparison
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.chart_helpers import show_empty_chart
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.theme import ACCENT, BLUE, MUTED, RED, SUCCESS, display_color


class PeriodProfile(QWidget):
    def __init__(self):
        super().__init__()
        self.rows = QGridLayout(self)
        self.rows.setContentsMargins(0, 8, 0, 0)
        self.rows.setColumnStretch(0, 2)
        self.rows.setColumnStretch(1, 1)
        self.rows.setColumnStretch(2, 1)

    def refresh(self, result, after_refunds=False):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if result is None:
            return
        for column, key, tint in ((1, "a", BLUE), (2, "b", ACCENT)):
            heading = label(format_date(result[key]["month"]), "section")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet(f"color:{display_color(tint)};")
            self.rows.addWidget(heading, 0, column)
        metrics = [
            (tr("Wydatki brutto") if not after_refunds else tr("Po zwrotach"), "total"),
            (tr("Średnia dzienna"), "average"),
            (tr("Liczba wydatków"), "count"),
            (tr("Mediana transakcji"), "median"),
            (tr("Najwyższy wydatek dzienny"), "highest"),
        ]
        for index, (caption, key) in enumerate(metrics):
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("color:#24394D;")
            self.rows.addWidget(line, index * 2 + 1, 0, 1, 3)
            self.rows.addWidget(label(caption), index * 2 + 2, 0)
            for column, period in enumerate((result["a"], result["b"]), 1):
                value = period[key]
                text = (
                    "—"
                    if value is None
                    else str(value)
                    if key == "count"
                    else amount_label(round(value))
                )
                item = label(text, "section" if key == "total" else "")
                item.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.rows.addWidget(item, index * 2 + 2, column)
            self.rows.setRowStretch(index * 2 + 2, 1)


class CategoryAmountLabel(Annotation):
    """Recheck category-name collisions at each draw, including window resizing."""

    def overlaps_category(self, renderer):
        bounds = self.get_window_extent(renderer)
        return any(
            bounds.overlaps(label.get_window_extent(renderer).expanded(1.02, 1.1))
            for label in self.axes.get_yticklabels()
            if label.get_visible() and label.get_text()
        )

    def draw(self, renderer):
        if self.get_visible() and not self.overlaps_category(renderer):
            super().draw(renderer)


def render_comparison(figure, key, data, percentage=True):
    figure.clear()
    figure._transparent_chart = True
    if key == "changes":
        grid = figure.add_gridspec(1, 3, width_ratios=[5, 1.55, 1.35], wspace=0.04)
        ax = figure.add_subplot(grid[0, 0])
        amount_ax = figure.add_subplot(grid[0, 1], sharey=ax)
        percent_ax = figure.add_subplot(grid[0, 2], sharey=ax)
    else:
        ax = figure.add_subplot(111)
    roots = data["roots"][:12]
    values = data["values"]
    ax._comparison_targets = {}
    if not roots:
        show_empty_chart(ax)
        return ax
    labels = [data["category_names"].get(root, "—") for root in roots]
    if key == "changes":
        deltas = [values[root][1] - values[root][0] for root in roots]
        bars = ax.barh(
            range(len(roots)),
            [v / 100 for v in deltas],
            height=0.48,
            color=[display_color(RED if v > 0 else SUCCESS if v < 0 else MUTED) for v in deltas],
        )
        for i, (root, delta, bar) in enumerate(zip(roots, deltas, bars)):
            a, b = values[root]
            percent = f"{100 * delta / abs(a):+.2f}%" if a else "—"
            text = ("+" if delta > 0 else "") + amount_label(round(delta))
            for column_axis, content in ((amount_ax, text), (percent_ax, percent)):
                value_text = column_axis.text(
                    0.5,
                    i,
                    content,
                    ha="center",
                    va="center",
                    transform=column_axis.get_yaxis_transform(),
                )
                value_text._semantic_color = RED if delta > 0 else SUCCESS if delta < 0 else MUTED
            bar.set_picker(True)
            ax._comparison_targets[bar] = root
        ax.axvline(0, color=display_color(MUTED), linewidth=0.6)
        ax.margins(x=0.18)
        for column_axis, title in (
            (amount_ax, tr("Zmiana kwoty") + " (" + data["currency"] + ")"),
            (percent_ax, tr("Zmiana %")),
        ):
            column_axis.text(
                0.5, 1.04, title, transform=column_axis.transAxes, ha="center", va="bottom"
            )
            column_axis.set_axis_off()
    else:
        for i, root in enumerate(roots):
            a, b = values[root]
            ax.plot([a / 100, b / 100], [i, i], color=display_color(MUTED), linewidth=1)
            for period, value, tint in (("a", a, BLUE), ("b", b, ACCENT)):
                point = ax.scatter(
                    [value / 100],
                    [i],
                    color=display_color(tint),
                    s=35,
                    label=format_date(data[period]["month"]) if i == 0 else None,
                    picker=True,
                )
                ax._comparison_targets[point] = root
                if round(value) == 0 or (a == b and period == "a"):
                    continue
                left = value == min(a, b) and a != b
                annotation = CategoryAmountLabel(
                    amount_label(round(value)),
                    (value / 100, i),
                    xytext=(-9 if left else 9, 0),
                    textcoords="offset points",
                    ha="right" if left else "left",
                    va="center",
                    fontsize=8,
                )
                annotation._semantic_color = tint
                ax.add_artist(annotation)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2, fontsize=8)
        ax.margins(x=0.18, y=0.22)
        all_values = [v / 100 for root in roots for v in values[root]]
        ax.set_xlim(min(0, min(all_values) * 1.15), max(1, max(all_values) * 1.18))
    ax.set_yticks(range(len(roots)), labels)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
    unit = data["currency"] + (" / " + tr("dzień") if data["per_day"] else "")
    ax.text(-0.065, -0.025, unit, transform=ax.transAxes, ha="right", va="top")
    ax.grid(axis="x", alpha=0.15)
    ax.set_axisbelow(True)
    return ax


class PeriodComparison(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.data = None
        self.result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        control_panel, control_layout = panel()
        controls = QHBoxLayout()
        self.period_a = QComboBox()
        self.period_b = QComboBox()
        for combo in (self.period_a, self.period_b):
            combo.setMinimumContentsLength(10)
            combo.currentIndexChanged.connect(self.render)
        controls.addWidget(label(tr("Okres A")))
        controls.addWidget(self.period_a, 1)
        swap = QPushButton()
        swap.setIcon(icon("transactions"))
        swap.setToolTip(tr("Zamień okresy"))
        swap.clicked.connect(self.swap)
        controls.addWidget(swap)
        controls.addWidget(label(tr("Okres B")))
        controls.addWidget(self.period_b, 1)
        self.method = QComboBox()
        self.method.addItem(tr("Taka sama liczba dni"), True)
        self.method.addItem(tr("Pełne okresy"), False)
        controls.addWidget(label(tr("Metoda porównania")))
        self.method.currentIndexChanged.connect(self.render)
        controls.addWidget(self.method)
        controls.addStretch(1)
        self.normalization = QComboBox()
        self.normalization.addItem(tr("Suma"), False)
        self.normalization.addItem(tr("Dziennie"), True)
        self.normalization.hide()
        self.normalization.currentIndexChanged.connect(self.render)
        segments = QWidget()
        segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(0, 0, 0, 0)
        segment_layout.setSpacing(0)
        segments.setStyleSheet(
            "QPushButton:checked {background:#22D3EE; color:#062536; border-color:#22D3EE;}"
        )
        self.normalization_group = QButtonGroup(self)
        self.normalization_buttons = []
        for index, caption in enumerate(("Suma", "Dziennie")):
            button = QPushButton(tr(caption))
            button.setCheckable(True)
            button.setMinimumWidth(90)
            button.setChecked(index == 0)
            button.clicked.connect(
                lambda checked=False, index=index: self.normalization.setCurrentIndex(index)
            )
            self.normalization_group.addButton(button)
            self.normalization_buttons.append(button)
            segment_layout.addWidget(button)
        controls.addWidget(segments)
        control_layout.addLayout(controls)
        self.scope = label("")
        self.scope.hide()
        control_layout.addWidget(self.scope)
        layout.addWidget(control_panel)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter(Qt.Orientation.Horizontal)
        changes, box = panel("Przyczyny zmian wydatków")
        self.changes_canvas = self.make_canvas("changes")
        box.addWidget(self.changes_canvas, 1)
        upper.addWidget(changes)
        profile, box = panel("Profil okresów")
        self.profile = PeriodProfile()
        box.addWidget(self.profile)
        upper.addWidget(profile)
        upper.setSizes([650, 450])
        upper.setChildrenCollapsible(False)
        lower, box = panel()
        heading = QHBoxLayout()
        self.title = label(tr("Porównanie kategorii"), "section")
        heading.addWidget(self.title, 1)
        self.transactions = QPushButton(tr("Zobacz zmienione transakcje"))
        self.transactions.setIcon(icon("transactions"))
        self.transactions.clicked.connect(lambda: self.open_changed())
        heading.addWidget(self.transactions)
        box.addLayout(heading)
        self.paired_canvas = self.make_canvas("paired")
        box.addWidget(self.paired_canvas, 1)
        self.splitter.addWidget(upper)
        self.splitter.addWidget(lower)
        self.splitter.setSizes([350, 330])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

    def make_canvas(self, key):
        canvas = ExpandableCanvas(Figure(figsize=(6, 3), layout="constrained"))
        canvas.setMinimumSize(200, 140)
        canvas.enlarge_requested.connect(lambda: self.enlarge(key))
        canvas.mpl_connect("pick_event", self.pick)
        return canvas

    def refresh(self, data):
        self.data = data
        months = data["comparison_months"] if data else []
        for combo, fallback in (
            (self.period_a, max(0, len(months) - 2)),
            (self.period_b, len(months) - 1),
        ):
            current = combo.currentData()
            with QSignalBlocker(combo):
                combo.clear()
                for month in months:
                    combo.addItem(format_date(month), month)
                index = combo.findData(current)
                combo.setCurrentIndex(index if index >= 0 else fallback)
        self.render()

    def swap(self):
        a, b = self.period_a.currentIndex(), self.period_b.currentIndex()
        with QSignalBlocker(self.period_a), QSignalBlocker(self.period_b):
            self.period_a.setCurrentIndex(b)
            self.period_b.setCurrentIndex(a)
        self.render()

    def render(self, *_):
        for index, button in enumerate(self.normalization_buttons):
            button.setChecked(index == self.normalization.currentIndex())
        a, b = self.period_a.currentData(), self.period_b.currentData()
        if self.data is None or not a or not b:
            self.result = None
            self.profile.refresh(None)
            self.transactions.setEnabled(False)
            self.scope.clear()
            for canvas in (self.changes_canvas, self.paired_canvas):
                canvas.figure.clear()
                canvas.draw_idle()
            return
        self.result = comparison(
            self.data,
            a,
            b,
            equal_days=self.method.currentData(),
            per_day=self.normalization.currentData(),
        )
        result = self.result
        ranges = []
        for p in (result["a"], result["b"]):
            start = p["month"] + "-01"
            end = p["month"] + "-" + str(p["days"]).zfill(2)
            ranges.append(format_date(start) + " – " + format_date(end))
        self.scope.setText("   |   ".join(ranges))
        self.method.setToolTip(self.scope.text())
        self.title.setText(tr("Porównanie kategorii") + f" · {format_date(a)} → {format_date(b)}")
        self.transactions.setEnabled(bool(result["changed_ids"]))
        for canvas, key in ((self.changes_canvas, "changes"), (self.paired_canvas, "paired")):
            render_comparison(canvas.figure, key, result)
            canvas.draw_idle()
        self.profile.refresh(result, self.data["after_refunds"])

    def open_changed(self, root=...):
        if self.result is None:
            return
        ids = (
            self.result["changed_ids"]
            if root is Ellipsis
            else sorted(
                {
                    c["row"]["id"]
                    for p in (self.result["a"], self.result["b"])
                    for c in p["contributions"]
                    if c["root"] == root
                }
            )
        )
        self.owner.open_rows(ids)

    def pick(self, event):
        targets = getattr(event.artist.axes, "_comparison_targets", {})
        if event.artist in targets:
            self.open_changed(targets[event.artist])

    def enlarge(self, key):
        if self.result is None:
            return
        dialog = ChartDialog(
            self,
            key,
            self.result,
            renderer=render_comparison,
            title=tr("Porównanie kategorii"),
            context=self.scope.text(),
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
