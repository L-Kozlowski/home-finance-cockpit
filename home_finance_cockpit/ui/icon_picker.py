"""Small modal palette of the wallet icons supported by the ledger."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLineEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.domain.wallet_icons import WALLET_ICONS, wallet_icon
from home_finance_cockpit.localization import tr, translate
from home_finance_cockpit.services.search import normalize
from home_finance_cockpit.ui.components import icon, label
from home_finance_cockpit.ui.scaling import px


class WalletIconDialog(QDialog):
    def __init__(self, parent, selected="wallet"):
        super().__init__(parent)
        self.setWindowTitle(tr("Wybierz ikonę portfela"))
        self.selected_icon = wallet_icon(selected)
        layout = QVBoxLayout(self)
        layout.addWidget(label(tr("Wybierz ikonę pasującą do tego portfela.")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj ikon po polsku lub angielsku…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_icons)
        layout.addWidget(self.search)
        self.grid = grid = QGridLayout()
        self.buttons = {}
        for index, (key, title) in enumerate(WALLET_ICONS.items()):
            button = QToolButton()
            button.setText(tr(title))
            button.setIcon(icon(key))
            button.setIconSize(QSize(px(28), px(28)))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setChecked(key == selected)
            button.setMinimumSize(px(120), px(72))
            button.clicked.connect(lambda checked=False, value=key: self.select(value))
            grid.addWidget(button, index // 5, index % 5)
            self.buttons[key] = button
        width = max(button.sizeHint().width() for button in self.buttons.values())
        for button in self.buttons.values():
            button.setFixedWidth(max(px(120), width))
        layout.addLayout(grid)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Wybierz"))
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Anuluj"))
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def select(self, key):
        self.selected_icon = wallet_icon(key)
        for value, button in self.buttons.items():
            button.setChecked(value == key)

    def filter_icons(self, query):
        terms = normalize(query).split()
        visible_index = 0
        for key, button in self.buttons.items():
            title = WALLET_ICONS[key]
            searchable = normalize(" ".join((key, title, translate(title, "en"))))
            visible = all(term in searchable for term in terms)
            self.grid.removeWidget(button)
            button.setVisible(visible)
            if visible:
                self.grid.addWidget(button, visible_index // 5, visible_index % 5)
                visible_index += 1


class CategoryIconDialog(QDialog):
    def __init__(self, parent, selected="tag", color="#22D3EE"):
        super().__init__(parent)
        from home_finance_cockpit.domain.category_icons import CATEGORY_ICONS

        self.setWindowTitle(tr("Wybierz ikonę kategorii"))
        self.selected_icon, self.color = selected, color
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Szukaj ikon po polsku lub angielsku…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter_icons)
        layout.addWidget(self.search)
        self.grid = grid = QGridLayout()
        self.buttons = {}
        for index, (key, title) in enumerate(CATEGORY_ICONS.items()):
            button = QToolButton()
            button.setText(tr(title))
            button.setIcon(icon(key, "#FFFFFF"))
            button.setIconSize(QSize(28, 28))
            button.setMinimumSize(110, 70)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, key=key: self.select(key))
            grid.addWidget(button, index // 4, index % 4)
            self.buttons[key] = button
        width = max(button.sizeHint().width() for button in self.buttons.values())
        for button in self.buttons.values():
            button.setFixedSize(max(px(130), width), px(76))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumSize(490, 350)
        content = QWidget()
        content.setLayout(grid)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.preview = QToolButton()
        self.preview.setIconSize(QSize(40, 40))
        self.preview.setMinimumHeight(60)
        self.preview.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout.addWidget(self.preview)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self.select(selected)

    def filter_icons(self, query):
        from home_finance_cockpit.domain.category_icons import CATEGORY_ICONS

        terms = normalize(query).split()
        visible_index = 0
        for key, button in self.buttons.items():
            title = CATEGORY_ICONS[key]
            searchable = normalize(" ".join((key, title, translate(title, "en"))))
            visible = all(term in searchable for term in terms)
            self.grid.removeWidget(button)
            button.setVisible(visible)
            if visible:
                self.grid.addWidget(button, visible_index // 4, visible_index % 4)
                visible_index += 1

    def select(self, key):
        from home_finance_cockpit.domain.category_icons import CATEGORY_ICONS, category_icon

        self.selected_icon = category_icon(key)
        for name, button in self.buttons.items():
            button.setChecked(name == key)
        self.preview.setText(tr(CATEGORY_ICONS[key]))
        self.preview.setIcon(icon(key, self.color))
