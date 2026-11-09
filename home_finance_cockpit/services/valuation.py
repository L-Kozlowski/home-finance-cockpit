"""Presentation-only valuation; stored amounts always remain in wallet currency."""

from decimal import ROUND_HALF_UP, Decimal

from home_finance_cockpit.localization import tr


def in_currency_scope(source, target):
    return target == "PLN" or source == target


def converted_minor(db, amount, source, target):
    if source == target:
        return amount
    rate, _ = db.effective_rate(source)
    if rate is None:
        raise ValueError(
            tr("Brak kursu {code}. Uzupełnij przelicznik w ustawieniach walut.", code=source)
        )
    if target != "PLN":
        raise ValueError(tr("Wybierz PLN do łącznej wyceny portfeli."))
    return int((Decimal(amount) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def valued_transaction(db, row, target):
    result = dict(row)
    result["original_currency"] = row["currency"]
    result["original_amount_minor"] = row["amount_minor"]
    result["amount_minor"] = converted_minor(db, row["amount_minor"], row["currency"], target)
    result["currency"] = target
    return result
