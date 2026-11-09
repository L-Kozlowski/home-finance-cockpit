"""Shared date presentation for embedded, enlarged and exported charts."""

import re
from datetime import date, datetime

from matplotlib.dates import AutoDateLocator, DateFormatter
from matplotlib.ticker import FuncFormatter

from home_finance_cockpit.localization import tr

DATE_FORMATS = ("dd.MM.yyyy", "yyyy-MM-dd", "dd/MM/yyyy")
_date_format = DATE_FORMATS[0]


def get_date_format():
    """Return the Qt display format without exposing mutable module state."""
    return _date_format


def set_date_format(value):
    global _date_format
    if value not in DATE_FORMATS:
        raise ValueError(tr("Nieprawidłowy format daty"))
    _date_format = value


def format_date(value):
    try:
        day = date.fromisoformat(value + "-01" if len(value) == 7 else value)
    except (ValueError, TypeError):
        return value
    if len(value) == 7:
        return day.strftime(
            "%Y-%m"
            if _date_format == "yyyy-MM-dd"
            else "%m.%Y"
            if _date_format == "dd.MM.yyyy"
            else "%m/%Y"
        )
    return day.strftime(_date_format.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d"))


def format_timestamp(value):
    try:
        stamp = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return str(value).replace("T", " ")
    return format_date(stamp.date().isoformat()) + stamp.strftime(" %H:%M:%S")


def format_chart_dates(figure):
    for ax in figure.axes:
        texts = [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]
        if ax.get_legend() is not None:
            texts.extend(ax.get_legend().get_texts())
        for text in texts:
            source = getattr(text, "_date_source", text.get_text())
            if re.search(r"\b\d{4}-\d{2}(?:-\d{2})?\b", source):
                text._date_source = source
                text.set_text(
                    re.sub(
                        r"\b\d{4}-\d{2}(?:-\d{2})?\b",
                        lambda match: format_date(match.group()),
                        source,
                    )
                )
        converter = ax.xaxis.get_converter()
        if converter is not None and "date" in type(converter).__name__.lower():
            locator = AutoDateLocator(minticks=2, maxticks=max(4, min(8, int(ax.bbox.width / 100))))
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(
                DateFormatter(
                    _date_format.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d")
                )
            )
        else:
            mapping = getattr(ax.xaxis.units, "_mapping", {})
            if hasattr(ax, "_date_ticks"):
                mapping = {month: i for i, month in enumerate(ax._date_ticks)}
            dates = {
                v: format_date(k)
                for k, v in mapping.items()
                if isinstance(k, str) and len(k) in (7, 10) and k[:4].isdigit() and k[4:5] == "-"
            }
            if dates:
                ax.xaxis.set_major_formatter(
                    FuncFormatter(lambda value, _position, dates=dates: dates.get(value, ""))
                )
        labels = [t for t in ax.get_xticklabels() if t.get_visible() and t.get_text()]
        # Keep labels horizontal unless their estimated width exceeds tick spacing.
        spacing = ax.bbox.width / max(1, len(labels))
        crowded = any(
            len(t.get_text()) * t.get_fontsize() * figure.dpi / 72 * 0.52 > spacing for t in labels
        )
        for tick in labels:
            tick.set_rotation(30 if crowded else 0)
            tick.set_ha("right" if crowded else "center")
