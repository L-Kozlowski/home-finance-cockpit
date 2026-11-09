"""Exact expense/refund contributions shared by the analytical views."""

from collections import defaultdict
from datetime import date

from home_finance_cockpit.domain.analysis_kinds import REFUND_KINDS, cost_contribution
from home_finance_cockpit.domain.categories import category_name
from home_finance_cockpit.domain.validation import currency_code
from home_finance_cockpit.localization import tr
from home_finance_cockpit.reports.data import excluded_reason, previous_month, source_fields
from home_finance_cockpit.services.valuation import in_currency_scope, valued_transaction


def spending_snapshot(
    db,
    currency,
    wallet_id=None,
    year=None,
    month=None,
    *,
    after_refunds=True,
    omit_salary=True,
    exclude=True,
    category_ids=None,
    start=None,
    end=None,
    amount_min=None,
    amount_max=None,
):
    currency_code(currency)
    with db.transaction():
        categories = {r["id"]: dict(r) for r in db.categories()}
        rows = [
            valued_transaction(db, r, currency)
            for r in db.transactions(wallet_id)
            if in_currency_scope(r["currency"], currency)
        ]
        if category_ids:
            rows = [
                r
                for r in rows
                if r["category_id"] in category_ids or r["root_category_id"] in category_ids
            ]
    from home_finance_cockpit.domain.validation import date_range

    start, end = date_range(start, end)
    rows = [
        r
        for r in rows
        if (start is None or r["date"] >= start)
        and (end is None or r["date"] <= end)
        and (amount_min is None or r["amount_minor"] >= amount_min)
        and (amount_max is None or r["amount_minor"] <= amount_max)
    ]
    valid, excluded = [], []
    for row in rows:
        kind = row.get("analysis_kind", "standard")
        reason = (
            not row["include_in_reports"]
            or kind == "transfer"
            or (omit_salary and kind == "salary")
            or (exclude and excluded_reason(source_fields(row)))
        )
        (excluded if reason else valid).append(row)

    def selected(row):
        return (year is None or int(row["date"][:4]) == year) and (
            month is None or row["date"][:7] == month
        )

    selected_rows = [r for r in valid if selected(r)]
    names = {r["id"]: category_name(r) for r in categories.values() if r["parent_id"] is None}
    names[None] = tr("Zwroty do przypisania")
    colors = {r["id"]: r["color"] for r in categories.values() if r["parent_id"] is None}

    def bucket(values):
        result = dict(
            gross=0,
            refunds=0,
            cost=0,
            inflows=0,
            count=len(values),
            categories=defaultdict(int),
            gross_categories=defaultdict(int),
            refund_categories=defaultdict(int),
            children=defaultdict(int),
            daily=defaultdict(int),
            daily_gross=defaultdict(int),
            daily_refunds=defaultdict(int),
            merchants=defaultdict(int),
            merchant_count=defaultdict(int),
            kinds=defaultdict(int),
            weekday=[0] * 7,
            rows=values,
            contributions=[],
        )
        for row in values:
            amount, kind, day = (
                row["amount_minor"],
                row.get("analysis_kind", "standard"),
                row["date"],
            )
            root = row["root_category_id"]
            contribution = cost_contribution(amount, kind, after_refunds)
            if amount < 0:
                result["gross"] -= amount
                result["gross_categories"][root] -= amount
                result["daily_gross"][day] -= amount
                receiver = row["from_to"].strip() or row["description"].strip() or tr("Brak opisu")
                result["merchant_count"][receiver] += 1
            else:
                result["inflows"] += amount
                result["kinds"][kind] += amount
                receiver = row["from_to"].strip() or row["description"].strip() or tr("Brak opisu")
                if kind in REFUND_KINDS:
                    root = None if row["is_uncategorized"] else root
                    result["refunds"] += amount
                    result["refund_categories"][root] += amount
                    result["daily_refunds"][day] += amount
            if contribution:
                result["categories"][root] += contribution
                child = row["subcategory"] or (
                    tr("Zwroty do przypisania") if root is None else tr("Bez podkategorii")
                )
                result["children"][(root, child)] += contribution
                result["daily"][day] += contribution
                result["weekday"][date.fromisoformat(day).weekday()] += contribution
                result["merchants"][receiver] += contribution
                result["contributions"].append(
                    dict(row=row, root=root, merchant=receiver, value=contribution)
                )
        result["cost"] = result["gross"] - (result["refunds"] if after_refunds else 0)
        for key in ("categories", "children", "daily", "merchants"):
            if sum(result[key].values()) != result["cost"]:
                raise ValueError(tr("Niezgodne sumy kosztów i zwrotów."))
        return result

    grouped = defaultdict(list)
    for row in valid:
        grouped[row["date"][:7]].append(row)
    monthly = {key: bucket(values) for key, values in sorted(grouped.items())}
    scope_months = [
        key
        for key in monthly
        if (year is None or int(key[:4]) == year) and (month is None or key == month)
    ]
    result = bucket(selected_rows)
    focus = month or (scope_months[-1] if scope_months else None)
    previous = monthly.get(previous_month(focus)) if focus else None
    result.update(
        currency=currency,
        months=scope_months,
        monthly=monthly,
        focus=focus,
        category_icons={r["id"]: r["icon_name"] for r in categories.values()},
        comparison_months=([m for m in monthly if m <= month] if month else scope_months),
        previous=previous,
        category_names=names,
        category_colors=colors,
        after_refunds=after_refunds,
        omit_salary=omit_salary,
        excluded=sum(selected(r) for r in excluded),
        expenses=result["gross"],
        net=result["inflows"] - result["gross"],
        detail_category="all",
    )
    return result
