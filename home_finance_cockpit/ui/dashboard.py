"""Dashboard presentation using shared, currency-specific calculations."""

import sqlite3
from copy import deepcopy

from matplotlib.figure import Figure
from PyQt6.QtCore import QDate, QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.analysis import summarize
from home_finance_cockpit.ui.chart_layout import ResizableChartGrid, add_chart_area, chart_splitter
from home_finance_cockpit.ui.charts import ChartDialog, ExpandableCanvas, render_chart
from home_finance_cockpit.ui.common import table
from home_finance_cockpit.ui.components import MetricCard, icon, label, panel
from home_finance_cockpit.ui.filters import filter_toolbar
from home_finance_cockpit.ui.periods import PERIOD_PRESETS, period_range
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import BLUE, RED, SUCCESS, TEXT


class Dashboard(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.excluded_chart_wallet_ids = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter, layout = chart_splitter(self, layout)
        self.filter_fields = QWidget(self)
        filters = QGridLayout(self.filter_fields)
        self.wallet, self.currency, self.preset = QComboBox(), QComboBox(), QComboBox()
        for caption, value in PERIOD_PRESETS:
            self.preset.addItem(tr(caption), value)
        self.start, self.end = (
            QDateEdit(QDate.currentDate().addMonths(-1)),
            QDateEdit(QDate.currentDate()),
        )
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            from home_finance_cockpit.ui.calendar import MonthCalendar

            widget.setCalendarWidget(MonthCalendar(widget))
            widget.setDisplayFormat("yyyy-MM-dd")
        self.percentage = QPushButton(tr("Procenty"))
        self.percentage.setCheckable(True)
        self.percentage.setChecked(True)
        self.percentage.setToolTip(
            tr(
                "Przełącz udziały procentowe i kwoty na wykresach struktury. Przy saldach ujemnych pokazujemy kwoty."
            )
        )
        self.date_labels = []
        for index, (caption, widget) in enumerate(
            (
                ("Waluta:", self.currency),
                ("Portfel:", self.wallet),
                ("Okres:", self.preset),
                ("Od:", self.start),
                ("Do:", self.end),
            )
        ):
            row, column = divmod(index, 3)
            caption_widget = QLabel(tr(caption))
            if index >= 3:
                self.date_labels.append(caption_widget)
            filters.addWidget(caption_widget, row, column * 2)
            filters.addWidget(widget, row, column * 2 + 1)
        for column in (1, 3, 5):
            filters.setColumnStretch(column, 1)
        self.filter_fields.hide()
        toolbar, self.filter_button, self.filter_summary = filter_toolbar(self)
        layout.addLayout(toolbar)
        cards = QGridLayout()
        self.card_layout = cards
        self.cards = []
        for index, color in enumerate((TEXT, SUCCESS, RED, BLUE)):
            card = MetricCard(color, ("wallet", "income", "expense", "transactions")[index])
            self.cards.append(card)
            cards.addWidget(card, 0, index)
            cards.setColumnStretch(index, 1)
        layout.addLayout(cards)
        self.notice = QLabel()
        self.notice.setProperty("role", "muted")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.notice.hide()
        chart_body = ResizableChartGrid()
        self.body_grid = chart_body
        chart_frames = []
        self.canvases = []
        self.chart_windows = []
        self.chart_data = None
        self.chart_indices = (0, 2)
        for row, col in ((0, 1), (0, 0)):
            index = len(self.canvases)
            canvas = ExpandableCanvas(Figure(figsize=(5, 3), layout="constrained"))
            canvas.setMinimumHeight(px(140))
            canvas.setMinimumWidth(0)
            canvas.setToolTip(tr("Dwuklik otwiera powiększony wykres"))
            canvas.enlarge_requested.connect(lambda i=index: self.open_chart(i))
            self.canvases.append(canvas)
            frame, frame_layout = panel()
            frame_layout.setContentsMargins(px(8), px(8), px(8), px(8))
            if index == 0:
                heading = QHBoxLayout()
                heading.addWidget(self.percentage)
                self.composition_title = label("", "section")
                self.composition_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
                heading.addWidget(self.composition_title, 1)
                heading.addSpacing(self.percentage.sizeHint().width())
                frame_layout.addLayout(heading)
            frame_layout.addWidget(canvas)
            chart_frames.append(frame)
        balances, balances_layout = panel(tr("Portfele i salda"))
        self.summary_mode = QComboBox()
        self.summary_mode.addItem(tr("Salda według portfela"), "wallet")
        self.summary_mode.addItem(tr("Salda według waluty"), "currency")
        balances_layout.addWidget(self.summary_mode)
        self.summary_table = table([tr("Portfel"), tr("Saldo"), tr("Waluta")])
        self.summary_table.setMinimumHeight(px(85))
        self.summary_table.itemChanged.connect(self.chart_wallet_changed)
        balances_layout.addWidget(self.summary_table)
        self.valuation = label("")
        balances_layout.addWidget(self.valuation)
        goals, goals_layout = panel(tr("Cele oszczędnościowe"))
        from home_finance_cockpit.ui.savings_goals import GoalSummary

        self.goals_summary = GoalSummary(db)
        goals_layout.addWidget(self.goals_summary)
        self.body_widgets = [chart_frames[1], chart_frames[0], balances, goals]
        self.body_grid.arrange(self.body_widgets, 2, weights=[2, 1])
        scroll = QScrollArea()
        self.body_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(chart_body)
        add_chart_area(self.splitter, scroll, 130)
        self.currency.currentIndexChanged.connect(self.currency_changed)
        for signal in (
            self.wallet.currentIndexChanged,
            self.preset.currentIndexChanged,
            self.start.dateChanged,
            self.end.dateChanged,
            self.percentage.clicked,
        ):
            signal.connect(self.refresh)
        self.refresh_filters()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 2 if self.width() < px(980) else 4
        for index, card in enumerate(self.cards):
            self.card_layout.addWidget(card, index // columns, index % columns)
        for index in range(4):
            self.card_layout.setColumnStretch(index, 1 if index < columns else 0)
        if hasattr(self, "body_widgets"):
            body_columns = 1 if self.width() < px(980) else 2
            self.body_grid.arrange(
                self.body_widgets, body_columns, weights=[2, 1] if body_columns == 2 else [1]
            )

    def refresh_filters(self):
        current = self.currency.currentData()
        with QSignalBlocker(self.currency):
            self.currency.clear()
            for code in sorted({"PLN"} | {w["currency"] for w in self.db.wallets()}) or ["PLN"]:
                self.currency.addItem(code, code)
            preferred = self.currency.findData(current if current is not None else "PLN")
            self.currency.setCurrentIndex(max(preferred, 0))
        self.currency_changed()

    def currency_changed(self):
        current = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(
                tr("Wszystkie portfele")
                if self.currency.currentData() == "PLN"
                else tr("Wszystkie w tej walucie"),
                None,
            )
            for wallet in self.db.wallets():
                if (
                    self.currency.currentData() == "PLN"
                    or wallet["currency"] == self.currency.currentData()
                ):
                    self.wallet.addItem(icon(wallet["icon_name"]), wallet["name"], wallet["id"])
            self.wallet.setCurrentIndex(max(self.wallet.findData(current), 0))
        self.refresh()

    def period(self):
        preset = self.preset.currentData()
        self.start.setEnabled(preset == "custom")
        self.end.setEnabled(preset == "custom")
        for widget in (self.start, self.end, *self.date_labels):
            widget.setVisible(preset == "custom")
        return period_range(preset, self.start.date(), self.end.date())

    def refresh(self, *_):
        scope = self.preset.currentText()
        if self.preset.currentData() == "custom":
            scope = f"{self.start.date().toString('yyyy-MM-dd')} — {self.end.date().toString('yyyy-MM-dd')}"
        self.filter_summary.setText(
            tr(
                "{v0} · {v1} · {v2}",
                v0=self.currency.currentText(),
                v1=self.wallet.currentText(),
                v2=tr(scope),
            )
        )
        from home_finance_cockpit.ui.filters import category_summary

        self.filter_summary.setText((self.filter_summary.text() + category_summary(self)))
        try:
            start, end = self.period()
            data = summarize(
                self.db,
                self.wallet.currentData(),
                start,
                end,
                self.currency.currentData(),
                category_ids=getattr(self, "selected_category_ids", set()),
            )
        except (ValueError, sqlite3.Error) as exc:
            self.chart_data = None
            self.notice.setText(str(exc))
            self.notice.show()
            for card in self.cards:
                card.setText("—")
            for canvas in self.canvases:
                canvas.figure.clear()
                canvas.draw_idle()
            return
        code = data["currency"]
        self.composition_title.setText(tr("{v0} ({v1})", v0=tr("Struktura portfeli"), v1=code))
        chart_data = data
        if self.excluded_chart_wallet_ids:
            chart_data = summarize(
                self.db,
                self.wallet.currentData(),
                start,
                end,
                self.currency.currentData(),
                category_ids=getattr(self, "selected_category_ids", set()),
                wallet_ids={wallet["id"] for wallet in self.db.wallets()}
                - self.excluded_chart_wallet_ids,
            )
        self.chart_data = deepcopy(chart_data)
        self.chart_context = f"{self.wallet.currentText()} • {self.preset.currentText()}"
        if start or end:
            self.chart_context += f" • {start or '…'} — {end or '…'}"
        balance_title = "Saldo (wszystkie daty)" if end is None else "Saldo na koniec zakresu"
        for card, title, key in zip(
            self.cards,
            (balance_title, "Wpływy", "Wydatki", "Przepływ netto"),
            ("balance", "income", "expense", "net"),
        ):
            card.setText(tr("{v0}\n{v1}", v0=tr(title), v1=amount_label(data[key], code)))
        self.notice.clear()
        self.notice.hide()
        self.notice.setToolTip(
            tr(
                "Przegląd obejmuje wszystkie transakcje. Własne przelewy i wymiany są przepływami konta; nie są automatycznie uzgadniane. Saldo nie jest potwierdzane online przez bank."
            )
        )
        self.percentage.setText((tr("Procenty") if self.percentage.isChecked() else tr("Kwoty")))
        for index, canvas in enumerate(self.canvases):
            render_chart(
                canvas.figure, self.chart_indices[index], chart_data, self.percentage.isChecked()
            )
            if index == 0:
                for ax in canvas.figure.axes:
                    ax.set_title("")
            canvas.draw_idle()

    def chart_wallet_changed(self, item):
        if item.column() != 3:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if identifier is None:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.excluded_chart_wallet_ids.discard(identifier)
        else:
            self.excluded_chart_wallet_ids.add(identifier)
        self.refresh()

    def open_chart(self, index):
        if self.chart_data is None:
            return
        dialog = ChartDialog(
            self,
            self.chart_indices[index],
            self.chart_data,
            self.percentage.isChecked(),
            self.chart_context,
        )
        self.chart_windows.append(dialog)
        dialog.finished.connect(lambda result, window=dialog: self._forget_chart(window))
        dialog.show()

    def _forget_chart(self, dialog):
        if dialog in self.chart_windows:
            self.chart_windows.remove(dialog)

    def close_chart_windows(self):
        for dialog in list(self.chart_windows):
            dialog.close()
