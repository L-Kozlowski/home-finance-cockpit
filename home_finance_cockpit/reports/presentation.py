"""Stable colors and notebook-compatible English presentation labels."""

LABELS = {
    "FreeTime": "Leisure",
    "Mandatory": "Essential expenses",
    "Occasional": "Shopping",
    "AccountFunding": "Account funding",
    "TopUp": "Account top-up",
    "BarAndFood": "Dining out",
    "OnlineShopping": "Retail purchases",
    "Grocery": "Groceries",
    "Car": "Car expenses",
}


def label(value):
    return LABELS.get(value, value)


def category_color(name, overrides=None):
    from home_finance_cockpit.domain.chart_palettes import automatic_category_color

    return (overrides or {}).get(name) or automatic_category_color(name)
