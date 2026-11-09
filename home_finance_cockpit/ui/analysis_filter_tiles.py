"""Quick analytical scope selectors backed by the same state as FiltersDialog."""

from PyQt6.QtCore import QDate, QLocale, QSignalBlocker, QSize
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from home_finance_cockpit.localization import language, tr
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.periods import period_range

TIME_MODES = (
    ("Cały okres", "all"),
    ("Dzień", "day"),
    ("Tydzień", "week"),
    ("Miesiąc", "month"),
    ("Rok", "year"),
)


class AnalysisFilterTiles(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.period_mode = "all"
        self.period_anchor = QDate.currentDate()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.buttons = {}
        for key in ("wallet", "currency", "categories", "amount"):
            button = QToolButton()
            button.setMinimumHeight(32)
            self.buttons[key] = button
            layout.addWidget(button)
            if key in ("categories", "amount"):
                button.clicked.connect(owner.filter_button.click)
            else:
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(button)
                menu.aboutToShow.connect(lambda key=key: self.populate(key))
                button.setMenu(menu)
        self.period_controls = QWidget()
        period_layout = QHBoxLayout(self.period_controls)
        period_layout.setContentsMargins(0, 0, 0, 0)
        period_layout.setSpacing(6)
        self.previous = QToolButton()
        self.next = QToolButton()
        for button, glyph, caption in (
            (self.previous, "back", "Poprzedni okres"),
            (self.next, "forward", "Następny okres"),
        ):
            button.setIcon(icon(glyph))
            button.setProperty("themeIcon", glyph)
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(18, 18))
            button.setStyleSheet("QToolButton {padding:0;min-width:0;min-height:0;}")
            button.setToolTip(tr(caption))
            button.setAccessibleName(tr(caption))
        self.period_caption = label("")
        self.period_caption.setWordWrap(False)
        period_layout.addWidget(self.previous)
        period_layout.addWidget(self.period_caption)
        period_layout.addWidget(self.next)
        mode = QToolButton()
        mode.setMinimumHeight(32)
        mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(mode)
        menu.aboutToShow.connect(lambda: self.populate("period"))
        mode.setMenu(menu)
        self.buttons["period"] = mode
        period_layout.insertWidget(0, mode)
        layout.addWidget(self.period_controls)
        for key in ("categories", "amount"):
            layout.removeWidget(self.buttons[key])
            layout.addWidget(self.buttons[key])
        layout.addStretch(1)
        self.previous.clicked.connect(lambda: self.step_period(-1))
        self.next.clicked.connect(lambda: self.step_period(1))

    def populate(self, key):
        menu = self.buttons[key].menu()
        menu.clear()
        if key == "period":
            current = self.period_mode
            for caption, value in TIME_MODES:
                action = menu.addAction(tr(caption))
                action.setCheckable(True)
                action.setChecked(current == value)
                action.triggered.connect(lambda checked=False, value=value: self.choose_mode(value))
        else:
            source = getattr(self.owner, key)
            for index in range(source.count()):
                action = menu.addAction(source.itemIcon(index), source.itemText(index))
                action.setCheckable(True)
                action.setChecked(source.currentIndex() == index)
                action.triggered.connect(
                    lambda checked=False, source=source, value=source.itemData(index): (
                        source.setCurrentIndex(source.findData(value))
                    )
                )

    def choose_period(self, value):
        if value == "custom":
            from PyQt6.QtWidgets import QDialog

            from home_finance_cockpit.ui.filters import FiltersDialog

            dialog = FiltersDialog(self.owner)
            dialog.choose_period("custom")
            if dialog.exec() == QDialog.DialogCode.Accepted:
                dialog.apply()
            dialog.deleteLater()
            return
        with (
            QSignalBlocker(self.owner.preset),
            QSignalBlocker(self.owner.year),
            QSignalBlocker(self.owner.month),
        ):
            self.owner.preset.setCurrentIndex(self.owner.preset.findData(value))
            self.owner.year.setCurrentIndex(0)
            self.owner.month.setCurrentIndex(0)
        self.owner.refresh()

    def choose_mode(self, mode):
        self.period_mode = mode
        self.apply_period()

    def step_period(self, direction):
        if self.period_mode == "day":
            self.period_anchor = self.period_anchor.addDays(direction)
        elif self.period_mode == "week":
            self.period_anchor = self.period_anchor.addDays(direction * 7)
        elif self.period_mode == "month":
            self.period_anchor = self.period_anchor.addMonths(direction)
        elif self.period_mode == "year":
            self.period_anchor = self.period_anchor.addYears(direction)
        else:
            return
        self.apply_period()

    def apply_period(self):
        owner, mode, anchor = self.owner, self.period_mode, self.period_anchor
        first = last = anchor
        if mode == "week":
            first = anchor.addDays(1 - anchor.dayOfWeek())
            last = first.addDays(6)
        elif mode == "month":
            first = QDate(anchor.year(), anchor.month(), 1)
            last = first.addMonths(1).addDays(-1)
        elif mode == "year":
            first, last = QDate(anchor.year(), 1, 1), QDate(anchor.year(), 12, 31)
        with (
            QSignalBlocker(owner.preset),
            QSignalBlocker(owner.start),
            QSignalBlocker(owner.end),
            QSignalBlocker(owner.year),
            QSignalBlocker(owner.month),
        ):
            owner.preset.setCurrentIndex(
                owner.preset.findData("all" if mode == "all" else "custom")
            )
            if mode != "all":
                owner.start.setDate(first)
                owner.end.setDate(last)
            owner.year.setCurrentIndex(0)
            owner.month.setCurrentIndex(0)
        owner.refresh()

    def sync_period(self):
        owner = self.owner
        preset = owner.preset.currentData()
        first, last = period_range(preset, owner.start.date(), owner.end.date())
        if preset == "all" and owner.month.currentData():
            first = owner.month.currentData() + "-01"
            date = QDate.fromString(first, "yyyy-MM-dd")
            last = date.addMonths(1).addDays(-1).toString("yyyy-MM-dd")
        elif preset == "all" and owner.year.currentData():
            first, last = f"{owner.year.currentData()}-01-01", f"{owner.year.currentData()}-12-31"
        if not first:
            self.period_mode = "all"
            self.period_anchor = QDate.currentDate()
        else:
            start, end = QDate.fromString(first, "yyyy-MM-dd"), QDate.fromString(last, "yyyy-MM-dd")
            if not start <= self.period_anchor <= end:
                self.period_anchor = start
            if preset in ("this_year", "last_year") or (
                start.month() == 1 and start.day() == 1 and end == QDate(start.year(), 12, 31)
            ):
                self.period_mode = "year"
            elif preset in ("this_month", "last_month") or (
                start.day() == 1 and end == start.addMonths(1).addDays(-1)
            ):
                self.period_mode = "month"
            elif preset in ("this_week", "last_week") or (
                start.dayOfWeek() == 1 and end == start.addDays(6)
            ):
                self.period_mode = "week"
            elif start == end:
                self.period_mode = "day"
            else:
                self.period_mode = "day"
        caption = tr("Cały okres")
        if self.period_mode == "day":
            caption = (
                format_date(first)
                if first == last
                else f"{format_date(first)} – {format_date(last)}"
            )
        elif self.period_mode == "week":
            caption = tr(
                "Tydzień {week}: {first} – {last}",
                week=self.period_anchor.weekNumber()[0],
                first=format_date(first),
                last=format_date(last),
            )
        elif self.period_mode == "month":
            locale = QLocale("pl_PL" if language() == "pl" else "en_GB")
            caption = f"{locale.standaloneMonthName(self.period_anchor.month())} {self.period_anchor.year()}"
        elif self.period_mode == "year":
            caption = str(self.period_anchor.year())
        self.period_caption.setText(caption)
        self.period_caption.setToolTip(caption)
        for widget in (self.previous, self.next, self.period_caption):
            widget.setVisible(True)
        self.previous.setEnabled(self.period_mode != "all")
        self.next.setEnabled(self.period_mode != "all")
        self.buttons["period"].setText(
            tr(dict((value, caption) for caption, value in TIME_MODES)[self.period_mode])
        )

    def sync(self):
        owner = self.owner
        try:
            self.sync_period()
        except ValueError:
            self.period_caption.setText(tr("Nieprawidłowy zakres dat"))
        captions = {
            "wallet": owner.wallet.currentText(),
            "currency": owner.currency.currentText(),
            "categories": tr(
                "Kategorie: {count}", count=len(getattr(owner, "selected_category_ids", set()))
            ),
            "amount": tr(
                "Kwota: {first} – {last}",
                first=owner.amount_min.text() or "…",
                last=owner.amount_max.text() or "…",
            ),
        }
        for key, caption in captions.items():
            self.buttons[key].setText(caption)
            self.buttons[key].setToolTip(caption)
        self.buttons["categories"].setVisible(bool(getattr(owner, "selected_category_ids", set())))
        self.buttons["amount"].setVisible(bool(owner.amount_min.text() or owner.amount_max.text()))
