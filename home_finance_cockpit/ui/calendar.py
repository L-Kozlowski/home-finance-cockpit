"""Calendar with muted days outside the displayed month."""

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QTextCharFormat
from PyQt6.QtWidgets import QCalendarWidget, QToolButton

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.components import icon
from home_finance_cockpit.ui.text_halo import paint_halo
from home_finance_cockpit.ui.theme import display_color


class MonthCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dimmed_dates = []
        self.currentPageChanged.connect(self.update_month_formats)
        self.update_month_formats(self.yearShown(), self.monthShown())
        for name, glyph, text in (
            ("qt_calendar_prevmonth", "back", tr("Poprzedni")),
            ("qt_calendar_nextmonth", "forward", tr("Następny")),
        ):
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setIcon(icon(glyph))
                button.setProperty("themeIcon", glyph)
                button.setToolTip(text)
                button.setAccessibleName(text)

    def update_month_formats(self, year, month):
        for date in self.dimmed_dates:
            self.setDateTextFormat(date, QTextCharFormat())
        self.dimmed_dates = []
        first = QDate(year, month, 1)
        muted = QTextCharFormat()
        muted.setForeground(QColor(display_color("#526273")))
        for offset in range(-7, first.daysInMonth() + 14):
            date = first.addDays(offset)
            if date.month() != month or date.year() != year:
                self.setDateTextFormat(date, muted)
                self.dimmed_dates.append(date)

    def paintCell(self, painter, rect, date):
        if date.month() != self.monthShown() or date.year() != self.yearShown():
            painter.save()
            painter.fillRect(rect, self.palette().window())
            painter.setFont(self.font())
            painter.setPen(QColor(display_color("#526273")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(date.day()))
            painter.restore()
            return
        super().paintCell(painter, rect, date)
        painter.save()
        painter.setFont(self.font())
        paint_halo(painter, rect, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        brush = self.weekdayTextFormat(Qt.DayOfWeek(date.dayOfWeek())).foreground()
        color = (
            brush.color()
            if brush.style() != Qt.BrushStyle.NoBrush
            else self.palette().text().color()
        )
        if date == self.selectedDate():
            color = self.palette().highlightedText().color()
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(date.day()))
        painter.restore()
