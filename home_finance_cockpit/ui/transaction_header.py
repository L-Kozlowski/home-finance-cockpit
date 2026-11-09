"""Column-aligned editors embedded below the sortable transaction headings."""

from PyQt6 import sip
from PyQt6.QtCore import QDate, QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from home_finance_cockpit.domain.validation import money_minor
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.calendar import MonthCalendar
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import ACCENT, RED, display_color


class CategoryMenu(QMenu):
    def __init__(self, button, rows, selected, placeholder, changed, clear_selection):
        super().__init__(button)
        self.button = button
        self.rows = rows
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(6, 6, 6, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        clear = QPushButton(tr("Wszystkie"))
        clear.clicked.connect(clear_selection)
        layout.addWidget(clear)
        self.choices = QListWidget()
        self.choices.setWordWrap(True)
        self.choices.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.choices.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for key, caption in rows:
            item = QListWidgetItem(caption)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked
            )
            self.choices.addItem(item)
        self.choices.itemChanged.connect(
            lambda item: changed(
                item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked
            )
        )
        self.search.textChanged.connect(self.filter_choices)
        layout.addWidget(self.choices)
        entry = QWidgetAction(self)
        entry.setDefaultWidget(self.content)
        self.addAction(entry)

    def filter_choices(self, query):
        for i in range(self.choices.count()):
            item = self.choices.item(i)
            item.setHidden(query.casefold() not in item.text().casefold())

    def showEvent(self, event):
        super().showEvent(event)
        screen = self.button.screen().availableGeometry()
        anchor = self.button.mapToGlobal(QPoint(0, self.button.height()))
        longest = max(
            (self.fontMetrics().horizontalAdvance(caption) for _, caption in self.rows), default=200
        )
        width = min(max(self.button.width(), longest + 64, px(260)), px(600), screen.width() - 16)
        desired = px(116) + min(self.choices.count(), 9) * px(28)
        height = max(px(110), min(px(360), desired, screen.bottom() - anchor.y() - 12))
        self.content.setFixedSize(width, height)
        self.setFixedSize(width + px(12), height + px(12))
        self.move(
            max(screen.left() + 6, min(anchor.x(), screen.right() - self.width() - 6)), anchor.y()
        )
        self.search.setFocus()


class CalendarFilter(QDateEdit):
    """A date selector: the whole field opens the calendar."""

    def __init__(self):
        super().__init__()
        self.lineEdit().setReadOnly(True)
        self.lineEdit().installEventFilter(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popup = QMenu(self)
        self.calendar = MonthCalendar(self.popup)
        action = QWidgetAction(self.popup)
        action.setDefaultWidget(self.calendar)
        self.popup.addAction(action)
        self.calendar.clicked.connect(self.choose_date)

    def choose_date(self, date):
        self.setDate(date)
        self.popup.close()

    def open_calendar(self):
        self.calendar.setDateRange(self.minimumDate(), self.maximumDate())
        self.calendar.setSelectedDate(
            self.date() if self.date() != self.minimumDate() else QDate.currentDate()
        )
        self.popup.popup(self.mapToGlobal(self.rect().bottomLeft()))
        self.calendar.setFocus()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_calendar()
            event.accept()
        else:
            super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.open_calendar()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.setDate(self.minimumDate())
        elif event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Down,
        ):
            self.open_calendar()
        else:
            event.ignore()


class TransactionHeader(QHeaderView):
    def __init__(self, page):
        super().__init__(Qt.Orientation.Horizontal, page.table)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)
        self.page = page
        self.filters_collapsed = False
        self.editors = {}
        self.text_fields = {}
        self.ranges = {}
        self.active = set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(page.refresh)
        self.dates = []
        for column in range(13):
            box = QWidget(self.viewport())
            layout = QVBoxLayout(box)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.editors[column] = box
            if column in (5, 12):
                fields = []
                for index, caption in enumerate(("Od", "Do")):
                    edit = (
                        (page.filters.amount_min, page.filters.amount_max)[index]
                        if column == 5
                        else QLineEdit()
                    )
                    edit.setPlaceholderText(tr(caption))
                    edit.setClearButtonEnabled(True)
                    edit.textChanged.connect(lambda: self.timer.start())
                    layout.addWidget(edit)
                    fields.append(edit)
                self.ranges[column] = fields
            elif column == 0:
                for caption in ("Od", "Do"):
                    edit = CalendarFilter()
                    edit.setCalendarPopup(True)
                    edit.setDisplayFormat("dd.MM.yyyy")
                    edit.setMinimumDate(QDate(1752, 9, 14))
                    edit.setSpecialValueText(tr(caption))
                    edit.setDate(edit.minimumDate())
                    edit.dateChanged.connect(self.date_changed)
                    layout.addWidget(edit)
                    self.dates.append(edit)
            elif column == 6:
                self.currency = QComboBox()
                self.currency.setMinimumWidth(0)
                layout.addWidget(self.currency)
                self.currency.currentIndexChanged.connect(self.currency_changed)
            elif column == 10:
                self.reports = QComboBox(box)
                self.reports.hide()
                self.reports_button = QToolButton()
                self.reports_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(self.reports_button)
                self.reports_button.setMenu(menu)
                for index, (caption, value) in enumerate(
                    (("Wszystkie", None), ("Tak", True), ("Nie", False))
                ):
                    self.reports.addItem(tr(caption), value)
                    action = menu.addAction(tr(caption))
                    action.setCheckable(True)
                    action.triggered.connect(
                        lambda checked, i=index: self.reports.setCurrentIndex(i)
                    )
                self.reports.currentIndexChanged.connect(self.sync_reports_button)
                self.reports.currentIndexChanged.connect(page.refresh)
                self.sync_reports_button()
                layout.addWidget(self.reports_button)
            elif column in (1, 3):
                button = QToolButton()
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                layout.addWidget(button)
                if column == 1:
                    self.wallet = button
                else:
                    self.categories = button
            else:
                edit = QLineEdit()
                edit.setPlaceholderText(tr("Zawiera…"))
                edit.setClearButtonEnabled(True)
                edit.textChanged.connect(lambda: self.timer.start())
                layout.addWidget(edit)
                self.text_fields[column] = edit
            for i in range(layout.count()):
                control = layout.itemAt(i).widget()
                control.setObjectName("transactionColumnFilter")
                control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                layout.setStretch(i, 1)
        self.collapse_button = QToolButton(self.viewport())
        self.collapse_button.setIcon(icon("minus"))
        self.collapse_button.setToolTip(tr("Zwiń filtry"))
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.setStyleSheet(
            "QToolButton {padding:0;min-height:0;border:0;background:transparent;}"
        )
        self.collapse_button.clicked.connect(self.toggle_filters)
        self.sectionResized.connect(self.position_editors)
        self.sectionMoved.connect(self.position_editors)
        self.geometriesChanged.connect(self.position_editors)
        page.table.horizontalScrollBar().valueChanged.connect(self.position_editors)

    def sync_reports_button(self):
        self.reports_button.setText(self.reports.currentText())
        for index, action in enumerate(self.reports_button.menu().actions()):
            action.setChecked(index == self.reports.currentIndex())

    def enable_width_fitting(self):
        """Fill the viewport while keeping every section interactively resizable."""
        self._width_preferences = {i: self.sectionSize(i) for i in range(self.count())}
        self._width_layout = None
        self._fitting_widths = False
        self._width_timer = QTimer(self)
        self._width_timer.setSingleShot(True)
        self._width_timer.timeout.connect(self.fit_available_width)
        self.sectionResized.connect(self.remember_width)
        self.geometriesChanged.connect(self.schedule_width_fitting)
        self._table_viewport = self.page.table.viewport()
        self._table_viewport.installEventFilter(self)
        self._width_timer.start(0)

    def schedule_width_fitting(self):
        if not sip.isdeleted(self._width_timer) and not sip.isdeleted(self._table_viewport):
            self._width_timer.start(0)

    def eventFilter(self, watched, event):
        # Destruction events arrive after the parent table's C++ object is gone.
        # Compare the cached viewport without calling back into that table.
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "_table_viewport", None):
            self.schedule_width_fitting()
        return super().eventFilter(watched, event)

    def remember_width(self, logical, old_size, new_size):
        if not self._fitting_widths and not self.isSectionHidden(logical) and new_size > 0:
            self._width_preferences[logical] = new_size

    def fit_available_width(self):
        if sip.isdeleted(self) or sip.isdeleted(self._table_viewport):
            return
        visible = tuple(i for i in range(self.count()) if not self.isSectionHidden(i))
        available = self._table_viewport.width()
        layout = (available, visible)
        if layout == self._width_layout or not visible or available <= 0:
            return
        self._width_layout = layout
        # Preserve readable filters on small windows; horizontal scrolling remains available.
        minimums = {i: max(self.minimumSectionSize(), px(145 if i == 0 else 130)) for i in visible}
        extra = max(0, available - sum(minimums.values()))
        weights = {i: max(1, self._width_preferences[i] - minimums[i]) for i in visible}
        total = sum(weights.values())
        allocated = 0
        self._fitting_widths = True
        try:
            for index, logical in enumerate(visible):
                share = (
                    extra - allocated
                    if index == len(visible) - 1
                    else extra * weights[logical] // total
                )
                allocated += share
                self.resizeSection(logical, minimums[logical] + share)
        finally:
            self._fitting_widths = False
        self.position_editors()

    def sizeHint(self):
        size = super().sizeHint()
        return QSize(size.width(), size.height() + self.filter_area_height())

    def filter_area_height(self):
        return px(16 if self.filters_collapsed else 64)

    def toggle_filters(self):
        self.filters_collapsed = not self.filters_collapsed
        self.collapse_button.setIcon(icon("plus" if self.filters_collapsed else "minus"))
        self.collapse_button.setToolTip(
            tr("Rozwiń filtry") if self.filters_collapsed else tr("Zwiń filtry")
        )
        self.updateGeometry()
        self.page.table.updateGeometries()
        self.position_editors()
        self.viewport().update()

    def sectionSizeFromContents(self, logical):
        size = super().sectionSizeFromContents(logical)
        if logical in self.editors:
            size.setWidth(max(size.width(), px(145 if logical == 0 else 130)))
        return size

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        column = self.logicalIndexAt(point)
        self._sort_press = None
        if column >= 0 and point.y() < self.height() - self.filter_area_height():
            left = self.sectionViewportPosition(column)
            if left + 5 < point.x() < left + self.sectionSize(column) - 5:
                self._sort_press = (point, column)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        press = getattr(self, "_sort_press", None)
        self._sort_press = None
        if (
            event.button() == Qt.MouseButton.LeftButton
            and press is not None
            and (event.position().toPoint() - press[0]).manhattanLength() < 4
        ):
            with QSignalBlocker(self):
                super().mouseReleaseEvent(event)
            self.page.sort_column(
                press[1], bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            )
            return
        super().mouseReleaseEvent(event)

    def paintSection(self, painter, rect, logical):
        heading = QRect(rect.x(), rect.y(), rect.width(), rect.height() - self.filter_area_height())
        super().paintSection(painter, heading, logical)
        if logical in self.active:
            painter.save()
            painter.fillRect(
                heading.x() + px(4),
                heading.bottom() - px(2),
                heading.width() - px(8),
                px(2),
                QColor(display_color(ACCENT)),
            )
            painter.restore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_editors()

    def paintEvent(self, event):
        # Qt can finish resizing the last section after geometriesChanged.
        # Align the controls with its final geometry before displaying it.
        self.position_editors()
        super().paintEvent(event)

    def position_editors(self, *_):
        for column, editor in self.editors.items():
            editor.setVisible(not self.filters_collapsed and not self.isSectionHidden(column))
            editor.setGeometry(
                self.sectionViewportPosition(column),
                self.height() - self.filter_area_height(),
                self.sectionSize(column),
                px(48),
            )
            # Apply the new width to the fields immediately, including during
            # ResizeToContents updates after the visible transactions change.
            editor.layout().activate()
        if hasattr(self, "collapse_button"):
            self.collapse_button.setGeometry(
                max(0, self.viewport().width() - px(24)), self.height() - px(16), px(24), px(16)
            )
            self.collapse_button.raise_()

    def sync(self):
        filters = self.page.filters
        for target, source in ((self.currency, filters.currency),):
            with QSignalBlocker(target):
                target.clear()
                for i in range(source.count()):
                    target.addItem(source.itemText(i), source.itemData(i))
                target.setCurrentIndex(source.currentIndex())
        try:
            bounds = filters.period()
        except ValueError:
            bounds = tuple(
                edit.date().toString("yyyy-MM-dd") for edit in (filters.start, filters.end)
            )
        for edit, value, source in zip(self.dates, bounds, (filters.start, filters.end)):
            with QSignalBlocker(edit):
                date = QDate.fromString(value, "yyyy-MM-dd") if value else edit.minimumDate()
                if date in (source.minimumDate(), source.maximumDate()):
                    date = edit.minimumDate()
                edit.setDate(date)
                if date == edit.minimumDate():
                    today = QDate.currentDate()
                    edit.calendarWidget().setCurrentPage(today.year(), today.month())
        self.sync_choices(
            self.wallet,
            filters.selected_wallet_ids,
            [
                (w["id"], w["name"])
                for w in self.page.db.wallets()
                if w["currency"] == filters.currency.currentData()
            ],
            tr("Szukaj portfela…"),
            self.wallet_changed,
            self.clear_wallets,
        )
        self.sync_choices(
            self.categories,
            getattr(filters, "selected_category_ids", set()),
            [(r["id"], r["display_name"]) for r in self.page.db.categories()],
            tr("Szukaj kategorii…"),
            self.category_changed,
            self.clear_categories,
        )

    def sync_choices(self, button, selected, rows, placeholder, changed, clear_selection):
        button.setText(
            tr("Wszystkie") if not selected else tr("Wybrano: {count}", count=len(selected))
        )
        # Keep an open popup intact while its checkboxes refresh the table.
        old = button.menu()
        if old is None or not old.isVisible():
            menu = CategoryMenu(button, rows, selected, placeholder, changed, clear_selection)
            button.setMenu(menu)
            if old:
                old.deleteLater()

    def wallet_changed(self, key, checked):
        filters = self.page.filters
        selected = set(filters.selected_wallet_ids)
        selected.add(key) if checked else selected.discard(key)
        filters.selected_wallet_ids = selected
        with QSignalBlocker(filters.wallet):
            filters.wallet.setCurrentIndex(
                max(0, filters.wallet.findData(next(iter(selected)))) if len(selected) == 1 else 0
            )
        self.page.refresh()

    def clear_wallets(self):
        self.page.filters.selected_wallet_ids = set()
        with QSignalBlocker(self.page.filters.wallet):
            self.page.filters.wallet.setCurrentIndex(0)
        if self.wallet.menu():
            self.wallet.menu().close()
        self.page.refresh()

    def currency_changed(self):
        self.page.filters.currency.setCurrentIndex(
            self.page.filters.currency.findData(self.currency.currentData())
        )

    def category_changed(self, key, checked):
        selected = set(getattr(self.page.filters, "selected_category_ids", set()))
        selected.add(key) if checked else selected.discard(key)
        self.page.filters.selected_category_ids = selected
        self.page.refresh()

    def clear_categories(self):
        self.page.filters.selected_category_ids = set()
        if self.categories.menu():
            self.categories.menu().close()
        self.page.refresh()

    def date_changed(self):
        first, last = (edit.date() for edit in self.dates)
        filters = self.page.filters
        # A single bound is represented by the supported calendar extremes.
        with (
            QSignalBlocker(filters.start),
            QSignalBlocker(filters.end),
            QSignalBlocker(filters.preset),
        ):
            filters.start.setDate(
                first if first != self.dates[0].minimumDate() else filters.start.minimumDate()
            )
            filters.end.setDate(
                last if last != self.dates[1].minimumDate() else filters.end.maximumDate()
            )
            filters.preset.setCurrentIndex(
                filters.preset.findData(
                    "all" if all(e.date() == e.minimumDate() for e in self.dates) else "custom"
                )
            )
        self.page.refresh()

    def apply(self, rows):
        self.active = set()
        if any(e.date() != e.minimumDate() for e in self.dates):
            self.active.add(0)
        if self.page.filters.selected_wallet_ids:
            self.active.add(1)
        if getattr(self.page.filters, "selected_category_ids", set()):
            self.active.add(3)
        if self.reports.currentData() is not None:
            self.active.add(10)
            rows = [r for r in rows if bool(r["include_in_reports"]) == self.reports.currentData()]
        keys = {
            2: "from_to",
            4: "subcategory",
            7: "description",
            8: "category_source",
            11: "analysis_kind",
        }
        for column, edit in self.text_fields.items():
            query = edit.text().strip().casefold()
            if query:
                self.active.add(column)

                def value(row):
                    if column == 9:
                        return (
                            tr("Konflikt reguł")
                            if row["category_conflict"]
                            else tr("Możliwy konflikt")
                            if row["possible_conflict"]
                            else ""
                        )
                    if column == 11:
                        from home_finance_cockpit.domain.analysis_kinds import ANALYSIS_KINDS

                        return tr(ANALYSIS_KINDS[row["analysis_kind"]])
                    return str(row[keys[column]]) + (" " + row["from_to"] if column == 7 else "")

                rows = [r for r in rows if query in value(r).casefold()]
        invalid = False
        for column, fields in self.ranges.items():
            bounds = []
            for edit in fields:
                try:
                    bounds.append(money_minor(edit.text()) if edit.text().strip() else None)
                    edit.setToolTip("")
                    edit.setStyleSheet("")
                except ValueError as exc:
                    bounds.append(None)
                    invalid = True
                    edit.setToolTip(str(exc))
                    edit.setStyleSheet(f"border: 1px solid {display_color(RED)};")
            low, high = bounds
            if any(e.text().strip() for e in fields):
                self.active.add(column)
            if low is not None and high is not None and low > high:
                invalid = True
                for edit in fields:
                    edit.setToolTip(tr("Wartość od nie może być większa niż do."))
                    edit.setStyleSheet(f"border: 1px solid {display_color(RED)};")
            key = "amount_minor" if column == 5 else "balance_after_minor"
            rows = [
                r
                for r in rows
                if (low is None or r[key] >= low) and (high is None or r[key] <= high)
            ]
        for column, editor in self.editors.items():
            editor.setStyleSheet(
                "#transactionColumnFilter {"
                f"background: {display_color('#1e3347')}; border: 1px solid {display_color('#24394d')};"
                "border-radius: 0; margin: 0; padding: 2px 8px; min-height: 0;}"
            )
        self.position_editors()
        self.viewport().update()
        return [] if invalid else rows

    def clear(self):
        self.timer.stop()
        for edit in self.text_fields.values():
            with QSignalBlocker(edit):
                edit.clear()
        for fields in self.ranges.values():
            for edit in fields:
                with QSignalBlocker(edit):
                    edit.clear()
        with QSignalBlocker(self.reports):
            self.reports.setCurrentIndex(0)
        self.sync_reports_button()
