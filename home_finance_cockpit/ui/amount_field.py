"""Currency suffix inside an editable money field; text remains numeric."""

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QLabel

from home_finance_cockpit.ui.theme import display_color


class CurrencySuffix(QObject):
    def __init__(self, field):
        super().__init__(field)
        self.field = field
        self.label = QLabel(field)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        field.installEventFilter(self)
        self.set_currency("")

    def set_currency(self, currency):
        self.label.setText(currency or "")
        self.label.setStyleSheet(
            "QLabel {background:"
            + display_color("#1A2B3D")
            + "; color:"
            + display_color("#A8BED5")
            + "; border:0; border-left:1px solid "
            + display_color("#24394D")
            + "; border-top-right-radius:5px; border-bottom-right-radius:5px; padding:0;}"
        )
        self.position()

    def position(self):
        width = (
            max(48, self.label.fontMetrics().horizontalAdvance(self.label.text()) + 24)
            if self.label.text()
            else 0
        )
        self.field.setTextMargins(0, 0, width, 0)
        self.label.setGeometry(
            max(1, self.field.width() - width - 1), 1, width, max(0, self.field.height() - 2)
        )
        self.label.setVisible(bool(width))
        self.label.raise_()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange, QEvent.Type.Show):
            self.position()
        return False
