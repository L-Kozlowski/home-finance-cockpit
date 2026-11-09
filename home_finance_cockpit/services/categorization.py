"""Deterministic matching with conflict reporting and manual edit protection."""

import json
import re


def field_value(transaction, column):
    if column.startswith("raw:"):
        raw = transaction["raw_json"] if "raw_json" in transaction.keys() else None
        values = json.loads(raw or "{}")
        return (
            str(values[column[4:]]) if isinstance(values, dict) and column[4:] in values else None
        )
    return str(transaction[column] or "") if column in transaction.keys() else ""


def matching_rules(transaction, rules):
    from home_finance_cockpit.domain.categories import rule_conditions

    matches = []
    for rule in rules:
        conditions = rule_conditions(rule)
        specificity = 0
        for condition in conditions:
            value = field_value(transaction, condition["column_name"])
            if value is None:
                break
            value = value.casefold()
            pattern, mode = condition["pattern"].casefold(), condition["mode"]
            if mode == "literal":
                matched = pattern in value
            elif mode == "not_contains":
                matched = pattern not in value
            elif mode == "exact":
                matched = pattern == value.strip()
            elif mode == "starts_with":
                matched = value.startswith(pattern)
            elif mode == "like":
                expression = "".join(
                    ".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern
                )
                matched = re.search(expression, value, re.DOTALL) is not None
            else:
                matched = False
            if not matched:
                break
            if mode != "not_contains":
                specificity += (
                    len(pattern.replace("%", "").replace("_", ""))
                    if mode == "like"
                    else len(pattern)
                )
        else:
            matches.append((len(conditions), specificity, rule))
    matches.sort(key=lambda item: (-item[0], -item[1], item[2]["id"]))
    return [rule for _, _, rule in matches]


def classify(transaction, rules):
    matches = matching_rules(transaction, rules)
    return (matches[0] if matches else None), len({rule["category_id"] for rule in matches}) > 1


def apply_rules(db, *, include_bank=False, include_manual=False):
    rules = db.rules()
    changed, conflicts = 0, 0
    with db.transaction():
        for tx in db.transactions():
            protected = tx["category_source"] in ("manual", "bank")
            if (tx["category_source"] == "manual" and not include_manual) or (
                tx["category_source"] == "bank" and not include_bank
            ):
                continue
            rule, conflict = classify(tx, rules)
            if protected and rule is None:
                continue
            category_id = rule["category_id"] if rule else db.default_category_id()
            db.execute(
                """UPDATE transactions SET category_id=?,category_source=?,matched_rule_id=?,category_conflict=? WHERE id=?""",
                (
                    category_id,
                    "rule" if rule else "unassigned",
                    rule["id"] if rule else None,
                    int(conflict),
                    tx["id"],
                ),
            )
            changed += int(category_id != tx["category_id"])
            conflicts += int(conflict)
    return changed, conflicts
