"""Draft filter selections: only Apply changes the underlying page."""

from PyQt6.QtCore import QDate, QSignalBlocker, QSize, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.categories import category_name
from home_finance_cockpit.domain.validation import date_range
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.amount_range import amount_range
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.common import show_error
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import display_color


class CategoryCheckItem(QTreeWidgetItem):
    def data(self, *args):
        return super().data(0, args[0]) if len(args) == 1 else super().data(*args)

    def checkState(self, column=0):
        return super().checkState(column)

    def setCheckState(self, *args):
        return super().setCheckState(0, args[0]) if len(args) == 1 else super().setCheckState(*args)


class CategoryChecks(QTreeWidget):
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]


def copy_combo(source, target):
    target.clear()
    for index in range(source.count()):
        target.addItem(source.itemIcon(index), source.itemText(index), source.itemData(index))
    target.setCurrentIndex(source.currentIndex())


def select(combo, value):
    combo.setCurrentIndex(max(0, combo.findData(value)))


def category_summary(owner):
    selected = getattr(owner, "selected_category_ids", set())
    return tr(" · Kategorie: {count}", count=len(selected)) if selected else ""


class FiltersDialog(QDialog):
    def __init__(self, owner, *, transactions=False):
        super().__init__(owner)
        self.owner, self.transactions = (
            owner.transaction_filters if transactions else owner,
            transactions,
        )
        owner = self.owner
        self.setWindowTitle((tr("Filtry transakcji") if transactions else tr("Filtry widoku")))
        self.resize(px(760), px(860))
        self.setMinimumWidth(px(480))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(px(18), px(16), px(18), px(16))
        outer.setSpacing(px(12))
        outer.addWidget(label(self.windowTitle(), "section"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(12))
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.fields = {}
        names = [
            ("currency", "Waluta"),
            ("wallet", "Portfel"),
            ("preset", "Okres"),
            ("start", "Od"),
            ("end", "Do"),
            ("year", "Rok"),
            ("month", "Miesi\u0105c"),
            ("exclude", "Wykluczenia"),
            ("amount_min", "Kwota od"),
            ("amount_max", "Kwota do"),
        ]
        for key, caption in names:
            if not hasattr(owner, key):
                continue
            source = getattr(owner, key)
            if isinstance(source, QComboBox):
                widget = QComboBox()
                copy_combo(source, widget)
            elif isinstance(source, QDateEdit):
                widget = QDateEdit(source.date())
                widget.setCalendarPopup(True)
                from home_finance_cockpit.ui.calendar import MonthCalendar

                widget.setCalendarWidget(MonthCalendar(widget))
                from home_finance_cockpit.ui.chart_dates import get_date_format

                widget.setDisplayFormat(get_date_format())
                widget.setDateRange(source.minimumDate(), source.maximumDate())
            elif isinstance(source, QLineEdit):
                widget = QLineEdit(source.text())
                widget.setClearButtonEnabled(True)
            else:
                widget = QCheckBox(
                    tr("Poka\u017c udzia\u0142y procentowe")
                    if key == "percentage"
                    else source.text()
                )
                widget.setChecked(source.isChecked())
            self.fields[key] = widget
            setattr(self, key, widget)
        scope, box = panel()
        box.addWidget(label(tr("Zakres"), "section"))
        grid = QGridLayout()
        for col, (key, caption) in enumerate((("currency", "Waluta"), ("wallet", "Portfel"))):
            if key in self.fields:
                grid.addWidget(label(tr(caption)), 0, col)
                grid.addWidget(self.fields[key], 1, col)
                grid.setColumnStretch(col, 1)
        box.addLayout(grid)
        layout.addWidget(scope)
        if "amount_min" in self.fields:
            amounts, amount_layout = panel()
            amount_layout.addWidget(label(tr("Przedział kwot"), "section"))
            amount_row = QGridLayout()
            for col, key in enumerate(("amount_min", "amount_max")):
                amount_row.addWidget(label(tr("Kwota od") if col == 0 else tr("Kwota do")), 0, col)
                amount_row.addWidget(self.fields[key], 1, col)
            amount_layout.addLayout(amount_row)
            layout.addWidget(amounts)
        period, box = panel()
        box.addWidget(label(tr("Okres"), "section"))
        self.period_buttons = QButtonGroup(self)
        quick = QHBoxLayout()
        for caption, value in [
            ("Wszystko", "all"),
            ("Ten miesi\u0105c", "this_month"),
            ("Ten rok", "this_year"),
            ("Zakres dat", "custom"),
        ]:
            button = QPushButton(tr(caption))
            button.setCheckable(True)
            button.setProperty("periodValue", value)
            button.clicked.connect(lambda checked=False, value=value: self.choose_period(value))
            self.period_buttons.addButton(button)
            quick.addWidget(button)
        box.addLayout(quick)
        grid = QGridLayout()
        for row, keys in enumerate(((("start", "Od"), ("end", "Do")),)):
            for col, (key, caption) in enumerate(keys):
                if key in self.fields:
                    grid.addWidget(label(tr(caption)), row * 2, col)
                    grid.addWidget(self.fields[key], row * 2 + 1, col)
                    grid.setColumnStretch(col, 1)
        box.addLayout(grid)
        advanced = QWidget()
        advanced_layout = QGridLayout(advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        for col, key in enumerate(("year", "month")):
            if key in self.fields:
                advanced_layout.addWidget(self.fields[key], 0, col)
        if "preset" in self.fields:
            advanced_layout.addWidget(self.preset, 1, 0, 1, 2)
        more = QPushButton(tr("Więcej okresów"))
        more.setCheckable(True)
        more.setProperty("role", "link")
        more.toggled.connect(advanced.setVisible)
        box.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(advanced)
        advanced.setVisible(
            any(
                key in self.fields and self.fields[key].currentData() is not None
                for key in ("year", "month")
            )
        )
        layout.addWidget(period)
        categories_panel, box = panel()
        head = QHBoxLayout()
        head.addWidget(label(tr("Kategorie"), "section"), 1)
        self.category_count = label("")
        head.addWidget(self.category_count)
        box.addLayout(head)
        search = QHBoxLayout()
        self.category_search = QLineEdit()
        self.category_search.setPlaceholderText(tr("Szukaj kategorii…"))
        self.category_search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.category_search.setClearButtonEnabled(True)
        search.addWidget(self.category_search, 1)
        clear = QPushButton(tr("Wyczy\u015b\u0107 zaznaczenie"))
        clear.clicked.connect(self.clear_categories)
        search.addWidget(clear)
        self.select_all = QCheckBox(tr("Zaznacz wszystkie"))
        self.select_all.clicked.connect(self.check_all)
        search.addWidget(self.select_all)
        box.addLayout(search)
        self.categories = CategoryChecks()
        self.categories.items = []
        self.categories.setHeaderHidden(True)
        self.categories.setMinimumHeight(px(220))
        self.categories.setIndentation(px(24))
        self.categories.setIconSize(QSize(px(20), px(20)))
        categories = [dict(r) for r in owner.db.categories()]
        nodes = {}
        from home_finance_cockpit.reports.presentation import category_color
        from home_finance_cockpit.ui.category_explorer import dot

        selected = getattr(owner, "selected_category_ids", set())
        for row in categories:
            item = CategoryCheckItem([category_name(row)])
            item.setData(0, Qt.ItemDataRole.UserRole, row["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setSizeHint(0, QSize(0, px(30)))
            nodes[row["id"]] = item
            self.categories.items.append(item)
        for row in categories:
            item = nodes[row["id"]]
            parent = nodes.get(row["parent_id"])
            root = next((c for c in categories if c["id"] == row["parent_id"]), row)
            tint = category_color(root["name"], {root["name"]: root["color"]})
            item.setIcon(0, dot(tint) if parent else icon(root["icon_name"], tint))
            if parent:
                parent.addChild(item)
            else:
                self.categories.addTopLevelItem(item)
            item.setCheckState(
                Qt.CheckState.Checked
                if row["id"] in selected or row["parent_id"] in selected
                else Qt.CheckState.Unchecked
            )
        for i in range(self.categories.topLevelItemCount()):
            root = self.categories.topLevelItem(i)
            if root.childCount():
                root.setFlags(root.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            root.setExpanded(False)
        box.addWidget(self.categories, 1)
        note = label(tr("Brak zaznaczenia = wszystkie kategorie"))
        note.setAlignment(Qt.AlignmentFlag.AlignRight)
        box.addWidget(note)
        layout.addWidget(categories_panel, 1)
        options = [key for key in ("exclude",) if key in self.fields]
        if options:
            section, box = panel()
            box.addWidget(label(tr("Wykluczenia"), "section"))
            for key in options:
                box.addWidget(self.fields[key])
            layout.addWidget(section)
        self.category_search.textChanged.connect(self.search_categories)
        self.categories.itemChanged.connect(self.update_category_count)
        self.update_category_count()
        if "currency" in self.fields:
            self.currency.currentIndexChanged.connect(self.currency_changed)
            self.wallet.currentIndexChanged.connect(self.wallet_changed)
        if "preset" in self.fields:
            self.preset.currentIndexChanged.connect(self.period_changed)
            self.period_changed()
        if "year" in self.fields:
            self.year.currentIndexChanged.connect(self.year_changed)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Zastosuj filtry"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Anuluj"))
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText(
            tr("Wyczy\u015b\u0107 filtry")
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).clicked.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self.reset_filters)
        footer = QHBoxLayout()
        footer.addWidget(buttons.button(QDialogButtonBox.StandardButton.Reset))
        footer.addStretch()
        footer.addWidget(buttons.button(QDialogButtonBox.StandardButton.Cancel))
        footer.addWidget(buttons.button(QDialogButtonBox.StandardButton.Ok))
        outer.addLayout(footer)
        bg = display_color("#0B1623")
        border = display_color("#24394D")
        self.setStyleSheet(
            "QFrame#card {background:"
            + display_color("#112233")
            + ";border:1px solid "
            + border
            + ";border-radius:5px;} QLineEdit,QComboBox,QDateEdit {background:"
            + bg
            + ";border:1px solid "
            + border
            + ';border-radius:5px;padding:7px;} QPushButton[role="link"] {background:transparent;border:0;color:'
            + display_color("#A8BED5")
            + ";padding:2px;text-decoration:underline;} QTreeWidget {background:"
            + bg
            + ";border:1px solid "
            + border
            + ";border-radius:5px;} QTreeWidget::item {padding:3px;} QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;}"
        )
        screen = self.screen().availableGeometry()
        self.resize(
            min(self.width(), screen.width() - 40), min(self.height(), screen.height() - 60)
        )

    def choose_period(self, value):
        if "preset" in self.fields:
            select(self.preset, value)
        elif "year" in self.fields:
            select(self.year, QDate.currentDate().year() if value == "this_year" else None)
            select(
                self.month,
                QDate.currentDate().toString("yyyy-MM") if value == "this_month" else None,
            )

    def clear_categories(self):
        with QSignalBlocker(self.categories):
            for item in self.categories.items:
                item.setCheckState(Qt.CheckState.Unchecked)
        self.update_category_count()

    def check_all(self, checked):
        with QSignalBlocker(self.categories):
            for item in self.categories.items:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.update_category_count()

    def update_category_count(self, *_):
        count = sum(
            item.checkState() == Qt.CheckState.Checked
            and (item.parent() is None or item.parent().checkState() != Qt.CheckState.Checked)
            for item in self.categories.items
        )
        self.category_count.setText(tr("Wybrano: {count}", count=count))
        with QSignalBlocker(self.select_all):
            self.select_all.setChecked(
                bool(self.categories.items)
                and all(i.checkState() == Qt.CheckState.Checked for i in self.categories.items)
            )

    def search_categories(self, text):
        terms = normalize(text).split()
        for i in range(self.categories.topLevelItemCount()):
            root = self.categories.topLevelItem(i)
            matches_root = all(t in normalize(root.text(0)) for t in terms)
            visible = matches_root
            for n in range(root.childCount()):
                child = root.child(n)
                show = matches_root or all(t in normalize(child.text(0)) for t in terms)
                child.setHidden(not show)
                visible |= show
            root.setHidden(not visible)
            if terms and visible:
                root.setExpanded(True)

    def currency_changed(self):
        current = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(tr("Wszystkie w wybranej walucie"), None)
            for wallet in self.owner.db.wallets():
                if (not self.transactions and self.currency.currentData() == "PLN") or wallet[
                    "currency"
                ] == self.currency.currentData():
                    self.wallet.addItem(icon(wallet["icon_name"]), wallet["name"], wallet["id"])
            select(self.wallet, current)
        self.wallet_changed()

    def months(self):
        return sorted(
            {
                row["date"][:7]
                for row in self.owner.db.transactions(self.wallet.currentData())
                if (
                    (not self.transactions and self.currency.currentData() == "PLN")
                    or row["currency"] == self.currency.currentData()
                )
                and row["include_in_reports"]
            }
        )

    def wallet_changed(self):
        if "year" not in self.fields:
            return
        current = self.year.currentData()
        with QSignalBlocker(self.year):
            self.year.clear()
            self.year.addItem(tr("Wszystkie lata"), None)
            for year in sorted({month[:4] for month in self.months()}):
                self.year.addItem(year, int(year))
            select(self.year, current)
        self.year_changed()

    def year_changed(self):
        current = self.month.currentData()
        self.month.clear()
        self.month.addItem(tr("Cały wybrany okres"), None)
        for month in self.months():
            if self.year.currentData() is None or int(month[:4]) == self.year.currentData():
                self.month.addItem(month, month)
        select(self.month, current)

    def period_changed(self):
        for key in ("start", "end"):
            self.fields[key].setEnabled(self.preset.currentData() == "custom")
        for button in self.period_buttons.buttons():
            button.setChecked(button.property("periodValue") == self.preset.currentData())
        if "year" in self.fields:
            enabled = self.preset.currentData() == "all"
            self.year.setEnabled(enabled)
            self.month.setEnabled(enabled)
            if not enabled:
                with QSignalBlocker(self.year), QSignalBlocker(self.month):
                    select(self.year, None)
                    select(self.month, None)

    def reset_filters(self):
        self.reset_wallet_selection = True
        self.clear_categories()
        self.category_search.clear()
        for key in ("amount_min", "amount_max"):
            if key in self.fields:
                self.fields[key].clear()
        for key in ("wallet_filter", "wallet", "preset", "year", "month"):
            if key in self.fields:
                self.fields[key].setCurrentIndex(0)
        for key in ("exclude",):
            if key in self.fields:
                self.fields[key].setChecked(True)

    def accept(self):
        if "amount_min" in self.fields:
            try:
                amount_range(self.amount_min.text(), self.amount_max.text())
            except ValueError as exc:
                show_error(self, exc)
                return
        if "preset" in self.fields and self.preset.currentData() == "custom":
            try:
                date_range(
                    self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd")
                )
            except ValueError as exc:
                show_error(self, exc)
                return
        super().accept()

    def apply(self):
        if self.transactions:
            value = self.wallet.currentData()
            if (
                getattr(self, "reset_wallet_selection", False)
                or value != self.owner.wallet.currentData()
                or self.currency.currentData() != self.owner.currency.currentData()
            ):
                self.owner.selected_wallet_ids = {value} if value is not None else set()
        self.owner.selected_category_ids = {
            self.categories.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.categories.count())
            if self.categories.item(i).checkState() == Qt.CheckState.Checked
            and (
                self.categories.item(i).parent() is None
                or self.categories.item(i).parent().checkState() != Qt.CheckState.Checked
            )
        }
        blockers = [QSignalBlocker(getattr(self.owner, key)) for key in self.fields]
        try:
            for key, source in self.fields.items():
                target = getattr(self.owner, key)
                if isinstance(source, QComboBox):
                    copy_combo(source, target)
                elif isinstance(source, QDateEdit):
                    target.setDate(source.date())
                elif isinstance(source, QLineEdit):
                    target.setText(source.text())
                else:
                    target.setChecked(source.isChecked())
        finally:
            for blocker in blockers:
                blocker.unblock()
        if self.transactions:
            self.owner.refresh_transactions()
        else:
            self.owner.refresh()


def open_filters(owner, *, transactions=False):
    dialog = FiltersDialog(owner, transactions=transactions)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        dialog.apply()


def filter_toolbar(owner, *, transactions=False, reset_callback=None):
    class FilterToolbar(QHBoxLayout):
        def __init__(self):
            super().__init__()
            self.setContentsMargins(0, 0, 0, 0)
            frame = QFrame()
            frame.setObjectName("filterToolbar")
            frame.setMinimumHeight(px(46))
            frame.setStyleSheet(
                "QFrame#filterToolbar {background:"
                + display_color("#112233")
                + ";border:1px solid "
                + display_color("#24394D")
                + ";border-radius:5px;}"
            )
            self.content = QHBoxLayout(frame)
            self.content.setContentsMargins(px(5), px(5), px(12), px(5))
            self.content.setSpacing(px(14))
            super().addWidget(frame)

        def addWidget(self, widget, stretch=0, *args):
            self.content.insertWidget(max(0, self.content.count() - 1), widget, stretch, *args)

        def removeWidget(self, widget):
            self.content.removeWidget(widget)

    row = FilterToolbar()
    button = QPushButton(tr("Filtry"))
    button.setProperty("themeIcon", "filter")
    button.setIcon(icon("filter"))
    button.clicked.connect(lambda: open_filters(owner, transactions=transactions))
    summary = label("")
    row.content.addWidget(button)
    row.content.addWidget(summary, 1)
    clear = QPushButton(tr("Wyczyść filtry"))
    clear.setCursor(Qt.CursorShape.PointingHandCursor)
    clear.setIcon(icon("undo"))
    clear.setProperty("themeIcon", "undo")

    def reset():
        dialog = FiltersDialog(owner, transactions=transactions)
        dialog.reset_filters()
        dialog.apply()
        dialog.deleteLater()

    clear.clicked.connect(reset_callback or reset)
    row.clear_button = clear
    row.content.addWidget(clear)
    return row, button, summary
