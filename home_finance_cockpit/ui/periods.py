"""The same period presets for overview and transaction filters."""

from PyQt6.QtCore import QDate

from home_finance_cockpit.domain.validation import date_range

PERIOD_PRESETS = (
    ("Wszystko", "all"),
    ("Dzisiaj", "today"),
    ("Wczoraj", "yesterday"),
    ("Ten tydzień", "this_week"),
    ("Poprzedni tydzień", "last_week"),
    ("Ten miesiąc", "this_month"),
    ("Poprzedni miesiąc", "last_month"),
    ("Ten rok", "this_year"),
    ("Poprzedni rok", "last_year"),
    ("Zakres dat", "custom"),
)


def period_range(preset, first, last):
    today = QDate.currentDate()
    if preset == "all":
        return None, None
    if preset == "custom":
        return date_range(first.toString("yyyy-MM-dd"), last.toString("yyyy-MM-dd"))
    start = end = today
    if preset == "yesterday":
        start = end = today.addDays(-1)
    elif preset == "this_week":
        start = today.addDays(1 - today.dayOfWeek())
    elif preset == "last_week":
        end = today.addDays(-today.dayOfWeek())
        start = end.addDays(-6)
    elif preset == "this_month":
        start = QDate(today.year(), today.month(), 1)
    elif preset == "last_month":
        end = QDate(today.year(), today.month(), 1).addDays(-1)
        start = QDate(end.year(), end.month(), 1)
    elif preset == "this_year":
        start = QDate(today.year(), 1, 1)
    elif preset == "last_year":
        start, end = QDate(today.year() - 1, 1, 1), QDate(today.year() - 1, 12, 31)
    return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")
