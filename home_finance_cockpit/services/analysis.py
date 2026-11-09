"""One set of definitions for all dashboard totals and charts."""

from collections import defaultdict

from home_finance_cockpit.domain.validation import date_range
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.valuation import converted_minor, in_currency_scope


def summarize(
    db, wallet_id=None, start=None, end=None, currency=None, *, category_ids=None, wallet_ids=None
):
    start, end = date_range(start, end)
    wallets = [dict(w) for w in db.wallets() if wallet_id is None or w["id"] == wallet_id]
    if wallet_ids is not None:
        wallets = [wallet for wallet in wallets if wallet["id"] in wallet_ids]
    if currency:
        wallets = [w for w in wallets if in_currency_scope(w["currency"], currency)]
    codes = {w["currency"] for w in wallets}
    if len(codes) > 1 and currency != "PLN":
        raise ValueError(tr("Wybierz jedną walutę do analizy."))
    result = dict(
        currency=currency or next(iter(codes), "PLN"),
        income=0,
        expense=0,
        net=0,
        balance=0,
        wallets=[],
        categories=[],
        trend=[],
        balance_trend=[],
        count=0,
    )
    categories, daily = defaultdict(int), defaultdict(lambda: [0, 0])
    balance_events = defaultdict(int)
    for wallet in wallets:
        opening = converted_minor(
            db, wallet["opening_minor"], wallet["currency"], result["currency"]
        )
        balance = opening if not end or wallet["opening_date"] <= end else 0
        if not end or wallet["opening_date"] <= end:
            balance_events[wallet["opening_date"]] += opening
        for tx in db.transactions(wallet["id"]):
            amount = converted_minor(db, tx["amount_minor"], wallet["currency"], result["currency"])
            if not end or tx["date"] <= end:
                balance += amount
                balance_events[tx["date"]] += amount
            if (start and tx["date"] < start) or (end and tx["date"] > end):
                continue
            if (
                category_ids
                and tx["category_id"] not in category_ids
                and tx["root_category_id"] not in category_ids
            ):
                continue
            result["count"] += 1
            if amount > 0:
                result["income"] += amount
                daily[tx["date"]][0] += amount
            else:
                result["expense"] -= amount
                daily[tx["date"]][1] -= amount
                categories[tx["category"]] -= amount
        result["wallets"].append(
            dict(name=wallet["name"], balance=balance, currency=result["currency"])
        )
        result["balance"] += balance
    result["net"] = result["income"] - result["expense"]
    result["categories"] = sorted(categories.items(), key=lambda item: (-item[1], item[0]))
    result["trend"] = [(day, *daily[day]) for day in sorted(daily)]
    running = sum(value for day, value in balance_events.items() if start and day < start)
    history = {start: running} if start else {}
    for day in sorted(balance_events):
        if start and day < start:
            continue
        running += balance_events[day]
        history[day] = running
    if end:
        history[end] = running
    result["balance_trend"] = sorted(history.items())
    return result


def balances_by_currency(db):
    return group_wallet_balances(db.wallet_balances())


def group_wallet_balances(wallets):
    """Sum the exact wallet balances shown in the UI, including negative amounts."""
    grouped = {}
    for wallet in wallets:
        code = wallet["currency"]
        group = grouped.setdefault(code, dict(currency=code, balance=0, wallets=[]))
        group["wallets"].append(dict(wallet))
        group["balance"] += wallet["balance"]
    return dict(sorted(grouped.items()))
