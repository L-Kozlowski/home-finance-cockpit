"""Three report setup sections and an always-visible output summary."""

from PyQt6.QtCore import QLocale, QSignalBlocker, QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.paths import reports_directory
from home_finance_cockpit.ui.chart_dates import format_date
from home_finance_cockpit.ui.components import icon, label, panel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import INK, display_color


def separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background:" + display_color("#24394D") + ";border:0;")
    return line


def build_workspace(owner):
    layout = QVBoxLayout(owner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(px(10))
    owner.splitter = QSplitter(Qt.Orientation.Horizontal)
    owner.splitter.setChildrenCollapsible(False)
    owner.splitter.setHandleWidth(px(12))
    layout.addWidget(owner.splitter, 1)
    owner.controls = QWidget()
    left = QVBoxLayout(owner.controls)
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(px(14))
    scope, box = panel()
    box.addWidget(label("1.  " + tr("Zakres"), "section"))
    box.addWidget(label(tr("Wybierz walutę, portfel i rok raportu.")))
    owner.currency, owner.wallet, owner.year = QComboBox(), QComboBox(), QComboBox()
    grid = QGridLayout()
    grid.setHorizontalSpacing(px(16))
    grid.setVerticalSpacing(px(12))
    for row, col, caption, field in (
        (0, 0, "Waluta", owner.currency),
        (0, 2, "Portfel", owner.wallet),
        (1, 0, "Rok", owner.year),
    ):
        field.setMinimumContentsLength(5)
        field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        grid.addWidget(label(tr(caption)), row, col)
        grid.addWidget(field, row, col + 1)
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 2)
    box.addLayout(grid)
    left.addWidget(scope, 1)
    period, box = panel()
    head = QHBoxLayout()
    head.addWidget(label("2.  " + tr("Okres raportu"), "section"), 1)
    owner.annual = QCheckBox(tr("Uwzględnij raport roczny"))
    owner.annual.setChecked(True)
    head.addWidget(owner.annual)
    box.addLayout(head)
    box.addWidget(label(tr("Wybierz miesiące raportów i opcjonalnie raport roczny.")))
    owner.tabs = QTabBar()
    owner.tabs.setObjectName("reportTabs")
    owner.tabs.setExpanding(False)
    owner.tabs.setDrawBase(False)
    owner.tabs.addTab(tr("Raporty miesięczne"))
    owner.tabs.addTab(tr("Raport roczny"))
    box.addWidget(owner.tabs)
    owner.period_stack = QStackedWidget()
    owner.tabs.currentChanged.connect(owner.period_stack.setCurrentIndex)
    box.addWidget(owner.period_stack)
    monthly_page = QWidget()
    m = QVBoxLayout(monthly_page)
    m.setContentsMargins(0, px(6), 0, 0)
    m.setAlignment(Qt.AlignmentFlag.AlignTop)
    month_head = QHBoxLayout()
    owner.monthly = QCheckBox(tr("Generuj raporty miesięczne"))
    owner.monthly.setChecked(True)
    month_head.addWidget(owner.monthly)
    month_head.addStretch()
    owner.grid_year = QComboBox()
    owner.grid_year.setMinimumContentsLength(5)
    month_head.addWidget(owner.grid_year)
    m.addLayout(month_head)
    owner.months = QListWidget(owner)
    owner.months.hide()
    owner.month_grid = QWidget()
    owner.month_layout = QGridLayout(owner.month_grid)
    owner.month_layout.setContentsMargins(0, 0, 0, 0)
    owner.month_layout.setSpacing(px(8))
    m.addWidget(owner.month_grid)
    owner.month_buttons = {}
    actions = QHBoxLayout()
    owner.month_count = label("")
    actions.addWidget(owner.month_count, 1)
    for caption, checked in (("Zaznacz dostępne", True), ("Wyczyść zaznaczenie", False)):
        button = QPushButton(tr(caption))
        button.setProperty("role", "link")
        button.clicked.connect(lambda clicked=False, state=checked: owner.select_months(state))
        actions.addWidget(button)
    m.addLayout(actions)
    owner.period_stack.addWidget(monthly_page)
    annual_page = QWidget()
    annual = QVBoxLayout(annual_page)
    annual.setContentsMargins(0, px(10), 0, 0)
    owner.annual_note = label("")
    annual.addWidget(owner.annual_note)
    owner.annual_months = label("")
    annual.addWidget(owner.annual_months)
    annual.addStretch()
    owner.period_stack.addWidget(annual_page)
    left.addWidget(period, 2)
    contents, box = panel()
    box.setAlignment(Qt.AlignmentFlag.AlignTop)
    box.addWidget(label("3.  " + tr("Zawartość raportów"), "section"))
    box.addWidget(label(tr("Wybierz elementy, które znajdą się w raportach.")))
    grid = QGridLayout()
    grid.setHorizontalSpacing(px(20))
    grid.setVerticalSpacing(px(12))
    owner.transactions = QCheckBox(tr("Szczegóły transakcji"))
    owner.uncategorized = QCheckBox(tr("Nieprzypisane wydatki"))
    owner.comparison = QCheckBox(tr("Porównanie miesięcy"))
    owner.exclude = QCheckBox(tr("Pomiń wymiany i nieukończone operacje"))
    features = (
        (owner.transactions, "Lista transakcji w raportach miesięcznych."),
        (owner.comparison, "Porównanie kategorii z poprzednim miesiącem."),
        (owner.uncategorized, "Osobne zestawienie nieprzypisanych wydatków."),
        (owner.exclude, "Pomija wymiany walut i operacje niezakończone lub cofnięte."),
    )
    for i, (check, description) in enumerate(features):
        check.setChecked(True)
        check.setToolTip(tr(description))
        field = QWidget()
        f = QVBoxLayout(field)
        f.setAlignment(Qt.AlignmentFlag.AlignTop)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(px(3))
        f.addWidget(check)
        f.addWidget(label(tr(description)))
        grid.addWidget(field, i // 2, i % 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    box.addLayout(grid)
    box.addStretch(1)
    box.addWidget(separator())
    advanced = QPushButton(tr("Opcje zaawansowane"))
    advanced.setIcon(icon("chevron_down"))
    advanced.setCheckable(True)
    advanced.setProperty("role", "link")
    box.addWidget(advanced, 0, Qt.AlignmentFlag.AlignLeft)
    options = QWidget()
    a = QVBoxLayout(options)
    a.setContentsMargins(px(8), 0, 0, 0)
    owner.after_refunds = QCheckBox(tr("Koszty po zwrotach i rozliczeniach"))
    owner.omit_salary = QCheckBox(tr("Pomiń pensje w zestawieniu wpływów"))
    a.addWidget(owner.after_refunds)
    a.addWidget(owner.omit_salary)
    box.addWidget(options)
    options.hide()
    advanced.toggled.connect(options.setVisible)
    left.addWidget(contents, 2)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(owner.controls)
    owner.splitter.addWidget(scroll)
    right, box = panel()
    owner.splitter.addWidget(right)
    box.addWidget(label(tr("Podsumowanie raportów"), "section"))
    box.addWidget(label(tr("Raporty i ustawienia wybrane do wygenerowania.")))
    tile, t = panel()
    tile.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    row = QHBoxLayout()
    glyph = label("")
    glyph.setPixmap(icon("file", display_color("#A8BED5")).pixmap(px(40), px(40)))
    row.addWidget(glyph)
    text = QVBoxLayout()
    owner.report_count = label("", "section")
    owner.report_breakdown = label("")
    text.addWidget(owner.report_count)
    text.addWidget(owner.report_breakdown)
    row.addLayout(text, 1)
    t.addLayout(row)
    box.addWidget(tile)
    owner.documents = QListWidget()
    owner.documents.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    owner.documents.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    owner.documents.setMinimumHeight(px(150))
    box.addWidget(owner.documents, 2)
    box.addWidget(separator())
    box.addWidget(label(tr("Zakres"), "section"))
    owner.summary_scope = label("")
    box.addWidget(owner.summary_scope)
    box.addWidget(separator())
    box.addWidget(label(tr("Zawartość raportów"), "section"))
    owner.summary_features = label("")
    owner.summary_features.setAlignment(Qt.AlignmentFlag.AlignTop)
    box.addWidget(owner.summary_features, 1)
    box.addWidget(separator())
    box.addWidget(label(tr("Folder wyników"), "section"))
    owner.output = QLineEdit(str(reports_directory()))
    owner.output.setToolTip(owner.output.text())
    owner.output.textChanged.connect(owner.output.setToolTip)
    owner.output.textChanged.connect(owner.schedule_summary)
    output = QHBoxLayout()
    output.setSpacing(0)
    output.addWidget(owner.output, 1)
    owner.choose_button = QPushButton()
    owner.choose_button.setIcon(icon("folder"))
    owner.choose_button.setToolTip(tr("Wybierz folder…"))
    owner.choose_button.clicked.connect(owner.choose_output)
    output.addWidget(owner.choose_button)
    box.addLayout(output)
    owner.generate_button = QPushButton(tr("Generuj raporty PDF"))
    owner.generate_button.setProperty("role", "primary")
    owner.generate_button.setIcon(icon("file", INK))
    owner.generate_button.setMinimumHeight(px(46))
    owner.generate_button.clicked.connect(owner.generate)
    box.addWidget(owner.generate_button)
    owner.open_button = QPushButton(tr("Otwórz folder wyników"))
    owner.open_button.setIcon(icon("folder"))
    owner.open_button.setEnabled(False)
    owner.open_button.clicked.connect(owner.open_output)
    box.addWidget(owner.open_button)
    owner.cancel_button = QPushButton(tr("Anuluj generowanie"))
    owner.cancel_button.setEnabled(False)
    owner.cancel_button.hide()
    owner.cancel_button.clicked.connect(owner.cancel)
    box.addWidget(owner.cancel_button)
    owner.progress = QProgressBar()
    owner.progress.hide()
    box.addWidget(owner.progress)
    owner.status = label(tr("Gotowe do generowania raportów."))
    layout.addWidget(owner.status)
    owner.splitter.setStretchFactor(0, 3)
    owner.splitter.setStretchFactor(1, 2)
    owner.splitter.setSizes([px(740), px(500)])
    owner.summary_timer = QTimer(owner)
    owner.summary_timer.setSingleShot(True)
    owner.summary_timer.setInterval(150)
    owner.summary_timer.timeout.connect(owner.refresh_summary)
    for check in (
        owner.monthly,
        owner.annual,
        owner.transactions,
        owner.uncategorized,
        owner.comparison,
        owner.exclude,
        owner.after_refunds,
        owner.omit_salary,
    ):
        check.toggled.connect(owner.schedule_summary)
    owner.months.itemChanged.connect(owner.schedule_summary)
    owner.grid_year.currentIndexChanged.connect(lambda *_: refresh_month_grid(owner))
    for caption in owner.findChildren(QLabel):
        caption.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    owner.summary_features.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    bg = display_color("#0B1623")
    border = display_color("#24394D")
    accent = display_color("#22D3EE")
    owner.setStyleSheet(
        'QLabel[role="section"] {font-size:'
        + str(px(18))
        + 'px;font-weight:600;} QPushButton[monthTile="true"] {min-height:'
        + str(px(34))
        + 'px;} QPushButton[monthTile="true"]:checked {background:'
        + accent
        + ";color:"
        + INK
        + ";border-color:"
        + accent
        + ";} QFrame#card {background:"
        + display_color("#112233")
        + ";border:1px solid "
        + border
        + ";border-radius:5px;} QLineEdit,QComboBox {background:"
        + bg
        + ";border:1px solid "
        + border
        + ";border-radius:5px;padding:9px;} QTabBar#reportTabs::tab {background:transparent;border:0;border-bottom:3px solid transparent;padding:12px 18px;color:"
        + display_color("#A8BED5")
        + ";} QTabBar#reportTabs::tab:selected {color:"
        + accent
        + ";border-bottom-color:"
        + accent
        + ';font-weight:600;} QPushButton[role="link"] {background:transparent;border:0;color:'
        + accent
        + ";padding:3px;} QListWidget {background:transparent;border:0;} QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;}"
    )


def refresh_month_grid(owner):
    available = {
        owner.months.item(i).text(): owner.months.item(i) for i in range(owner.months.count())
    }
    years = sorted({m[:4] for m in available})
    current = owner.grid_year.currentData()
    with QSignalBlocker(owner.grid_year):
        owner.grid_year.clear()
        for year in years:
            owner.grid_year.addItem(year, year)
        owner.grid_year.setCurrentIndex(
            max(0, owner.grid_year.findData(current or (years[-1] if years else "")))
        )
    owner.grid_year.setVisible(len(years) > 1)
    year = owner.grid_year.currentData()
    owner.month_grid.setEnabled(True)
    while owner.month_layout.count():
        item = owner.month_layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
    owner.month_buttons = {}
    for number in range(1, 13):
        key = f"{year}-{number:02d}"
        item = available.get(key)
        button = QPushButton(QLocale().monthName(number, QLocale.FormatType.ShortFormat))
        button.setProperty("monthTile", True)
        button.setCheckable(True)
        button.setMinimumHeight(px(42))
        button.setEnabled(item is not None and owner.monthly.isChecked())
        button.setChecked(item is not None and item.checkState() == Qt.CheckState.Checked)
        if item is not None:
            button.setToolTip(format_date(key))
            button.toggled.connect(
                lambda checked, item=item: item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
            )
        owner.month_layout.addWidget(button, (number - 1) // 6, (number - 1) % 6)
        owner.month_buttons[key] = button
    count = sum(item.checkState() == Qt.CheckState.Checked for item in available.values())
    owner.month_count.setText(tr("Wybrane miesiące: {count}", count=count))


def refresh_documents(owner, monthly, years, eligible):
    owner.documents.clear()
    for caption, values in ((tr("Raporty miesięczne"), monthly), (tr("Raport roczny"), years)):
        heading = QListWidgetItem(f"{caption} ({len(values)})")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading.setSizeHint(QSize(0, px(34)))
        owner.documents.addItem(heading)
        for value in values:
            item = QListWidgetItem(icon("file"), format_date(value) if len(value) == 7 else value)
            item.setSizeHint(QSize(0, px(32)))
            owner.documents.addItem(item)
    owner.documents.setMaximumHeight(
        max(px(150), min(px(340), px(34) * owner.documents.count() + px(8)))
    )
    owner.summary_scope.setText(
        " · ".join(
            (owner.currency.currentText(), owner.wallet.currentText(), owner.year.currentText())
        )
    )
    checks = (
        owner.transactions,
        owner.uncategorized,
        owner.comparison,
        owner.exclude,
        owner.after_refunds,
        owner.omit_salary,
    )
    owner.summary_features.setText(
        "\n".join("• " + check.text() for check in checks if check.isChecked())
        or tr("Podsumowanie finansowe")
    )
    owner.annual_months.setText(", ".join(format_date(m) for m in eligible))
