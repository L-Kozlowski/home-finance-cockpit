"""Daily calendar and spending rhythm, using the active analytical scope."""

from calendar import monthcalendar, monthrange
from datetime import date

import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PyQt6.QtCore import QRectF, QSignalBlocker, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.category_explorer import HeatLegend
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.theme import ACCENT, MUTED, SURFACE, TEXT, display_color

WEEKDAYS = ("Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz")


class WeekdayOverview(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.data = None
        self.setMinimumSize(260, 190)

    def paintEvent(self, event):
        if not self.data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        averages, counts = weekday_averages(self.data)
        width = self.width()
        height = self.height()
        header = 32
        row_height = (height - header) / 7
        painter.setPen(QColor(display_color(MUTED)))
        painter.drawText(
            QRectF(0, 0, 60, header), Qt.AlignmentFlag.AlignVCenter, tr("Dzień tygodnia")
        )
        painter.drawText(
            QRectF(width * 0.61, 0, width * 0.21, header),
            Qt.AlignmentFlag.AlignCenter,
            tr("Średni wydatek") + f" ({self.data['currency']})",
        )
        painter.drawText(
            QRectF(width * 0.84, 0, width * 0.16, header),
            Qt.AlignmentFlag.AlignCenter,
            tr("Liczba dni"),
        )
        maximum = max(averages) or 1
        for index, (value, count) in enumerate(zip(averages, counts)):
            top = header + row_height * index
            middle = top + row_height / 2
            painter.setPen(QColor(display_color("#24394D")))
            painter.drawLine(0, int(top), width, int(top))
            painter.setPen(QColor(display_color(TEXT)))
            painter.drawText(
                QRectF(0, top, 58, row_height), Qt.AlignmentFlag.AlignVCenter, tr(WEEKDAYS[index])
            )
            bar = QRectF(
                62,
                middle - row_height * 0.2,
                max(0, (width * 0.59 - 62) * value / maximum),
                row_height * 0.4,
            )
            if bar.width() > 0:
                gradient = QLinearGradient(bar.topLeft(), bar.bottomLeft())
                gradient.setColorAt(0, QColor("#55E8FF"))
                gradient.setColorAt(0.45, QColor(display_color(ACCENT)))
                gradient.setColorAt(1, QColor("#06B6D4"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawRoundedRect(bar, 1.5, 1.5)
            painter.setPen(QColor(display_color(TEXT)))
            painter.drawText(
                QRectF(width * 0.61, top, width * 0.21, row_height),
                Qt.AlignmentFlag.AlignCenter,
                amount_label(round(value)),
            )
            painter.setPen(QColor(display_color(MUTED)))
            painter.drawText(
                QRectF(width * 0.84, top, width * 0.16, row_height),
                Qt.AlignmentFlag.AlignCenter,
                str(count),
            )

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner.enlarge("weekday")


def observed_days(months, today=None):
    today = today or date.today()
    for month in months:
        year, number = map(int, month.split("-"))
        for day in range(1, monthrange(year, number)[1] + 1):
            value = date(year, number, day)
            if month != today.strftime("%Y-%m") or value <= today:
                yield value


def weekday_averages(data, today=None):
    sums, counts = [0] * 7, [0] * 7
    for day in observed_days(data["months"], today):
        index = day.weekday()
        counts[index] += 1
        sums[index] += data["daily"].get(day.isoformat(), 0)
    return [total / count if count else 0 for total, count in zip(sums, counts)], counts


def render_time_chart(figure, key, data, percentage=True):
    figure.clear()
    figure._transparent_chart = True
    ax = figure.add_subplot(111)
    if key == "daily":
        month = data["calendar_month"]
        if not month:
            return ax
        days = list(observed_days([month]))
        # Future example transactions remain inspectable in the calendar and chart.
        year, number = map(int, month.split("-"))
        elapsed = max(
            [day.day for day in days]
            + [int(d[-2:]) for d in data["daily"] if d.startswith(month)]
            + [1]
        )
        last = monthrange(year, number)[1]
        values = [data["daily"].get(f"{month}-{day:02d}", 0) for day in range(1, last + 1)]
        bars = ax.bar(
            range(1, last + 1), [v / 100 for v in values], color=display_color(ACCENT), width=0.65
        )
        limits = ax.get_xlim(), ax.get_ylim()
        cmap = LinearSegmentedColormap.from_list("daily_bar", ["#06B6D4", "#22D3EE", "#55E8FF"])
        for bar in bars:
            if bar.get_height() == 0:
                continue
            x, y = bar.get_x(), bar.get_y()
            height = bar.get_height()
            bar.set_facecolor("none")
            image = ax.imshow(
                np.linspace(0, 1, 128).reshape(-1, 1),
                extent=(x, x + bar.get_width(), min(y, y + height), max(y, y + height)),
                origin="lower",
                aspect="auto",
                cmap=cmap,
                zorder=2,
            )
            image.set_clip_path(bar)
        ax.set_xlim(limits[0])
        ax.set_ylim(limits[1])
        mean = sum(values) / elapsed / 100
        ax.axhline(
            mean,
            color=display_color(ACCENT),
            linestyle="--",
            linewidth=1,
            label=tr("Średnia dzienna") + ": " + amount_label(round(mean * 100)),
        )
        for i in sorted(range(len(values)), key=lambda i: values[i], reverse=True)[:3]:
            if values[i] > 0:
                ax.annotate(
                    amount_label(values[i]),
                    (i + 1, values[i] / 100),
                    xytext=(0, 8),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
        ax.set_xticks(range(1, last + 1))
        ax.set_xlabel(tr("Dzień miesiąca"))
        ax.margins(y=0.25)
        ax.text(0, 1.04, data["currency"], transform=ax.transAxes, ha="left", va="bottom")
    else:
        averages, counts = weekday_averages(data)
        ax.barh(range(7), [v / 100 for v in averages], color=display_color(ACCENT), height=0.5)
        ax.set_yticks(range(7), [tr(day) for day in WEEKDAYS])
        ax.invert_yaxis()
        for i, (value, count) in enumerate(zip(averages, counts)):
            ax.text(
                value / 100,
                i,
                "  " + amount_label(round(value)) + f"  ·  {count} " + tr("dni"),
                va="center",
                fontsize=8,
            )
        ax.set_xlabel(tr("Średni wydatek dzienny") + f" ({data['currency']})")
        ax.margins(x=0.6)
    axis = ax.yaxis if key == "daily" else ax.xaxis
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))
    axis.set_major_locator(MaxNLocator(nbins=5))
    ax.grid(axis="y" if key == "daily" else "x", alpha=0.15)
    ax.set_axisbelow(True)
    return ax


class CalendarDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        payload = index.data(Qt.ItemDataRole.UserRole)
        painter.save()
        rect = option.rect.adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor(display_color(SURFACE)))
        if payload:
            day, amount, intensity = payload
            base = QColor(display_color(SURFACE))
            accent = QColor(display_color(ACCENT))
            weight = 0.08 + 0.7 * intensity if amount else 0
            mixed = QColor(
                *[
                    round(a * (1 - weight) + b * weight)
                    for a, b in zip(base.getRgb()[:3], accent.getRgb()[:3])
                ]
            )
            painter.fillRect(rect, mixed)
            painter.setPen(QColor("#062536" if mixed.lightnessF() > 0.6 else display_color(TEXT)))
            painter.drawText(
                rect.adjusted(8, 6, -6, -6),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                str(int(day[-2:])),
            )
            painter.drawText(
                rect.adjusted(4, 4, -8, -6),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
                amount_label(amount) if amount else "—",
            )
            if day == self.parent().selected_day:
                painter.setPen(QPen(QColor(display_color(ACCENT)), 2))
                painter.drawRoundedRect(rect, 4, 4)
        painter.restore()


class TimeOverview(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.data = None
        self.selected_day = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left, content = panel()
        header = QHBoxLayout()
        header.addWidget(label(tr("Przegląd dzienny"), "section"), 1)
        self.previous = QPushButton()
        self.next = QPushButton()
        for button, glyph, caption in (
            (self.previous, "back", "Poprzednie"),
            (self.next, "forward", "Następne"),
        ):
            button.setIcon(icon(glyph))
            button.setProperty("themeIcon", glyph)
            button.setToolTip(tr(caption))
            button.setAccessibleName(tr(caption))
        self.month = QComboBox()
        self.month.setMinimumContentsLength(16)
        self.month.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        self.month.currentIndexChanged.connect(self.render_month)
        header.addWidget(self.previous)
        header.addWidget(self.month)
        header.addWidget(self.next)
        content.addLayout(header)
        self.calendar = QTableWidget(0, 7)
        self.calendar.selected_day = None
        self.calendar.setHorizontalHeaderLabels([tr(d) for d in WEEKDAYS])
        self.calendar.verticalHeader().hide()
        self.calendar.setShowGrid(False)
        self.calendar.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.calendar.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.calendar.setItemDelegate(CalendarDelegate(self.calendar))
        self.calendar.cellClicked.connect(self.select_day)
        self.calendar.cellDoubleClicked.connect(self.activate_day)
        content.addWidget(self.calendar, 1)
        legend = QHBoxLayout()
        legend.addWidget(label(tr("Niższe wydatki")))
        legend.addWidget(HeatLegend(), 1)
        legend.addWidget(label(tr("Wyższe wydatki")))
        content.addLayout(legend)
        self.selection_bar, selection_layout = panel()
        selection_row = QHBoxLayout()
        self.selection_label = label("")
        selection_row.addWidget(self.selection_label, 1)
        self.transactions = QPushButton(tr("Zobacz transakcje"))
        self.transactions.setIcon(icon("transactions"))
        self.transactions.clicked.connect(self.open_day)
        selection_row.addWidget(self.transactions)
        selection_layout.addLayout(selection_row)
        content.addWidget(self.selection_bar)
        self.splitter.addWidget(left)
        self.right = QSplitter(Qt.Orientation.Vertical)
        self.canvases = []
        self.chart_titles = []
        for key, title in (
            ("daily", "Wydatki dzienne"),
            ("weekday", "Typowe wydatki według dnia tygodnia"),
        ):
            frame, box = panel()
            heading = label(tr(title), "section")
            self.chart_titles.append(heading)
            chart_header = QHBoxLayout()
            chart_header.addWidget(heading, 1)
            if key == "daily":
                self.daily_average = label("")
                self.daily_average.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.daily_average.setWordWrap(False)
                chart_header.addWidget(self.daily_average)
            box.addLayout(chart_header)
            canvas = ExpandableCanvas(Figure(figsize=(6, 3), layout="constrained"))
            canvas.setMinimumSize(220, 140)
            canvas.enlarge_requested.connect(lambda key=key: self.enlarge(key))
            box.addWidget(canvas, 1)
            self.canvases.append(canvas)
            self.right.addWidget(frame)
            if key == "weekday":
                canvas.hide()
                self.weekday_view = WeekdayOverview(self)
                box.addWidget(self.weekday_view, 1)
        self.right.setChildrenCollapsible(False)
        self.splitter.addWidget(self.right)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([550, 550])
        layout.addWidget(self.splitter)

    def refresh(self, data):
        self.data = data
        current = self.month.currentData()
        with QSignalBlocker(self.month):
            self.month.clear()
            for month in data["months"] if data else []:
                self.month.addItem(format_date(month), month)
            index = self.month.findData(current)
            self.month.setCurrentIndex(index if index >= 0 else self.month.count() - 1)
        self.render_month()

    def step(self, direction):
        index = self.month.currentIndex() + direction
        if 0 <= index < self.month.count():
            self.month.setCurrentIndex(index)

    def render_month(self, *_):
        month = self.month.currentData()
        index = self.month.currentIndex()
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < self.month.count() - 1)
        self.calendar.setRowCount(0)
        if not month or self.data is None:
            self.daily_average.clear()
            self.selected_day = None
            self.update_selection()
            self.weekday_view.data = None
            self.weekday_view.update()
            for canvas in self.canvases:
                canvas.figure.clear()
                canvas.draw_idle()
            return
        if not self.selected_day or not self.selected_day.startswith(month):
            self.selected_day = None
        self.calendar.selected_day = self.selected_day
        weeks = monthcalendar(*map(int, month.split("-")))
        self.calendar.setRowCount(len(weeks))
        maximum = max([abs(v) for d, v in self.data["daily"].items() if d.startswith(month)] + [1])
        for row, week in enumerate(weeks):
            for col, day in enumerate(week):
                item = QTableWidgetItem()
                if day:
                    iso = f"{month}-{day:02d}"
                    value = self.data["daily"].get(iso, 0)
                    item.setData(Qt.ItemDataRole.UserRole, (iso, value, abs(value) / maximum))
                    item.setToolTip(
                        format_date(iso) + " · " + amount_label(value, self.data["currency"])
                    )
                self.calendar.setItem(row, col, item)
        self.chart_titles[0].setText(tr("Wydatki dzienne") + " · " + format_date(month))
        months = self.data["months"]
        self.chart_titles[1].setText(
            tr("Typowe wydatki według dnia tygodnia")
            + " · "
            + format_date(months[0])
            + " – "
            + format_date(months[-1])
        )
        self.plot_data = dict(self.data, calendar_month=month)
        self.weekday_view.data = self.data
        self.weekday_view.update()
        for canvas, key in zip(self.canvases, ("daily", "weekday")):
            render_time_chart(canvas.figure, key, self.plot_data)
            canvas.draw_idle()
        daily_axis = self.canvases[0].figure.axes[0]
        mean = daily_axis.lines[0].get_ydata()[0] if daily_axis.lines else 0
        self.daily_average.setText(
            tr("Średnia dzienna") + ": " + amount_label(round(mean * 100), self.data["currency"])
        )
        self.update_selection()

    def select_day(self, row, col):
        item = self.calendar.item(row, col)
        payload = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not payload:
            return
        self.selected_day = payload[0]
        self.calendar.selected_day = self.selected_day
        self.calendar.viewport().update()
        self.update_selection()

    def activate_day(self, row, col):
        item = self.calendar.item(row, col)
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        self.select_day(row, col)
        self.open_day()

    def update_selection(self):
        self.transactions.setEnabled(self.selected_day is not None)
        if not self.selected_day or not self.data:
            self.selection_label.setText(tr("Wybierz dzień, aby zobaczyć transakcje."))
            return
        count = sum(r["date"] == self.selected_day for r in self.data["rows"])
        self.selection_label.setText(
            format_date(self.selected_day)
            + " · "
            + amount_label(self.data["daily"].get(self.selected_day, 0), self.data["currency"])
            + " · "
            + tr("Transakcje")
            + f": {count}"
        )

    def open_day(self):
        if self.selected_day and self.data:
            self.owner.open_rows(
                [r["id"] for r in self.data["rows"] if r["date"] == self.selected_day]
            )

    def enlarge(self, key):
        if self.data is None or self.month.currentData() is None:
            return
        dialog = ChartDialog(
            self,
            key,
            self.plot_data,
            renderer=render_time_chart,
            title=tr("Wydatki dzienne")
            if key == "daily"
            else tr("Typowe wydatki według dnia tygodnia"),
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
