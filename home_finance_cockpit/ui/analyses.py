"""Shared analytics filters and routing to six dedicated views."""

import sqlite3

from PyQt6.QtCore import QDate, QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLineEdit,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.ui.chart_layout import add_chart_area, chart_splitter
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.filters import filter_toolbar


class AnalysesTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.data, self.dirty = db, None, True
        self.chart_windows = []
        self.drawing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter, controls = chart_splitter(self, layout)
        self.filter_fields = QWidget(self)
        self.amount_min, self.amount_max = (
            QLineEdit(self.filter_fields),
            QLineEdit(self.filter_fields),
        )
        self.currency, self.wallet, self.year, self.month = (
            QComboBox(self.filter_fields) for _ in range(4)
        )
        from home_finance_cockpit.ui.periods import PERIOD_PRESETS

        self.preset = QComboBox(self.filter_fields)
        for caption, value in PERIOD_PRESETS:
            self.preset.addItem(tr(caption), value)
        self.start = QDateEdit(QDate.currentDate().addMonths(-1), self.filter_fields)
        self.end = QDateEdit(QDate.currentDate(), self.filter_fields)
        self.exclude = QCheckBox(
            tr("Pomiń rozpoznane wymiany i niezakończone operacje"), self.filter_fields
        )
        self.exclude.setChecked(True)
        self.filter_fields.hide()
        toolbar, self.filter_button, self.filter_summary = filter_toolbar(self)
        from home_finance_cockpit.ui.analysis_filter_tiles import AnalysisFilterTiles

        self.quick_filters = AnalysisFilterTiles(self)
        toolbar.removeWidget(self.filter_summary)
        self.filter_summary.hide()
        toolbar.content.insertWidget(1, self.quick_filters, 1)
        controls.addLayout(toolbar)
        self.filter_summary.setMinimumWidth(0)
        self.filter_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status = label("")
        controls.addWidget(self.status)
        self.status.hide()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabBar()
        self.tabs.setObjectName("analysisTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        from home_finance_cockpit.ui.theme import display_color

        self.tabs.setStyleSheet(
            "QTabBar#analysisTabs {border-bottom:1px solid "
            + display_color("#24394D")
            + ";} QTabBar#analysisTabs::tab {background:transparent;border:0;border-bottom:3px solid transparent;padding:12px 20px;margin-right:4px;color:"
            + display_color("#A8BED5")
            + ";} QTabBar#analysisTabs::tab:selected {color:"
            + display_color("#22D3EE")
            + ";border-bottom:3px solid "
            + display_color("#22D3EE")
            + ";font-weight:600;} QTabBar#analysisTabs::tab:hover {color:"
            + display_color("#EDF4FF")
            + ";background:"
            + display_color("#112233")
            + ";}"
        )
        for title in ("Podsumowanie", "Kategorie", "W czasie", "Porównania", "Odbiorcy"):
            self.tabs.addTab(tr(title))
        self.tabs.addTab(tr("Kursy walut"))
        self.tabs.currentChanged.connect(self.group_changed)
        body_layout.addWidget(self.tabs)
        from home_finance_cockpit.ui.analysis_summary import AnalysisSummary

        self.summary_view = AnalysisSummary(self)
        body_layout.addWidget(self.summary_view, 1)
        self.summary_view.hide()
        from home_finance_cockpit.ui.category_explorer import CategoryExplorer

        self.category_explorer = CategoryExplorer(self)
        from home_finance_cockpit.ui.category_overview import CategoryViews

        self.category_views = CategoryViews(self, self.category_explorer)
        body_layout.addWidget(self.category_views, 1)
        self.category_views.hide()
        from home_finance_cockpit.ui.time_overview import TimeOverview

        self.time_overview = TimeOverview(self)
        body_layout.addWidget(self.time_overview, 1)
        self.time_overview.hide()
        from home_finance_cockpit.ui.period_comparison import PeriodComparison

        self.period_comparison = PeriodComparison(self)
        body_layout.addWidget(self.period_comparison, 1)
        self.period_comparison.hide()
        from home_finance_cockpit.ui.counterparties import Counterparties

        self.counterparties = Counterparties(self)
        body_layout.addWidget(self.counterparties, 1)
        self.counterparties.hide()
        from home_finance_cockpit.ui.currency_rates import CurrencyRatesTab

        self.currency_rates = CurrencyRatesTab(self.db, self)
        body_layout.addWidget(self.currency_rates, 1)
        self.currency_rates.hide()
        self.views = (
            self.summary_view,
            self.category_views,
            self.time_overview,
            self.period_comparison,
            self.counterparties,
            self.currency_rates,
        )
        add_chart_area(self.splitter, body, 55)
        self.currency.currentIndexChanged.connect(self.refresh_wallets)
        self.wallet.currentIndexChanged.connect(self.refresh_years)
        self.year.currentIndexChanged.connect(self.refresh_months)
        self.month.currentIndexChanged.connect(self.refresh)
        self.exclude.toggled.connect(self.refresh)
        self.amount_min.textChanged.connect(self.refresh)
        self.amount_max.textChanged.connect(self.refresh)
        self.group_changed()
        self.refresh_filters()

    def group_changed(self, *_):
        rates = self.tabs.currentIndex() == 5
        self.splitter.widget(0).setVisible(True)
        self.splitter.widget(0).setEnabled(not rates)
        self.layout_charts()

    def layout_charts(self, *_):
        if not hasattr(self, "views"):
            return
        for index, view in enumerate(self.views):
            view.setVisible(index == self.tabs.currentIndex())
        self.render_current()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout_charts()

    def refresh(self, *_, force=False):
        if self.tabs.currentIndex() == 5:
            self.currency_rates.refresh()
            return
        from home_finance_cockpit.ui.filters import category_summary
        from home_finance_cockpit.ui.periods import period_range

        self.filter_summary.setText(
            tr(
                "{v0} · {v1} · {v2} · {v3}",
                v0=self.currency.currentText(),
                v1=self.wallet.currentText(),
                v2=self.year.currentText(),
                v3=self.month.currentText(),
            )
        )
        if self.preset.currentData() != "all":
            from home_finance_cockpit.ui.chart_dates import format_date

            first, last = (
                (self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"))
                if self.preset.currentData() == "custom"
                else period_range(self.preset.currentData(), self.start.date(), self.end.date())
            )
            self.filter_summary.setText(
                " · ".join(
                    (
                        self.currency.currentText(),
                        self.wallet.currentText(),
                        format_date(first) + " – " + format_date(last),
                    )
                )
            )
        self.filter_summary.setText((self.filter_summary.text() + category_summary(self)))
        self.quick_filters.sync()
        self.dirty = True
        if not force and not self.isVisible():
            return
        try:
            from home_finance_cockpit.services.amount_range import amount_range

            low, high = amount_range(self.amount_min.text(), self.amount_max.text())
            start, end = period_range(self.preset.currentData(), self.start.date(), self.end.date())
            self.data = spending_snapshot(
                self.db,
                self.currency.currentData() or "PLN",
                self.wallet.currentData(),
                self.year.currentData(),
                self.month.currentData(),
                after_refunds=False,
                omit_salary=True,
                exclude=self.exclude.isChecked(),
                category_ids=getattr(self, "selected_category_ids", set()),
                start=start,
                end=end,
                amount_min=low,
                amount_max=high,
            )
        except (ValueError, sqlite3.Error) as exc:
            self.data = None
            self.status.setText(str(exc))
            self.status.show()
        if self.data is not None:
            self.status.clear()
            self.status.hide()
        self.dirty = False
        self.render_current(force=force)

    def render_current(self, *_, force=False):
        if not hasattr(self, "views") or self.drawing or (not force and not self.isVisible()):
            return
        self.drawing = True
        try:
            view = self.views[self.tabs.currentIndex()]
            if view is self.currency_rates:
                view.refresh()
            else:
                view.refresh(self.data)
        finally:
            self.drawing = False

    def showEvent(self, event):
        super().showEvent(event)
        if self.dirty:
            self.refresh(force=True)
        else:
            self.render_current()

    def close_chart_windows(self):
        self.currency_rates.close_windows()
        for dialog in self.chart_windows[:]:
            dialog.close()

    def open_pdf(self):
        host = self.window()
        if hasattr(host, "show_report_generator"):
            host.show_report_generator()
            panel = host.report_generator.panel
            panel.currency.setCurrentIndex(
                max(0, panel.currency.findData(self.currency.currentData()))
            )
            panel.wallet.setCurrentIndex(max(0, panel.wallet.findData(self.wallet.currentData())))
            panel.year.setCurrentIndex(max(0, panel.year.findData(self.year.currentData())))
            panel.after_refunds.setChecked(False)
            panel.omit_salary.setChecked(True)
            panel.exclude.setChecked(self.exclude.isChecked())
            for i in range(panel.months.count()):
                item = panel.months.item(i)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if self.month.currentData() is None or item.text() == self.month.currentData()
                    else Qt.CheckState.Unchecked
                )

    def pick_category(self, event):
        if self.data is None:
            return
        target = getattr(event.artist.axes, "_analysis_targets", {}).get(event.artist)
        if target is None:
            return
        kind, value = target
        if kind == "category":
            self.category_explorer.selection = (value, None)
            self.tabs.setCurrentIndex(1)
            self.category_explorer.refresh(self.data)
        elif kind == "merchant":
            self.open_rows(
                [c["row"]["id"] for c in self.data["contributions"] if c["merchant"] == value]
            )

    def open_rows(self, ids):
        host = self.window()
        if (
            not hasattr(host, "transaction_page")
            or not host.transaction_page.inspector.guard_pending()
        ):
            return
        filters = host.transaction_filters
        with (
            QSignalBlocker(filters.currency),
            QSignalBlocker(filters.wallet),
            QSignalBlocker(filters.preset),
            QSignalBlocker(host.transaction_search),
        ):
            filters.currency.setCurrentIndex(filters.currency.findData(self.currency.currentData()))
            filters.populate_wallets()
            filters.wallet.setCurrentIndex(filters.wallet.findData(self.wallet.currentData()))
            filters.preset.setCurrentIndex(filters.preset.findData("all"))
            host.transaction_search.clear()
        host.transaction_page.analysis_ids = set(ids)
        host.transaction_page.mode = "all"
        host.transaction_page.view_buttons["all"].setChecked(True)
        host.refresh_transactions()
        host.tabs.setCurrentIndex(1)

    def eligible_months(self):
        return sorted(
            {
                r["date"][:7]
                for r in self.db.transactions(self.wallet.currentData())
                if (
                    self.currency.currentData() == "PLN"
                    or r["currency"] == self.currency.currentData()
                )
                and r["include_in_reports"]
            }
        )

    def refresh_filters(self):
        current = self.currency.currentData()
        with QSignalBlocker(self.currency):
            self.currency.clear()
            for code in sorted({"PLN"} | {w["currency"] for w in self.db.wallets()}):
                self.currency.addItem(code, code)
            self.currency.setCurrentIndex(
                max(0, self.currency.findData(current if current is not None else "PLN"))
            )
        self.refresh_wallets()

    def refresh_wallets(self):
        current = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(
                tr("Wszystkie portfele")
                if self.currency.currentData() == "PLN"
                else tr("Wszystkie w wybranej walucie"),
                None,
            )
            for w in self.db.wallets():
                if (
                    self.currency.currentData() == "PLN"
                    or w["currency"] == self.currency.currentData()
                ):
                    self.wallet.addItem(icon(w["icon_name"]), w["name"], w["id"])
            self.wallet.setCurrentIndex(max(0, self.wallet.findData(current)))
        self.refresh_years()

    def refresh_years(self):
        current = self.year.currentData()
        with QSignalBlocker(self.year):
            self.year.clear()
            self.year.addItem(tr("Wszystkie lata"), None)
            for year in sorted({m[:4] for m in self.eligible_months()}):
                self.year.addItem(year, int(year))
            self.year.setCurrentIndex(max(0, self.year.findData(current)))
        self.refresh_months()

    def refresh_months(self):
        current = self.month.currentData()
        with QSignalBlocker(self.month):
            self.month.clear()
            self.month.addItem(tr("Cały wybrany okres"), None)
            for month in self.eligible_months():
                if self.year.currentData() is None or month.startswith(
                    str(self.year.currentData()) + "-"
                ):
                    self.month.addItem(month, month)
            self.month.setCurrentIndex(max(0, self.month.findData(current)))
        self.refresh()
