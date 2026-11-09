"""Render notebook-style PNGs without a Qt canvas or global pyplot state."""

from calendar import monthrange
from datetime import date
from math import nan

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from home_finance_cockpit.domain import brand_palette as brand
from home_finance_cockpit.domain.validation import amount_label
from home_finance_cockpit.localization import tr
from home_finance_cockpit.reports.presentation import category_color, label


def _figure(width=9, height=5):
    figure = Figure(figsize=(width, height), layout="constrained")
    FigureCanvasAgg(figure)
    return figure


def _save(figure, path):
    from home_finance_cockpit.ui.chart_dates import format_chart_dates

    format_chart_dates(figure)
    figure.patch.set_facecolor(brand.SURFACE)
    for ax in figure.axes:
        ax.set_facecolor(brand.SURFACE)
        ax.tick_params(colors=brand.MUTED)
        for spine in ax.spines.values():
            spine.set_color(brand.BORDER)
        for text in (ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts):
            text.set_color(brand.TEXT)
        legend = ax.get_legend()
        if legend:
            legend.get_frame().set_facecolor(brand.PANEL)
            legend.get_frame().set_edgecolor(brand.BORDER)
            for text in legend.get_texts():
                text.set_color(brand.TEXT)
    figure.savefig(path, dpi=160, facecolor=brand.SURFACE)
    figure.clear()
    return path


def monthly_charts(summary, currency, folder):
    month = summary["month"]
    values = sorted(summary["categories"].items(), key=lambda item: (item[1], item[0]))
    figure = _figure()
    ax = figure.add_subplot(111)
    if values:
        ax.barh(
            [label(c) for c, _ in values],
            [v / 100 for _, v in values],
            color=[category_color(c, summary.get("category_colors")) for c, _ in values],
        )
    else:
        ax.text(0.5, 0.5, tr("No expenses recorded"), ha="center", transform=ax.transAxes)
    ax.set(title=tr("Spending by category — {v0}", v0=month), xlabel=currency)
    ax.grid(axis="x", alpha=0.2)
    categories = _save(figure, folder / f"{month}_categories.png")
    figure = _figure(height=6)
    year, number = map(int, month.split("-"))
    days = [date(year, number, i) for i in range(1, monthrange(year, number)[1] + 1)]
    daily = [summary["daily"].get(day.isoformat(), 0) for day in days]
    cumulative, running = [], 0
    for value in daily:
        running += value
        cumulative.append(running / 100)
    axes = figure.subplots(2, 1, sharex=True)
    axes[0].bar(days, [v / 100 for v in daily], color=brand.ACCENT)
    axes[0].set(title=tr("Daily spending — {v0}", v0=month), ylabel=currency)
    axes[1].plot(days, cumulative, color=brand.ACCENT)
    axes[1].set(ylabel=tr("Cumulative ({v0})", v0=currency), xlabel=tr("Date"))
    for tick in axes[1].get_xticklabels():
        tick.set_rotation(25)
    daily_path = _save(figure, folder / f"{month}_daily.png")
    figure = _figure(height=6)
    ax = figure.add_subplot(111)
    if values and all(v >= 0 for _, v in values) and sum(v for _, v in values) > 0:
        wedges, *_ = ax.pie(
            [v for _, v in values],
            autopct="%1.1f%%",
            startangle=90,
            colors=[category_color(c, summary.get("category_colors")) for c, _ in values],
        )
        ax.legend(
            wedges,
            [f"{label(c)} ({amount_label(v, currency)})" for c, v in values],
            loc="center left",
            bbox_to_anchor=(1, 0.5),
            fontsize=8,
        )
    elif values:
        ax.barh(
            [label(c) for c, v in values],
            [v / 100 for c, v in values],
            color=[category_color(c, summary.get("category_colors")) for c, v in values],
        )
        ax.axvline(0, color="grey", lw=0.7)
        ax.set_xlabel(tr("Signed costs after refunds (shares unavailable)"))
    else:
        ax.text(0.5, 0.5, tr("No expenses recorded"), ha="center", transform=ax.transAxes)
    ax.set_title(tr("Share of spending by category — {v0}", v0=month))
    pie = _save(figure, folder / f"{month}_pie.png")
    return categories, daily_path, pie


def annual_charts(data, year, currency, folder):
    months = [m for m in data["annual_months"] if m.startswith(year)]
    calendar = [f"{year}-{i:02d}" for i in range(int(months[0][-2:]), int(months[-1][-2:]) + 1)]
    figure = _figure()
    ax = figure.add_subplot(111)
    for key, title, color in (
        ("inflows", "Inflows", brand.SUCCESS),
        ("expenses", "Expenses", brand.ERROR),
        ("net", "Net flow", brand.INFO),
    ):
        ax.plot(
            calendar,
            [data["summaries"][m][key] / 100 if m in months else nan for m in calendar],
            marker="o",
            color=color,
            label=tr(title),
        )
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set(
        title=tr("Inflows, expenses and net flow — {v0}", v0=year),
        ylabel=currency,
        xlabel=tr("Month"),
    )
    ax.tick_params(axis="x", rotation=30)
    ax.grid(alpha=0.25)
    ax.legend()
    trend = _save(figure, folder / f"{year}_trend.png")
    figure = _figure()
    ax = figure.add_subplot(111)
    names = sorted(
        {c for m in months for c in data["summaries"][m]["categories"]},
        key=lambda c: label(c).casefold(),
    )
    bottoms = [0] * len(months)
    negatives = [0] * len(months)
    for name in names:
        values = [data["summaries"][m]["categories"].get(name, 0) / 100 for m in months]
        ax.bar(
            months,
            values,
            bottom=[p if v >= 0 else n for p, n, v in zip(bottoms, negatives, values)],
            label=label(name),
            color=category_color(name, data.get("category_colors")),
        )
        bottoms = [a + max(0, b) for a, b in zip(bottoms, values)]
        negatives = [a + min(0, b) for a, b in zip(negatives, values)]
    if names:
        ax.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
    else:
        ax.text(0.5, 0.5, tr("No expenses recorded"), ha="center", transform=ax.transAxes)
    ax.set(
        title=tr("Monthly spending composition — {v0}", v0=year),
        ylabel=currency,
        xlabel=tr("Month"),
    )
    ax.tick_params(axis="x", rotation=30)
    composition = _save(figure, folder / f"{year}_categories.png")
    return trend, composition
