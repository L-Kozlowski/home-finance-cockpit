"""Exact monetary aggregation independent of PDF, charts and Qt."""

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from home_finance_cockpit.domain.analysis_kinds import REFUND_KINDS, cost_contribution
from home_finance_cockpit.domain.categories import category_name
from home_finance_cockpit.domain.validation import currency_code, money_minor
from home_finance_cockpit.localization import tr


@dataclass(frozen=True)
class ReportOptions:
    currency: str
    wallet_id: int | None = None
    year: int | None = None
    months: tuple[str, ...] | None = None
    monthly: bool = True
    annual: bool = True
    transactions: bool = True
    uncategorized: bool = True
    comparison: bool = True
    exclude_recognized: bool = True
    after_refunds: bool = False
    omit_salary: bool = False


def previous_month(month):
    year, number = map(int, month.split("-"))
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def percent_change(current, previous):
    return Decimal(current - previous) * 100 / previous if previous and previous > 0 else None


def source_fields(row):
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except (ValueError, TypeError):
        return {}
    return {str(k).strip().casefold(): v for k, v in raw.items()} if isinstance(raw, dict) else {}


def excluded_reason(raw):
    kind = (
        str(next((raw[k] for k in ("rodzaj", "type", "transaction_type") if k in raw), ""))
        .strip()
        .casefold()
    )
    if kind in ("wymiana", "exchange", "currency exchange", "fx exchange"):
        return "Currency exchange"
    status = str(next((raw[k] for k in ("state", "status") if k in raw), "")).strip().casefold()
    if status in (
        "pending",
        "oczekująca",
        "oczekujące",
        "reverted",
        "cofnięto",
        "anulowano",
        "failed",
        "declined",
        "cancelled",
        "canceled",
        "odrzucono",
    ):
        return "Unfinished or reversed operation"
    return None


def snapshot(db, options):
    """Copy data on the connection's owning thread before background generation."""
    with db.transaction():
        categories = {c["id"]: dict(c) for c in db.categories()}
        wallets = [
            dict(w)
            for w in db.wallets()
            if w["currency"] == options.currency
            and (options.wallet_id is None or w["id"] == options.wallet_id)
        ]
        ids = {w["id"] for w in wallets}
        rows = [dict(t) for t in db.transactions() if t["wallet_id"] in ids]
    scope = ", ".join(w["name"] for w in wallets) or "No wallets"
    return aggregate(rows, categories, options, scope=scope)


def aggregate(rows, categories, options, *, scope="Selected wallets"):
    currency_code(options.currency)
    if not options.monthly and not options.annual:
        raise ValueError(tr("Wybierz raporty miesięczne lub roczne."))
    if options.year is not None and (
        isinstance(options.year, bool)
        or not isinstance(options.year, int)
        or not 1 <= options.year <= 9999
    ):
        raise ValueError(tr("Nieprawidłowy rok raportu."))
    all_months = {}
    category_colors = {
        category_name(c): c.get("color") for c in categories.values() if c["parent_id"] is None
    }
    prepared = []
    for original in rows:
        row = dict(original)
        if row["currency"] != options.currency or (
            options.wallet_id is not None and row["wallet_id"] != options.wallet_id
        ):
            continue
        row["month"] = row["date"][:7]
        raw = source_fields(row)
        row["excluded_reason"] = (
            "Excluded by user"
            if not row.get("include_in_reports", 1)
            else excluded_reason(raw)
            if options.exclude_recognized
            else None
        )
        if row.get("analysis_kind") == "transfer":
            row["excluded_reason"] = "Own transfer"
        elif options.omit_salary and row.get("analysis_kind") == "salary":
            row["excluded_reason"] = "Salary excluded"
        row["cost_minor"] = cost_contribution(
            row["amount_minor"], row.get("analysis_kind", "standard"), options.after_refunds
        )
        if (
            options.after_refunds
            and row.get("analysis_kind") in REFUND_KINDS
            and categories[row["category_id"]]["is_default"]
        ):
            row["category"] = "Zwroty do przypisania"
            row["subcategory"] = ""
        row["fee_minor"] = None
        for key in ("opłata", "fee", "fees"):
            if key in raw and str(raw[key]).strip():
                try:
                    row["fee_minor"] = money_minor(raw[key])
                except ValueError:
                    pass
                break
        row["uncategorized"] = bool(categories[row["category_id"]]["is_default"])
        prepared.append(row)
        all_months.setdefault(row["month"], []).append(row)
    if not all_months:
        raise ValueError(tr("Brak transakcji dla wybranego portfela i waluty."))
    if not any(r.get("include_in_reports", 1) for r in prepared):
        raise ValueError(
            tr("Brak transakcji zaznaczonych „W raportach” dla wybranego portfela i waluty.")
        )
    summaries = {}
    for month, raw_rows in sorted(all_months.items()):
        included = [r for r in raw_rows if not r["excluded_reason"]]
        expense_rows = [r for r in included if r["amount_minor"] < 0]
        category_totals, subcategories, daily = defaultdict(int), defaultdict(int), defaultdict(int)
        for row in included:
            amount = row["cost_minor"]
            if not amount:
                continue
            category_totals[row["category"]] += amount
            subcategories[row["category"], row["subcategory"] or "No subcategory"] += amount
            daily[row["date"]] += amount
        expense = sum(r["cost_minor"] for r in included)
        gross_expenses = sum(-r["amount_minor"] for r in expense_rows)
        refunds = sum(r["amount_minor"] for r in included if r.get("analysis_kind") in REFUND_KINDS)
        inflow = sum(r["amount_minor"] for r in included if r["amount_minor"] > 0)
        fees = [r["fee_minor"] for r in included if r["fee_minor"] is not None]
        missing = [r for r in expense_rows if r["uncategorized"]]
        summaries[month] = dict(
            month=month,
            raw=raw_rows,
            rows=included,
            expenses=expense,
            inflows=inflow,
            category_colors=dict(category_colors),
            eligible_count=sum(bool(r.get("include_in_reports", 1)) for r in raw_rows),
            user_excluded_count=sum(not r.get("include_in_reports", 1) for r in raw_rows),
            net=inflow - gross_expenses,
            gross_expenses=gross_expenses,
            refunds=refunds,
            fees=sum(fees) if fees else None,
            fee_count=len(fees),
            categories=dict(category_totals),
            subcategories=dict(subcategories),
            daily=dict(daily),
            expense_count=len(expense_rows),
            uncategorized=missing,
            uncategorized_minor=sum(-r["amount_minor"] for r in missing),
            conflicts=sum(bool(r["category_conflict"]) for r in included),
        )
    for month, summary in summaries.items():
        previous = summaries.get(previous_month(month))
        if previous and not previous["eligible_count"]:
            previous = None
        summary["change"] = summary["expenses"] - previous["expenses"] if previous else None
        summary["change_percent"] = (
            percent_change(summary["expenses"], previous["expenses"]) if previous else None
        )
        if (
            sum(summary["categories"].values()) != summary["expenses"]
            or sum(summary["subcategories"].values()) != summary["expenses"]
        ):
            raise ValueError(tr("Niezgodne sumy kategorii w raporcie."))
    annual_months = tuple(
        m
        for m in sorted(summaries)
        if summaries[m]["eligible_count"]
        and (options.year is None or m.startswith(f"{options.year:04d}-"))
    )
    if not annual_months:
        raise ValueError(tr("Brak transakcji dla wybranego roku."))
    requested = options.months if options.months is not None else annual_months
    if options.monthly and (not requested or set(requested) - set(annual_months)):
        raise ValueError(tr("Wybierz co najmniej jeden dostępny miesiąc raportu."))
    monthly_months = tuple(m for m in annual_months if m in requested) if options.monthly else ()
    return dict(
        options=options,
        scope=scope,
        rows=prepared,
        summaries=summaries,
        annual_months=annual_months,
        category_colors=category_colors,
        category_icons={
            category_name(c): c.get("icon_name") or "tag"
            for c in categories.values()
            if c["parent_id"] is None
        },
        monthly_months=monthly_months,
        years=tuple(sorted({m[:4] for m in annual_months})) if options.annual else (),
    )


def category_comparison(data, month):
    current = data["summaries"][month]
    previous = data["summaries"].get(previous_month(month))
    if previous and not previous["eligible_count"]:
        previous = None
    names = set(current["categories"]) | (set(previous["categories"]) if previous else set())
    result = []
    for name in sorted(names, key=lambda n: (-current["categories"].get(n, 0), n.casefold())):
        now, before = (
            current["categories"].get(name, 0),
            previous["categories"].get(name, 0) if previous else None,
        )
        result.append(
            (
                name,
                before,
                now,
                now - before if before is not None else None,
                percent_change(now, before) if before is not None else None,
            )
        )
    return result
