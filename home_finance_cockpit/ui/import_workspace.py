"""Presentation of the guided, nonmodal transaction import workspace."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.importing import IMPORT_FIELDS
from home_finance_cockpit.ui.common import table
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.import_issues import ImportIssuesModel
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import MUTED, display_color, font_scale


class ElidedLabel(QLabel):
    """Keep long file names from forcing the source panel wider."""

    def __init__(self, text):
        super().__init__()
        self.full_text = text
        self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event):
        self.setText(
            self.fontMetrics().elidedText(
                self.full_text, Qt.TextElideMode.ElideMiddle, self.width()
            )
        )
        super().resizeEvent(event)


class ImportFileCard(QFrame):
    def __init__(self, name, subtitle, choose, remove):
        super().__init__()
        self.setObjectName("importFileCard")
        row = QHBoxLayout(self)
        row.setContentsMargins(px(12), px(10), px(8), px(10))
        glyph = QLabel()
        glyph.setPixmap(icon("file", "#10B981").pixmap(QSize(px(30), px(30))))
        row.addWidget(glyph)
        names = QVBoxLayout()
        names.setSpacing(px(3))
        self.name_label = ElidedLabel(name)
        names.addWidget(self.name_label)
        names.addWidget(label(subtitle))
        row.addLayout(names, 1)
        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("importRemoveFile")
        self.remove_button.setFixedSize(px(28), px(28))
        self.remove_button.setToolTip(tr("Usuń plik z importu"))
        self.remove_button.clicked.connect(remove)
        row.addWidget(self.remove_button)
        self.choose = choose
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose()
        super().mouseReleaseEvent(event)


def section():
    frame = QFrame()
    frame.setObjectName("importPanel")
    box = QVBoxLayout(frame)
    box.setContentsMargins(px(14), px(12), px(14), px(12))
    box.setSpacing(px(10))
    return frame, box


def step_marker(number, active=False, complete=False):
    size = px(40)
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(display_color("#22D3EE" if active or complete else "#7B8FA6")), 1.5))
    painter.setBrush(QColor(display_color("#22D3EE")) if active else Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    if complete:
        icon("check").paint(painter, px(10), px(10), px(20), px(20))
    else:
        painter.setPen(QColor("#062536" if active else display_color(MUTED)))
        font = painter.font()
        font.setPixelSize(px(18))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, str(number))
    painter.end()
    return QIcon(pixmap)


def build_workspace(dialog, db):
    """Build widgets while keeping file parsing and persistence in the controller."""
    dialog.setObjectName("importWorkspace")
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(px(18), px(16), px(18), px(14))
    outer.setSpacing(px(14))
    heading = QHBoxLayout()
    title = label(tr("Import transakcji"))
    title.setObjectName("importTitle")
    heading.addWidget(title)
    heading.addStretch(1)
    dialog.step_buttons = []
    for index, caption in enumerate(
        (tr("Pliki i źródło"), tr("Mapowanie i podgląd"), tr("Błędy i potwierdzenie"))
    ):
        if index:
            line = QFrame()
            line.setObjectName("importStepLine")
            line.setFixedSize(px(38), px(1))
            heading.addWidget(line)
        button = QPushButton(caption.replace("&", "&&"))
        button.setIconSize(QSize(px(40), px(40)))
        button.setObjectName("importStep")
        button.clicked.connect(lambda checked=False, step=index: dialog.go_to_step(step))
        dialog.step_buttons.append(button)
        heading.addWidget(button)
    outer.addLayout(heading)
    dialog.content_scroll = QScrollArea()
    dialog.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
    dialog.content_scroll.setWidgetResizable(True)
    content = QWidget()
    content.setMinimumSize(px(860), px(320))
    dialog.content_scroll.setWidget(content)
    outer.addWidget(dialog.content_scroll, 1)
    body = QVBoxLayout(content)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(px(12))
    dialog.pages = QStackedWidget()
    body.addWidget(dialog.pages, 1)
    source_page = QWidget()
    source_page_layout = QVBoxLayout(source_page)
    source_page_layout.setContentsMargins(0, 0, 0, 0)
    file_bar, file_bar_layout = section()
    dialog.file_bar = file_bar
    file_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    file_row = QHBoxLayout()
    file_bar_layout.addLayout(file_row)
    source_page_layout.addWidget(file_bar)
    dialog.splitter = QSplitter(Qt.Orientation.Horizontal)
    dialog.splitter.setChildrenCollapsible(False)
    source, source_layout = section()
    dialog.source_layout = source_layout
    source_layout.setSpacing(px(7))
    source.setMinimumWidth(px(260))
    source.setMaximumWidth(px(420))
    dialog.file_scroll = QScrollArea()
    dialog.file_scroll.setWidgetResizable(True)
    dialog.file_scroll.setFrameShape(QFrame.Shape.NoFrame)
    dialog.file_scroll.setFixedHeight(px(94))
    dialog.file_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    cards = QWidget()
    dialog.file_cards_layout = QHBoxLayout(cards)
    dialog.file_cards_layout.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    dialog.file_cards_layout.setContentsMargins(0, 0, 0, 0)
    dialog.file_cards_layout.setSpacing(px(8))
    dialog.file_cards_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    dialog.file_scroll.setWidget(cards)
    file_row.addWidget(dialog.file_scroll, 1)
    dialog.drop_button = QPushButton(tr("Upuść pliki CSV lub Excel tutaj\nlub kliknij, aby wybrać"))
    dialog.drop_button.setObjectName("importDropZone")
    dialog.drop_button.setIcon(icon("upload", MUTED))
    dialog.drop_button.setIconSize(QSize(px(26), px(26)))
    dialog.drop_button.setMinimumHeight(px(74))
    dialog.drop_button.clicked.connect(dialog.choose_file)
    dialog.drop_button.setMinimumWidth(px(240))
    file_row.addWidget(dialog.drop_button)
    dialog.filename = QLabel(dialog)
    dialog.filename.hide()
    source_layout.addSpacing(px(8))
    source_layout.addWidget(label(tr("Importuj do portfela"), "section"))
    dialog.wallet = QComboBox()
    for wallet in db.wallets():
        dialog.wallet.addItem(
            icon(wallet["icon_name"]), f"{wallet['name']} · {wallet['currency']}", wallet["id"]
        )
    source_layout.addWidget(dialog.wallet)
    source_layout.addSpacing(px(8))
    source_layout.addWidget(label(tr("Wiersz nagłówków"), "section"))
    header_settings = QGridLayout()
    header_settings.setColumnMinimumWidth(0, px(120))
    header_settings.setHorizontalSpacing(px(12))
    header_settings.setVerticalSpacing(px(10))
    dialog.header_mode = QComboBox()
    dialog.header_mode.addItem(tr("Automatycznie"), "auto")
    dialog.header_mode.addItem(tr("Ręcznie"), "manual")
    type_label = label(tr("Typ"))
    type_label.setFixedWidth(px(120))
    header_settings.addWidget(type_label, 0, 0)
    header_settings.addWidget(dialog.header_mode, 0, 1)
    dialog.header_row = QSpinBox()
    dialog.header_row.setObjectName("importHeaderRow")
    dialog.header_row.setRange(0, 200000)
    dialog.header_row.setSpecialValueText("—")
    dialog.header_row.setEnabled(False)
    dialog.header_row.setKeyboardTracking(False)
    dialog.header_row.setMaximumWidth(px(112))
    dialog.header_row.setToolTip(
        tr(
            "Numer wiersza z nazwami kolumn, liczony od 1. Automatycznie: wyszukaj tabelę w pierwszych 200 wierszach. Dane są odczytywane poniżej nagłówków."
        )
    )
    dialog.header_row_label = label(tr("Wykryty wiersz"))
    dialog.header_row_label.setFixedWidth(px(120))
    header_settings.addWidget(dialog.header_row_label, 1, 0)
    header_settings.addWidget(dialog.header_row, 1, 1, Qt.AlignmentFlag.AlignLeft)
    header_settings.setColumnStretch(1, 1)
    source_layout.addLayout(header_settings)
    source_layout.addSpacing(px(12))
    source_layout.addWidget(label(tr("Ustawienia importu"), "section"))
    settings = QGridLayout()
    settings.setColumnMinimumWidth(0, px(120))
    settings.setHorizontalSpacing(px(12))
    settings.setVerticalSpacing(px(9))
    dialog.encoding = QComboBox()
    for caption, value in (
        ("Automatycznie", "auto"),
        ("UTF-8 (także BOM)", "utf-8-sig"),
        ("Windows-1250", "cp1250"),
        ("ISO-8859-2", "iso-8859-2"),
        ("UTF-16", "utf-16"),
    ):
        dialog.encoding.addItem(tr(caption), value)
    dialog.delimiter = QComboBox()
    for caption, value in (
        ("Automatycznie", "auto"),
        ("Przecinek", ","),
        ("Średnik", ";"),
        ("Tabulator", "\t"),
    ):
        dialog.delimiter.addItem(tr(caption), value)
    dialog.sheet_name = QLineEdit()
    dialog.sheet_name.setPlaceholderText(tr("Pierwszy widoczny"))
    for index, (caption, widget) in enumerate(
        (
            (tr("Kodowanie"), dialog.encoding),
            (tr("Separator"), dialog.delimiter),
            (tr("Arkusz Excel"), dialog.sheet_name),
        )
    ):
        setting_label = label(caption)
        setting_label.setFixedWidth(px(120))
        settings.addWidget(setting_label, index, 0)
        settings.addWidget(widget, index, 1)
    settings.setColumnStretch(1, 1)
    source_layout.addLayout(settings)
    source_layout.addStretch(1)
    source_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    dialog.source_scroll = QScrollArea()
    dialog.source_scroll.setFrameShape(QFrame.Shape.NoFrame)
    dialog.source_scroll.setWidgetResizable(True)
    dialog.source_scroll.setWidget(source)
    dialog.source_scroll.setMinimumWidth(px(260))
    dialog.source_scroll.setMaximumWidth(px(440))
    dialog.splitter.addWidget(dialog.source_scroll)
    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(px(12))
    dialog.review_splitter = QSplitter(Qt.Orientation.Horizontal)
    dialog.review_splitter.setObjectName("importReviewSplitter")
    dialog.review_splitter.setHandleWidth(px(7))
    dialog.review_splitter.setChildrenCollapsible(False)
    mapping, mapping_layout = section()
    mapping.setProperty("importMapping", True)
    mapping_layout.setContentsMargins(px(12), px(8), px(12), px(8))
    mapping_layout.setSpacing(px(6))
    mapping_layout.addWidget(label(tr("Mapowanie kolumn"), "section"))
    grid = QGridLayout()
    grid.setHorizontalSpacing(px(12))
    grid.setVerticalSpacing(px(5))
    grid.setColumnMinimumWidth(0, px(150))
    dialog.fields, dialog.field_labels = {}, {}
    positions = {
        "date": (0, 0),
        "amount": (2, 0),
        "amount_fallback": (4, 0),
        "description": (6, 0),
        "from_to": (8, 0),
        "category": (10, 0),
        "currency": (12, 0),
    }
    glyphs = {
        "date": "calendar",
        "amount": "income",
        "amount_fallback": "income",
        "description": "file",
        "from_to": "business",
        "category": "tag",
        "currency": "cash",
    }
    for key, (row_number, column) in positions.items():
        combo = QComboBox()
        combo.setMinimumContentsLength(6)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setProperty("mappingIcon", glyphs[key])
        combo.addItem(icon(glyphs[key], MUTED), tr("— brak —"), None)
        combo.currentIndexChanged.connect(dialog.invalidate)
        dialog.fields[key] = combo
        caption = tr(IMPORT_FIELDS[key]) + (" *" if key in ("date", "amount") else "")
        field_label = label(caption, "field")
        dialog.field_labels[key] = field_label
        grid.addWidget(field_label, row_number, column)
        grid.addWidget(combo, row_number + 1, column)
    grid.setColumnStretch(0, 1)
    fallback_help = tr(
        "Używana tylko wtedy, gdy główna kwota w danym wierszu jest pusta. Nie zastępuje zera ani błędnej kwoty."
    )
    for key in dialog.fields:
        hint = (
            fallback_help
            if key == "amount_fallback"
            else tr("Pole wymagane")
            if key in ("date", "amount")
            else tr("Pole opcjonalne")
        )
        dialog.fields[key].setToolTip(hint)
        dialog.field_labels[key].setToolTip(hint)
    mapping_layout.addLayout(grid)
    mapping_layout.addStretch(1)
    mapping_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    dialog.mapping_scroll = QScrollArea()
    dialog.mapping_scroll.setFrameShape(QFrame.Shape.NoFrame)
    dialog.mapping_scroll.setWidgetResizable(True)
    dialog.mapping_scroll.setWidget(mapping)
    dialog.mapping_scroll.setMinimumHeight(0)
    dialog.mapping_scroll.setMinimumWidth(px(270))
    dialog.mapping_scroll.setMaximumWidth(px(500))
    dialog.review_splitter.addWidget(dialog.mapping_scroll)
    dialog.review_splitter.setCollapsible(0, True)
    preview_panel, preview_layout = section()
    preview_layout.addWidget(label(tr("Wczytany plik"), "section"))
    raw_page = QWidget()
    raw_layout = QVBoxLayout(raw_page)
    raw_layout.setContentsMargins(0, px(6), 0, 0)
    raw_controls = QHBoxLayout()
    dialog.raw_file = QComboBox()
    dialog.raw_file.setMinimumContentsLength(8)
    dialog.raw_file.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    dialog.raw_file.currentIndexChanged.connect(dialog.raw_file_changed)
    raw_controls.addWidget(dialog.raw_file, 1)
    dialog.raw_position = label("0 / 0")
    raw_controls.addWidget(dialog.raw_position)
    dialog.raw_previous = QPushButton(tr("Poprzednie"))
    dialog.raw_next = QPushButton(tr("Następne"))
    dialog.raw_previous.setToolTip(tr("Poprzednie wiersze"))
    dialog.raw_next.setToolTip(tr("Następne wiersze"))
    dialog.raw_previous.clicked.connect(lambda: dialog.change_raw_page(-1))
    dialog.raw_next.clicked.connect(lambda: dialog.change_raw_page(1))
    raw_controls.addWidget(dialog.raw_previous)
    raw_controls.addWidget(dialog.raw_next)
    raw_layout.addLayout(raw_controls)
    dialog.raw_preview = table([tr("Pomiń"), tr("Wiersz")])
    dialog.raw_preview.setSortingEnabled(False)
    dialog.raw_preview.itemChanged.connect(dialog.exclude_row)
    raw_layout.addWidget(dialog.raw_preview, 1)
    preview_layout.addWidget(raw_page, 1)
    dialog.source_status = label(tr("Wybierz pliki do importu."))
    preview_layout.addWidget(dialog.source_status)
    dialog.splitter.addWidget(preview_panel)
    source_page_layout.addWidget(dialog.splitter, 1)
    dialog.pages.addWidget(source_page)
    dialog.comparison_splitter = QSplitter(Qt.Orientation.Vertical)
    dialog.comparison_splitter.setChildrenCollapsible(False)
    before_panel, before_layout = section()
    before_head = QHBoxLayout()
    before_head.addWidget(label(tr("Dane źródłowe"), "section"))
    dialog.mapping_file = QComboBox()
    dialog.mapping_file.setMinimumContentsLength(10)
    dialog.mapping_file.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    dialog.mapping_file.currentIndexChanged.connect(dialog.raw_file.setCurrentIndex)
    before_head.addWidget(dialog.mapping_file, 1)
    dialog.mapping_position = label("")
    before_head.addWidget(dialog.mapping_position)
    dialog.mapping_previous = QPushButton(tr("Poprzednie"))
    dialog.mapping_next = QPushButton(tr("Następne"))
    dialog.mapping_previous.setToolTip(tr("Poprzednie wiersze"))
    dialog.mapping_next.setToolTip(tr("Następne wiersze"))
    dialog.mapping_previous.clicked.connect(lambda: dialog.change_raw_page(-1))
    dialog.mapping_next.clicked.connect(lambda: dialog.change_raw_page(1))
    before_head.addWidget(dialog.mapping_previous)
    before_head.addWidget(dialog.mapping_next)
    before_layout.addLayout(before_head)
    dialog.mapping_source_preview = QTableView()
    dialog.mapping_source_preview.setModel(dialog.raw_preview.model())
    dialog.mapping_source_preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    dialog.mapping_source_preview.setAlternatingRowColors(True)
    dialog.mapping_source_preview.verticalHeader().hide()
    dialog.mapping_source_preview.verticalHeader().setDefaultSectionSize(px(34))
    before_layout.addWidget(dialog.mapping_source_preview, 1)
    after_panel, after_layout = section()
    after_layout.addWidget(label(tr("Po mapowaniu"), "section"))
    dialog.preview = table([tr("Podgląd po mapowaniu")])
    after_layout.addWidget(dialog.preview, 1)
    dialog.comparison_splitter.addWidget(before_panel)
    dialog.comparison_splitter.addWidget(after_panel)
    dialog.comparison_splitter.setSizes([px(230), px(230)])
    dialog.fallback_note = label(
        tr("Kwota zapasowa jest używana tylko przy pustej kwocie głównej.")
    )
    after_layout.addWidget(dialog.fallback_note)
    dialog.review_splitter.addWidget(dialog.comparison_splitter)
    dialog.review_splitter.setStretchFactor(0, 0)
    dialog.review_splitter.setStretchFactor(1, 1)
    dialog.review_splitter.setSizes([px(330), px(1000)])
    dialog.review_splitter.handle(1).setToolTip(
        tr("Przeciągnij, aby zmienić szerokość mapowania i tabel.")
    )
    right_layout.addWidget(dialog.review_splitter, 1)
    dialog.pages.addWidget(right)
    dialog.splitter.setStretchFactor(0, 0)
    dialog.splitter.setStretchFactor(1, 1)
    dialog.splitter.setSizes([px(370), px(970)])
    notices, notice_layout = section()
    notice_layout.addWidget(label(tr("Błędy i potwierdzenie"), "section"))
    notice_layout.addWidget(
        label(
            tr(
                "Sprawdź pomijane rekordy i planowane zmiany. Zapis nastąpi dopiero po potwierdzeniu."
            )
        )
    )
    notice_row = QHBoxLayout()
    dialog.notice_labels = []
    dialog.notice_icons = []
    for _ in range(1):
        glyph = QLabel()
        glyph.setPixmap(icon("info", MUTED).pixmap(QSize(px(24), px(24))))
        notice_row.addWidget(glyph)
        dialog.notice_icons.append(glyph)
        notice = label("")
        notice.setMinimumWidth(0)
        notice_row.addWidget(notice, 1)
        dialog.notice_labels.append(notice)
    notice_layout.addLayout(notice_row)
    # Keep the validation log separate from the structured review table.
    dialog.details = QPlainTextEdit(notices)
    dialog.details.setReadOnly(True)
    dialog.details.hide()
    dialog.issues_table = QTableView()
    dialog.issues_model = ImportIssuesModel(dialog.issues_table)
    dialog.issues_table.setModel(dialog.issues_model)
    dialog.issues_table.setAlternatingRowColors(True)
    dialog.issues_table.setWordWrap(False)
    dialog.issues_table.verticalHeader().hide()
    dialog.issues_table.verticalHeader().setDefaultSectionSize(px(42))
    issues_header = dialog.issues_table.horizontalHeader()
    issues_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    issues_header.resizeSection(0, px(280))
    issues_header.resizeSection(1, px(80))
    issues_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    notice_layout.addWidget(dialog.issues_table, 1)
    dialog.review_confirmation = QCheckBox(
        tr("Sprawdziłem informacje i akceptuję import poprawnych rekordów.")
    )
    dialog.review_confirmation.toggled.connect(dialog.update_navigation)
    notice_layout.addWidget(dialog.review_confirmation)
    dialog.pages.addWidget(notices)
    footer = QHBoxLayout()
    dialog.back_button = QPushButton(tr("Wstecz"))
    dialog.back_button.clicked.connect(lambda: dialog.go_to_step(max(0, dialog.current_step - 1)))
    footer.addWidget(dialog.back_button)
    dialog.summary = label(tr("Wybierz pliki do importu."))
    dialog.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    footer.addWidget(dialog.summary, 1)
    footer.addSpacing(px(10))
    cancel = QPushButton(tr("Anuluj"))
    cancel.clicked.connect(dialog.reject)
    footer.addWidget(cancel)
    dialog.next_button = QPushButton(tr("Dalej"))
    dialog.next_button.setProperty("role", "primary")
    dialog.next_button.clicked.connect(dialog.advance_step)
    footer.addWidget(dialog.next_button)
    dialog.save_button = QPushButton(tr("Importuj transakcje"))
    dialog.save_button.setProperty("role", "primary")
    dialog.save_button.setIcon(icon("upload", "#062536"))
    dialog.save_button.setEnabled(False)
    dialog.save_button.clicked.connect(dialog.save)
    footer.addWidget(dialog.save_button)
    outer.addLayout(footer)
    apply_workspace_style(dialog)
    dialog.update_import_density()


def apply_workspace_style(dialog):
    style = """
    QDialog#importWorkspace {background:#0b1623;}
    #importWorkspace QWidget {font-size:15px;}
    #importWorkspace QLabel[role="section"] {font-size:18px;font-weight:600;}
    #importWorkspace QFrame#importPanel {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #112233,stop:1 #1a2b3d);border:1px solid #24394d;border-radius:6px;}
    #importWorkspace QFrame#importPanel QLabel {background:transparent;border:0;}
    #importWorkspace QLabel#importTitle {font-size:28px;font-weight:700;color:#edf4ff;}
    #importWorkspace QComboBox,#importWorkspace QLineEdit,#importWorkspace QSpinBox {background:#0b1623;border:1px solid #3d5b74;border-radius:5px;padding:8px;min-height:20px;}
    #importWorkspace QComboBox:focus,#importWorkspace QLineEdit:focus {border-color:#22d3ee;}
    #importWorkspace QSpinBox#importHeaderRow:disabled {background:#24394d;color:#7b8fa6;border-color:#24394d;}
    #importWorkspace QSpinBox#importHeaderRow:disabled QLineEdit {background:#24394d;color:#7b8fa6;border:0;}
    #importFileCard {background:#112233;border:1px solid #3d5b74;border-radius:5px;}
    #importFileCard[selected="true"] {border-color:#22d3ee;}
    #importFileCard QLabel {border:0;background:transparent;}
    #importRemoveFile {border:0;background:transparent;padding:0;}
    #importDropZone {border:0;background:transparent;text-align:center;font-weight:400;}
    #importStep {border:0;background:transparent;color:#a8bed5;padding:4px 7px;font-size:16px;}
    #importStep[active="true"] {color:#22d3ee;font-weight:600;}
    #importStepLine {background:#3d5b74;}
    #importWorkspace QTableWidget,#importWorkspace QTableView {background:#0b1623;alternate-background-color:#112233;border:1px solid #24394d;gridline-color:#24394d;}
    #importWorkspace QHeaderView::section {background:#112233;color:#edf4ff;border:0;border-right:1px solid #24394d;border-bottom:1px solid #24394d;padding:10px 8px;}
    #importWorkspace QFrame[importMapping="true"] QComboBox {padding:4px 7px;min-height:14px;}
    #importReviewSplitter::handle:vertical {background:#24394d;}
    #importReviewSplitter::handle:vertical:hover {background:#22d3ee;}
    #importReviewSplitter::handle:horizontal {background:#24394d;}
    #importReviewSplitter::handle:horizontal:hover {background:#22d3ee;}
    """
    import re

    if dialog.property("compactImport"):
        style += """
        #importWorkspace QComboBox,#importWorkspace QLineEdit,#importWorkspace QSpinBox {padding:5px;min-height:16px;}
        """
    style = re.sub(
        r"font-size:(\d+)px",
        lambda match: f"font-size:{round(px(int(match[1])) * font_scale())}px",
        style,
    )
    dialog.setStyleSheet(re.sub(r"#[0-9a-fA-F]{6}", lambda match: display_color(match[0]), style))
