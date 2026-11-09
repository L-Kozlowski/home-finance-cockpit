"""Shared colors and empty states for the current analytics views."""

from home_finance_cockpit.localization import tr
from home_finance_cockpit.reports.presentation import category_color


def category_chart_color(data, category_id):
    names = data["category_names"]
    colors = {names.get(identifier): color for identifier, color in data["category_colors"].items()}
    return category_color(names.get(category_id, "Bez kategorii"), colors)


def show_empty_chart(axes, message="Brak danych w wybranym zakresie"):
    axes.text(0.5, 0.5, tr(message), ha="center", va="center", wrap=True, transform=axes.transAxes)
    axes.set_xticks([])
    axes.set_yticks([])
