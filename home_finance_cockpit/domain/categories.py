"""Shared category-rule fields and matching operators."""

from home_finance_cockpit.localization import quote_text, tr

RULE_COLUMNS = {
    "description": "Opis",
    "from_to": "Kontrahent",
    "date": "Data",
    "currency": "Waluta",
}
RULE_MODES = {
    "literal": "Zawiera",
    "not_contains": "Nie zawiera",
    "exact": "Jest równe",
    "starts_with": "Zaczyna się od",
    "like": "LIKE (% i _)",
}


def category_name(category):
    """Translate only the built-in fallback category, never user category names."""
    return tr("Ogólne") if category["is_default"] else category["name"]


def column_label(column):
    if column is None:
        return tr("Wybierz pole aplikacji")
    return (
        tr(RULE_COLUMNS[column])
        if column in RULE_COLUMNS
        else tr("Plik: ") + column.removeprefix("raw:")
    )


def rule_conditions(rule):
    import json

    row = dict(rule)
    return [
        dict(column_name=row["column_name"], mode=row["mode"], pattern=row["pattern"])
    ] + json.loads(row.get("conditions_json") or "[]")


def describe_rule(rule):
    return tr(" ORAZ ").join(
        f"{column_label(c['column_name'])} {tr(RULE_MODES[c['mode']]).lower()} {quote_text(c['pattern'])}"
        for c in rule_conditions(rule)
    )


def validate_conditions(conditions):
    from home_finance_cockpit.domain.validation import text

    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 12:
        raise ValueError(tr("Reguła musi mieć od 1 do 12 warunków."))
    result, seen = [], set()
    for condition in conditions:
        if not isinstance(condition, dict):
            raise ValueError(tr("Nieprawidłowy warunek reguły."))
        column, mode = condition.get("column_name"), condition.get("mode")
        if (
            not isinstance(column, str)
            or column not in RULE_COLUMNS
            or not isinstance(mode, str)
            or mode not in RULE_MODES
        ):
            raise ValueError(tr("Nieprawidłowe pole lub tryb warunku."))
        pattern = text(condition.get("pattern"), "Tekst warunku")
        if mode == "like" and not pattern.replace("%", "").replace("_", "").strip():
            raise ValueError(tr("Wzorzec musi zawierać tekst, nie tylko znaki wieloznaczne."))
        key = (column, mode, pattern.casefold())
        if key in seen:
            raise ValueError(tr("Ten sam warunek występuje w regule więcej niż raz."))
        if (
            mode in ("literal", "not_contains")
            and (
                column,
                "literal" if mode == "not_contains" else "not_contains",
                pattern.casefold(),
            )
            in seen
        ):
            raise ValueError(tr("Warunki są sprzeczne: ten sam tekst ma być zawarty i wykluczony."))
        seen.add(key)
        result.append(dict(column_name=column, mode=mode, pattern=pattern))
    return result
