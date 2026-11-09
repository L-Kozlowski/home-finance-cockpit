"""Desktop workspace navigation around the existing functional pages."""

from pathlib import Path

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.branding import BrandLogo
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import ACCENT, INK, display_color

PAGES = (
    ("Przegląd", "overview", "Przegląd", ""),
    (
        "Transakcje",
        "transactions",
        "Transakcje",
        "Wszystkie źródła w jednym miejscu. Szukaj, sprawdzaj i porządkuj.",
    ),
    ("Portfele", "wallet", "Portfele", ""),
    (
        "Importy",
        "import",
        "Historia importów",
        "Kontroluj źródła swoich transakcji i zarządzaj importami.",
    ),
    ("Analizy", "chart", "Analizy", ""),
    (
        "Kategorie i reguły",
        "tag",
        "Kategorie i reguły",
        "Porządkuj transakcje, kolory kategorii i reguły automatycznego przypisywania.",
    ),
    ("Generuj raport", "report", "Generowanie raportów", ""),
    ("Cele oszczędnościowe", "target", "Cele oszczędnościowe", ""),
)


class DatabaseButton(QPushButton):
    def setMenu(self, menu):
        # Keep Qt's default below-button popup from overriding our position.
        self._database_menu = menu

    def menu(self):
        return getattr(self, "_database_menu", None)

    def popup_database_menu(self):
        if self.menu() is not None:
            self.menu().popup(self.mapToGlobal(QPoint(self.width() + px(6), 0)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.popup_database_menu()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self.popup_database_menu()
            event.accept()
        else:
            super().keyPressEvent(event)


class WorkspaceShell(QWidget):
    def __init__(
        self,
        pages,
        db_path,
        *,
        import_csv,
        add_transaction,
        settings,
        add_wallet=None,
        add_goal=None,
        report=None,
        database_menu=None,
        undo=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("appShell")
        self.pages = pages
        self.add_transaction, self.add_wallet = add_transaction, add_wallet
        self.add_goal = add_goal
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        from home_finance_cockpit.ui.theme import font_scale

        self.sidebar.setFixedWidth(px(round(205 * max(1.0, font_scale()))))
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(px(12), px(18), px(12), px(12))
        side.setSpacing(px(6))
        brand = BrandLogo(height=54)
        side.addWidget(brand)
        side.addSpacing(px(20))
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, (title, glyph, _, _) in enumerate(PAGES):
            button = self.navigation_button(title, glyph)
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            button.clicked.connect(lambda checked=False, i=index: pages.setCurrentIndex(i))
            side.addWidget(button)
            self.nav_buttons.append(button)
        self.report_button = self.nav_buttons[6]
        side.addStretch()
        self.undo_button = self.navigation_button("Cofnij usunięcie", "undo")
        self.undo_button.setToolTip(tr("Cofnij ostatnie usunięcie w bieżącej sesji · Ctrl+Z"))
        if undo is not None:
            self.undo_button.clicked.connect(undo)
        side.addWidget(self.undo_button)
        self.settings_button = self.navigation_button("Ustawienia", "settings")
        self.settings_button.clicked.connect(settings)
        name = tr("Baza w pamięci") if str(db_path) == ":memory:" else Path(db_path).name
        self.database_button = DatabaseButton()
        self.database_button.clicked.connect(self.database_button.popup_database_menu)
        self.database_button.setAccessibleName((tr("Aktywna baza danych: ") + name))
        self.database_button.setObjectName("activeDatabase")
        self.database_button.setStyleSheet(
            f"QPushButton#activeDatabase {{ text-align: left; background: transparent; border: 1px solid transparent; border-top-color: {display_color('#24394D')}; border-radius: 5px; padding: {px(10)}px {px(14)}px; }} QPushButton#activeDatabase:hover, QPushButton#activeDatabase:focus {{ background: {display_color('#15475B')}; border-color: {display_color(ACCENT)}; }} QPushButton#activeDatabase:pressed {{ background: {display_color('#1E3347')}; border-color: {display_color(ACCENT)}; }} QPushButton#activeDatabase::menu-indicator {{ image: none; width: 0px; }}"
        )
        self.database_button.setToolTip(str(db_path))
        self.database_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.database_button.setMinimumWidth(0)
        self.database_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        database_layout = QHBoxLayout(self.database_button)
        database_layout.setContentsMargins(px(14) + 1, px(10), px(10), px(10))
        database_icon = QLabel()
        database_icon.setPixmap(icon("database", ACCENT).pixmap(px(24), px(24)))
        database_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        database_layout.addWidget(database_icon)
        database_text = QVBoxLayout()
        database_text.setSpacing(px(3))
        caption = label(tr("Aktywna baza danych"), "muted")
        caption_font = caption.font()
        caption_font.setPointSizeF(max(8, caption_font.pointSizeF() - 1))
        caption.setFont(caption_font)
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        database_text.addWidget(caption)
        database_label = QLabel(name)
        name_font = database_label.font()
        name_font.setBold(True)
        database_label.setFont(name_font)
        database_label.setTextFormat(Qt.TextFormat.PlainText)
        database_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        database_label.setWordWrap(True)
        database_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        database_text.addWidget(database_label)
        database_layout.addLayout(database_text, 1)
        if database_menu is not None:
            self.database_button.setMenu(database_menu)
        side.addWidget(self.database_button)
        side.addSpacing(px(8))
        side.addWidget(self.settings_button)
        root.addWidget(self.sidebar)
        main = QWidget()
        main.setObjectName("page")
        content = QVBoxLayout(main)
        content.setContentsMargins(px(22), px(14), px(22), px(10))
        content.setSpacing(px(10))
        header = QHBoxLayout()
        self.header_layout = header
        self.back_button = QPushButton()
        self.forward_button = QPushButton()
        for button, glyph, caption in (
            (self.back_button, "back", "Wstecz"),
            (self.forward_button, "forward", "Dalej"),
        ):
            button.setIcon(icon(glyph))
            button.setProperty("themeIcon", glyph)
            button.setFixedSize(px(38), px(38))
            button.setToolTip(tr(caption))
            button.setAccessibleName(tr(caption))
            button.setEnabled(False)
            header.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addSpacing(px(8))
        heading = QVBoxLayout()
        heading.setSpacing(px(5))
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.subtitle = label("")
        heading.addWidget(self.title)
        self.subtitle.hide()
        header.addLayout(heading, 1)
        self.import_button = QPushButton(tr("Importuj pliki"))
        self.import_button.setToolTip(tr("Import CSV / Excel — wiele plików lub przeciąganie"))
        self.import_button.setProperty("themeIcon", "import")
        self.import_button.setIcon(icon("import", ACCENT))
        self.import_button.clicked.connect(import_csv)
        header.addWidget(self.import_button, 0, Qt.AlignmentFlag.AlignTop)
        self.add_button = QPushButton(tr("Transakcja"))
        self.add_button.setProperty("role", "primary")
        self.add_button.setProperty("themeIcon", "plus")
        self.add_button.setIcon(icon("plus", INK))
        self.add_button.clicked.connect(self.add_current)
        header.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(header)
        pages.tabBar().hide()
        content.addWidget(pages, 1)
        root.addWidget(main, 1)
        pages.currentChanged.connect(self.update_page)
        self.update_page(pages.currentIndex())

    def navigation_button(self, title, glyph):
        button = QPushButton(tr(title))
        button.setProperty("role", "nav")
        button.setProperty("navGlyph", glyph)
        button.setIcon(icon(glyph, ACCENT))
        button.setIconSize(QSize(px(22), px(22)))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def add_current(self):
        if self.pages.currentIndex() == 2 and self.add_wallet is not None:
            self.add_wallet()
        elif self.pages.currentIndex() == 7 and self.add_goal is not None:
            self.add_goal()
        else:
            self.add_transaction()

    def update_page(self, index):
        if 0 <= index < len(PAGES):
            _, _, title, subtitle = PAGES[index]
            self.title.setText(tr(title))
            self.subtitle.setText(tr(subtitle))
            self.nav_buttons[index].setChecked(True)
            self.import_button.setVisible(index in (0, 3))
            self.import_button.setProperty("role", "primary" if index == 3 else "")
            self.import_button.setProperty("themeIcon", "upload" if index == 3 else "import")
            self.import_button.setIcon(
                icon("upload" if index == 3 else "import", INK if index == 3 else ACCENT)
            )
            self.import_button.style().unpolish(self.import_button)
            self.import_button.style().polish(self.import_button)
            self.add_button.setVisible(index in (1, 2, 7))
            self.add_button.setText(
                tr("Dodaj cel")
                if index == 7
                else tr("Dodaj portfel")
                if index == 2
                else tr("Transakcja")
            )
            for button in getattr(self, "category_actions", []):
                button.setVisible(index == 5)
            for button in getattr(self, "analysis_actions", []):
                button.setVisible(index == 4 and not button.property("hideForRates"))

    def set_analysis_actions(self, page):
        self.analysis_actions = []
        self.update_page(self.pages.currentIndex())

    def set_category_actions(self, page):
        self.category_actions = [page.export_button, page.import_button, page.apply_button]
        for button in self.category_actions:
            page.toolbar.removeWidget(button)
            self.header_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.update_page(self.pages.currentIndex())
