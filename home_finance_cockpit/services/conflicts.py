"""Explain rule conflicts and possible counterparty classification inconsistencies."""

from collections import Counter, defaultdict

from home_finance_cockpit.domain.categories import describe_rule
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.categorization import matching_rules


def category_name(row):
    root = row.get("category_name", row.get("category", ""))
    child = row.get("subcategory_name", row.get("subcategory", ""))
    return root + (" / " + child if child else "")


def annotate_conflicts(rows, rules=(), *, context=()):
    rows = [dict(r) for r in rows]
    grouped = defaultdict(Counter)
    for original in [*context, *rows]:
        row = dict(original)
        key = " ".join((row.get("from_to") or "").casefold().split())
        if key and not row.get("is_uncategorized", False) and not row.get("duplicate", False):
            grouped[key][category_name(row)] += 1
    for row in rows:
        reasons = []
        key = " ".join((row.get("from_to") or "").casefold().split())
        categories = grouped.get(key, {})
        row["possible_conflict"] = len(categories) > 1
        if row.get("category_conflict"):
            matches = matching_rules(row, rules)
            if len({r["category_id"] for r in matches}) > 1:
                descriptions = [
                    f"{r['category']}"
                    + (f" / {r['subcategory']}" if r["subcategory"] else "")
                    + ": "
                    + describe_rule(r)
                    for r in matches
                ]
                reasons.append(
                    tr("Pasują reguły przypisujące różne kategorie: ") + "; ".join(descriptions)
                )
            else:
                reasons.append(
                    tr(
                        "Przy ostatniej kategoryzacji pasowały reguły wskazujące różne kategorie. Sprawdź bieżące reguły i potwierdź przypisanie."
                    )
                )
        if row["possible_conflict"]:
            labels = [f"{name} ({count})" for name, count in sorted(categories.items())]
            reasons.append(
                tr(
                    "Możliwy konflikt: kontrahent „{v0}” ma w historii różne kategorie: ",
                    v0=row["from_to"],
                )
                + ", ".join(labels)
                + tr(
                    ". Różnica może być uzasadniona rodzajem zakupu — kategoria nie została zmieniona automatycznie."
                )
            )
        row["conflict_explanation"] = "\n".join(reasons)
    return rows
