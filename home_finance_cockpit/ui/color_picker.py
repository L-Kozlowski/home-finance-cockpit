"""Optional category color with a small built-in palette and custom selection."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QHBoxLayout, QToolButton, QWidget

from home_finance_cockpit.domain.category_colors import PALETTE, validate_color
from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.scaling import px


class ColorPicker(QWidget):
    color_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(px(4))
        self.buttons = {}
        for color, caption in PALETTE:
            button = QToolButton()
            button.setProperty("preserveColors", True)
            button.setToolTip(
                (
                    tr(caption)
                    + (tr(" ({v0})", v0=color) if color else tr(": kolor z palety aplikacji"))
                )
            )
            button.setAccessibleName(tr(caption))
            button.setFixedSize(px(24), px(26))
            button.clicked.connect(lambda checked=False, value=color: self.choose(value))
            layout.addWidget(button)
            self.buttons[color] = button
        self.custom = QToolButton()
        self.custom.setText("…")
        self.custom.setToolTip(tr("Wybierz własny kolor"))
        self.custom.setFixedSize(px(24), px(26))
        self.custom.setStyleSheet("QToolButton {padding:0; border-radius:4px;}")
        self.custom.clicked.connect(self.choose_custom)
        layout.addWidget(self.custom)
        layout.addStretch()
        self.set_value(None)

    def set_value(self, value):
        from home_finance_cockpit.domain.brand_palette import BORDER
        from home_finance_cockpit.ui.theme import INK, SURFACE, TEXT, display_color

        self.value = validate_color(value)
        for color, button in self.buttons.items():
            selected = color == self.value
            border = display_color(TEXT if selected else BORDER)
            button.setText((tr("×") if color is None else ""))
            button.setStyleSheet(
                f"QToolButton {{background:{color or display_color(SURFACE)}; color:{INK if color else display_color(TEXT)};"
                f"border:{2 if selected else 1}px solid {border};padding:0;border-radius:4px;}}"
            )
        self.custom.setToolTip(
            (
                (tr("Własny kolor: ") + self.value)
                if self.value and self.value not in self.buttons
                else tr("Wybierz własny kolor")
            )
        )

    def choose(self, value):
        self.set_value(value)
        self.color_changed.emit(self.value)

    def choose_custom(self):
        from home_finance_cockpit.ui.theme import ACCENT

        color = QColorDialog.getColor(QColor(self.value or ACCENT), self, tr("Kolor kategorii"))
        if color.isValid():
            self.choose(color.name())
