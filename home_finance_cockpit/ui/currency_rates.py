"""Persisted daily FX quotes with independent date and multi-currency controls."""

from datetime import date
from decimal import Decimal

from matplotlib.dates import date2num
from matplotlib.figure import Figure
from PyQt6.QtCore import QDate, QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.chart_palettes import chart_colors
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.currency_history import CurrencyHistoryService
from home_finance_cockpit.ui.chart_dates import format_date, format_timestamp
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas
from home_finance_cockpit.ui.common import fill_table, show_error, table
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import INK, TEXT, display_color


def preferred_history(rows):
    """Use an NBP quote when both sources exist, retaining manual-only days."""
    selected = {}
    for row in rows:
        if row["quote_date"] not in selected or row["source"] == "NBP":
            selected[row["quote_date"]] = dict(row)
    return [selected[day] for day in sorted(selected)]


def render_rates(figure, key, data, percentage=False):
    figure.clear()
    ax = figure.add_subplot(111)
    figure._transparent_chart = True
    ax._rate_points = []
    colors = chart_colors()
    for index, (code, rows) in enumerate(data["series"].items()):
        if not rows:
            continue
        ax.plot(
            [date.fromisoformat(r["quote_date"]) for r in rows],
            [float(Decimal(r["rate"])) for r in rows],
            label=code + "/PLN",
            color=colors[index % len(colors)],
            linewidth=1.8,
            marker="o" if len(rows) < 45 else None,
            markersize=3,
        )
        for record in rows:
            x, y = (
                date2num(date.fromisoformat(record["quote_date"])),
                float(Decimal(record["rate"])),
            )
            ax._rate_points.append((code, record, x, y))
            if data.get("selected") == (code, record["quote_date"]):
                color = colors[index % len(colors)]
                ax.scatter(
                    [x], [y], s=65, color=color, edgecolors="white", linewidths=1.2, zorder=6
                )
                ax.axvline(x, color=color, alpha=0.35, linestyle="--", linewidth=0.8)
                ax.annotate(
                    f"{code}/PLN · {format_date(record['quote_date'])}\n{record['rate']} PLN",
                    (x, y),
                    xytext=(-12 if x > (ax.get_xlim()[0] + ax.get_xlim()[1]) / 2 else 12, 14),
                    textcoords="offset points",
                    ha="right" if x > (ax.get_xlim()[0] + ax.get_xlim()[1]) / 2 else "left",
                    fontsize=10,
                    zorder=7,
                    bbox=dict(
                        boxstyle="round,pad=.4", fc=display_color("#112233"), ec=color, alpha=0.95
                    ),
                    color=display_color(TEXT),
                )
    ax.set_title(tr("Kursy walut w czasie"), loc="left")
    ax.set_ylabel("PLN")
    ax.grid(alpha=0.15)
    if ax.lines:
        ax.legend(loc="best")
    else:
        ax.text(
            0.5,
            0.5,
            tr("Brak zapisanych notowań. Pobierz kursy dla wybranego okresu."),
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()


class CurrencyRatesTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.windows = []
        self.chart_data = None
        self.selected_point = None
        self.records = []
        self.service = CurrencyHistoryService(db, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls, box = panel()
        row = QHBoxLayout()
        box.addLayout(row)
        self.start = QDateEdit(QDate.currentDate().addMonths(-3))
        self.end = QDateEdit(QDate.currentDate())
        for caption, field in (("Od", self.start), ("Do", self.end)):
            field.setCalendarPopup(True)
            from home_finance_cockpit.ui.calendar import MonthCalendar

            field.setCalendarWidget(MonthCalendar(field))
            field.setDateRange(QDate(2002, 1, 2), QDate.currentDate())
            row.addWidget(label(tr(caption)))
            row.addWidget(field)
        row.addStretch()
        self.refresh_button = QPushButton(tr("Pobierz kursy z zakresu"))
        self.refresh_button.setIcon(icon("refresh", INK))
        self.refresh_button.setProperty("role", "primary")
        self.refresh_button.clicked.connect(self.download)
        row.addWidget(self.refresh_button)
        self.cancel = QPushButton(tr("Anuluj"))
        self.cancel.clicked.connect(self.service.cancel)
        self.cancel.hide()
        row.addWidget(self.cancel)
        layout.addWidget(controls)
        body = QSplitter()
        body.setChildrenCollapsible(False)
        body.setHandleWidth(px(10))
        layout.addWidget(body, 1)
        left, currency_layout = panel()
        currency_layout.addWidget(label(tr("Waluty"), "section"))
        self.currencies = QListWidget()
        self.currencies.setMinimumWidth(px(140))
        currency_layout.addWidget(self.currencies, 1)
        body.addWidget(left)
        right, chart_layout = panel()
        self.canvas = ExpandableCanvas(Figure(figsize=(8, 4), layout="constrained"))
        self.canvas.enlarge_requested.connect(self.enlarge)
        chart_layout.addWidget(self.canvas, 3)
        chart_layout.addWidget(label(tr("Notowania i czas pobrania"), "section"))
        self.table = table(
            [tr("Waluta"), tr("Data notowania"), tr("Kurs w PLN"), tr("Pobrano") + " (UTC)"]
        )
        chart_layout.addWidget(self.table, 2)
        body.addWidget(right)
        body.setSizes([px(200), px(1000)])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.select_table_point)
        self.canvas.mpl_connect("button_press_event", self.select_chart_point)
        self.note = label(
            tr("Kurs średni NBP za 1 jednostkę waluty. Dni bez publikacji nie są uzupełniane.")
        )
        layout.addWidget(self.note)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = label("")
        layout.addWidget(self.status)
        self.currencies.itemChanged.connect(self.refresh_chart)
        self.start.dateChanged.connect(self.refresh_chart)
        self.end.dateChanged.connect(self.refresh_chart)
        self.service.changed.connect(self.refresh_chart)
        self.service.finished.connect(self.status.setText)
        self.service.progress.connect(self.on_progress)
        self.service.busy_changed.connect(self.busy_changed)
        self.refresh()

    def selected_codes(self):
        return [
            self.currencies.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.currencies.count())
            if self.currencies.item(i).checkState() == Qt.CheckState.Checked
        ]

    def refresh(self):
        from home_finance_cockpit.ui.chart_dates import get_date_format

        for field in (self.start, self.end):
            field.setDisplayFormat(get_date_format())
        selected = set(self.selected_codes())
        initial = self.currencies.count() == 0
        with QSignalBlocker(self.currencies):
            self.currencies.clear()
            for record in self.db.rate_records():
                if record["code"] == "PLN":
                    continue
                item = QListWidgetItem(record["code"] + " · " + record["symbol"])
                item.setData(Qt.ItemDataRole.UserRole, record["code"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if record["code"] in selected or initial and record["code"] == "EUR"
                    else Qt.CheckState.Unchecked
                )
                self.currencies.addItem(item)
        self.refresh_chart()

    def refresh_chart(self, *_):
        start, end = (
            self.start.date().toString("yyyy-MM-dd"),
            self.end.date().toString("yyyy-MM-dd"),
        )
        if start > end:
            self.chart_data = {"currency": "PLN", "series": {}}
            self.records = []
            with QSignalBlocker(self.table):
                self.table.setRowCount(0)
            self.status.setText(tr("Data początkowa nie może być późniejsza niż końcowa."))
        else:
            self.chart_data = {
                "currency": "PLN",
                "series": {
                    code: preferred_history(self.db.rate_history(code, start, end))
                    for code in self.selected_codes()
                },
            }
            records = sorted(
                (r for rows in self.chart_data["series"].values() for r in rows),
                key=lambda r: (r["quote_date"], r["code"]),
                reverse=True,
            )
            self.records = records
            with QSignalBlocker(self.table):
                fill_table(
                    self.table,
                    [
                        [
                            r["code"],
                            format_date(r["quote_date"]),
                            r["rate"],
                            format_timestamp(r["fetched_at"])
                            + (" · " + tr("ręcznie") if r["source"] == "manual" else " · NBP"),
                        ]
                        for r in records
                    ],
                    resize_columns=False,
                )
            self.table.horizontalHeader().resizeSections(QHeaderView.ResizeMode.Stretch)
        self.note.setText(
            tr(
                "Zapisane kursy za 1 jednostkę waluty. Kursy ręczne są oznaczone; nie są notowaniami NBP."
            )
            if any(r["source"] == "manual" for r in self.records)
            else tr("Kurs średni NBP za 1 jednostkę waluty. Dni bez publikacji nie są uzupełniane.")
        )
        keys = {(r["code"], r["quote_date"]) for r in self.records}
        self.select_point(
            self.selected_point if self.selected_point in keys else None, scroll=False
        )

    def select_table_point(self):
        rows = self.table.selectionModel().selectedRows()
        if rows and rows[0].row() < len(self.records):
            record = self.records[rows[0].row()]
            self.select_point((record["code"], record["quote_date"]), scroll=False)

    def select_chart_point(self, event):
        if (
            event.button != 1
            or event.inaxes is None
            or getattr(event.canvas, "toolbar", None)
            and event.canvas.toolbar.mode
        ):
            return
        points = getattr(event.inaxes, "_rate_points", [])
        if not points:
            return
        nearest = min(
            points,
            key=lambda p: sum(
                (a - b) ** 2
                for a, b in zip(event.inaxes.transData.transform(p[2:]), (event.x, event.y))
            ),
        )
        distance = sum(
            (a - b) ** 2
            for a, b in zip(event.inaxes.transData.transform(nearest[2:]), (event.x, event.y))
        )
        if distance <= 14**2:
            self.select_point((nearest[0], nearest[1]["quote_date"]))

    def select_point(self, key, *, scroll=True):
        self.selected_point = key
        with QSignalBlocker(self.table):
            self.table.clearSelection()
            for index, record in enumerate(self.records):
                if (record["code"], record["quote_date"]) == key:
                    self.table.selectRow(index)
                    if scroll:
                        self.table.scrollToItem(self.table.item(index, 0))
                    break
        self.chart_data["selected"] = key
        render_rates(self.canvas.figure, None, self.chart_data)
        self.canvas.draw_idle()
        for dialog in self.windows:
            dialog.data["selected"] = key
            dialog.refresh_chart()

    def download(self):
        try:
            self.service.refresh(
                self.selected_codes(),
                self.start.date().toString("yyyy-MM-dd"),
                self.end.date().toString("yyyy-MM-dd"),
            )
        except ValueError as exc:
            show_error(self, exc)

    def busy_changed(self, busy):
        self.refresh_button.setEnabled(not busy)
        self.cancel.setVisible(busy)
        self.progress.setVisible(busy)
        self.currencies.setEnabled(not busy)
        self.start.setEnabled(not busy)
        self.end.setEnabled(not busy)
        if busy:
            self.status.setText(tr("Pobieranie historii kursów…"))
            self.progress.setRange(0, self.service.total)
            self.progress.setValue(0)

    def on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def enlarge(self, *_):
        dialog = ChartDialog(
            self, None, self.chart_data, renderer=render_rates, title=tr("Kursy walut w czasie")
        )
        dialog.canvas.mpl_connect("button_press_event", self.select_chart_point)
        self.windows.append(dialog)
        dialog.finished.connect(
            lambda *_: self.windows.remove(dialog) if dialog in self.windows else None
        )
        dialog.show()

    def close_windows(self):
        for window in self.windows[:]:
            window.close()
