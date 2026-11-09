"""Low-opacity theme glow for calendar numbers and money values."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from home_finance_cockpit.ui.scaling import px
from home_finance_cockpit.ui.theme import ACCENT, display_color


def paint_halo(painter, rect, alignment, text):
    painter.save()
    glow = QColor(display_color(ACCENT))
    glow.setAlpha(26)
    painter.setPen(glow)
    for x, y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        painter.drawText(rect.translated(x, y), alignment, text)
    painter.restore()


class MoneyGlowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        header = str(
            index.model().headerData(index.column(), Qt.Orientation.Horizontal) or ""
        ).casefold()
        text = str(index.data() or "")
        if not any(word in header for word in ("kwota", "saldo", "amount", "balance")) or not any(
            c.isdigit() for c in text
        ):
            return super().paint(painter, option, index)
        adjusted = QStyleOptionViewItem(option)
        self.initStyleOption(adjusted, index)
        adjusted.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, adjusted, painter, option.widget)
        rect = option.rect.adjusted(px(8), 0, -px(8), 0)
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(adjusted.font)
        alignment = int(adjusted.displayAlignment)
        paint_halo(painter, rect, alignment, text)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        painter.setPen(
            foreground.color() if foreground is not None else adjusted.palette.text().color()
        )
        painter.drawText(rect, alignment, text)
        painter.restore()
