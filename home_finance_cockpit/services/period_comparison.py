"""Period comparisons use integer contributions before optional normalization."""

from calendar import monthrange
from datetime import date
from statistics import median


def comparison(data, month_a, month_b, *, equal_days=True, per_day=False, today=None):
    today = today or date.today()

    def length(month):
        year, number = map(int, month.split("-"))
        return today.day if month == today.strftime("%Y-%m") else monthrange(year, number)[1]

    lengths = [length(m) for m in (month_a, month_b)]
    if equal_days:
        lengths = [min(lengths)] * 2
    periods = []
    for month, days in zip((month_a, month_b), lengths):
        bucket = data["monthly"][month]
        rows = [r for r in bucket["rows"] if int(r["date"][-2:]) <= days]
        contributions = [c for c in bucket["contributions"] if int(c["row"]["date"][-2:]) <= days]
        categories = {}
        daily = {}
        for c in contributions:
            categories[c["root"]] = categories.get(c["root"], 0) + c["value"]
            day = c["row"]["date"]
            daily[day] = daily.get(day, 0) + c["value"]
        amounts = [-r["amount_minor"] for r in rows if r["amount_minor"] < 0]
        total = sum(categories.values())
        periods.append(
            dict(
                month=month,
                days=days,
                total=total,
                average=total / days,
                count=len(amounts),
                median=median(amounts) if amounts else None,
                highest=max(daily.values(), default=0),
                categories=categories,
                contributions=contributions,
            )
        )
    a, b = periods
    roots = set(a["categories"]) | set(b["categories"])
    values = {
        root: (
            a["categories"].get(root, 0) / (a["days"] if per_day else 1),
            b["categories"].get(root, 0) / (b["days"] if per_day else 1),
        )
        for root in roots
    }
    roots = sorted(
        roots,
        key=lambda root: (
            -abs(values[root][1] - values[root][0]),
            data["category_names"].get(root, ""),
        ),
    )
    changed = {root for root in roots if values[root][0] != values[root][1]}
    ids = {c["row"]["id"] for p in periods for c in p["contributions"] if c["root"] in changed}
    return dict(
        a=a,
        b=b,
        roots=roots,
        values=values,
        changed_ids=sorted(ids),
        per_day=per_day,
        currency=data["currency"],
        category_names=data["category_names"],
    )
