"""Signed money bounds shared by the filter dialog and analytical views."""

from home_finance_cockpit.domain.validation import money_minor
from home_finance_cockpit.localization import tr


def amount_range(first, last):
    low = money_minor(first) if first.strip() else None
    high = money_minor(last) if last.strip() else None
    if low is not None and high is not None and low > high:
        raise ValueError(tr("Wartość od nie może być większa niż do."))
    return low, high
