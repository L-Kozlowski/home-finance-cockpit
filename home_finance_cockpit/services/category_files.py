"""Validate and atomically merge category trees and keywords from JSON data."""

import json
import unicodedata
from pathlib import Path

from home_finance_cockpit.domain.categories import (
    RULE_COLUMNS,
    rule_conditions,
    validate_conditions,
)
from home_finance_cockpit.domain.validation import text
from home_finance_cockpit.localization import tr


def _category_key(name):
    return unicodedata.normalize("NFC", " ".join(name.split())).casefold()


def _find_import_category(db, name, parent_id=None):
    """Merge equivalent names in the same branch without replacing user settings."""
    return next(
        (
            row
            for row in db.categories()
            if row["parent_id"] == parent_id and _category_key(row["name"]) == _category_key(name)
        ),
        None,
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(tr("Powtórzony klucz JSON: {v0}.", v0=key))
        result[key] = value
    return result


def read_category_file(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError(tr("Plik kategorii przekracza 2 MB."))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(tr("Nieprawidłowy JSON kategorii: {v0}", v0=exc)) from None
    if not isinstance(data, dict) or not data:
        raise ValueError(tr("Oczekiwano obiektu: kolumna → kategoria → podkategoria → lista słów."))
    if data.get("format") == "home-finance-categories":
        return _read_export(data)
    aliases = {
        **{key: key for key in RULE_COLUMNS},
        "details": "description",
        "opis": "description",
        "description": "description",
        "kontrahent": "from_to",
        "from_to": "from_to",
        "counterparty": "from_to",
        "data": "date",
        "waluta": "currency",
    }
    entries, assigned = [], {}
    for source, categories in data.items():
        source = text(source, "Kolumna", limit=200)
        column = aliases.get(source.casefold())
        if column is None:
            raise ValueError(
                tr(
                    "Pole {field} nie jest polem aplikacji. Użyj opisu, kontrahenta, daty lub waluty.",
                    field=source,
                )
            )
        if not isinstance(categories, dict):
            raise ValueError(tr("{v0}: oczekiwano kategorii głównych.", v0=source))
        for parent, children in categories.items():
            parent = text(parent, "Kategoria", limit=100)
            if not isinstance(children, dict):
                raise ValueError(tr("{v0}: oczekiwano obiektu z podkategoriami.", v0=parent))
            entries.append((column, parent, None, None))
            for child, keywords in children.items():
                child = text(child, "Podkategoria", limit=100)
                if not isinstance(keywords, list):
                    raise ValueError(
                        tr("{v0} / {v1}: słowa kluczowe muszą być listą.", v0=parent, v1=child)
                    )
                entries.append((column, parent, child, None))
                for keyword in keywords:
                    keyword = text(keyword, "Słowo kluczowe")
                    key, target = (
                        (column, keyword.casefold()),
                        (_category_key(parent), _category_key(child)),
                    )
                    if key in assigned and assigned[key] != target:
                        raise ValueError(
                            tr(
                                "Słowo {v0!r} przypisano do różnych kategorii w kolumnie {v1}.",
                                v0=keyword,
                                v1=source,
                            )
                        )
                    assigned[key] = target
                    entries.append((column, parent, child, keyword))
    return entries


def import_category_file(db, path):
    entries = read_category_file(path)
    if isinstance(entries, dict):
        return _import_export(db, entries)
    categories_added = rules_added = repeated = 0
    with db.transaction():
        for column, parent_name, child_name, keyword in entries:
            parent = _find_import_category(db, parent_name)
            if parent is None:
                parent_id = db.save_category(parent_name)
                categories_added += 1
            else:
                parent_id = parent["id"]
            target_id = parent_id
            if child_name is not None:
                child = _find_import_category(db, child_name, parent_id)
                if child is None:
                    target_id = db.save_category(child_name, parent_id=parent_id)
                    categories_added += 1
                else:
                    target_id = child["id"]
            if keyword is None:
                continue
            existing = next(
                (
                    r
                    for r in db.rules()
                    if r["column_name"] == column
                    and r["mode"] == "literal"
                    and r["pattern"].casefold() == keyword.casefold()
                    and len(rule_conditions(r)) == 1
                ),
                None,
            )
            if existing:
                if existing["category_id"] != target_id:
                    raise ValueError(
                        tr(
                            "Istniejąca reguła {v0!r} wskazuje inną kategorię. Popraw ją przed importem.",
                            v0=keyword,
                        )
                    )
                repeated += 1
            else:
                db.save_rule(target_id, column, keyword)
                rules_added += 1
    return categories_added, rules_added, repeated


def export_category_file(db, path):
    """Export hierarchy, appearance and all compound rules without transaction data."""
    categories = [dict(c) for c in db.categories() if not c["is_default"]]
    data = {
        "format": "home-finance-categories",
        "version": 1,
        "categories": [
            {key: c[key] for key in ("id", "parent_id", "name", "color", "icon_name")}
            for c in categories
        ],
        "rules": [
            {"category_id": r["category_id"], "conditions": rule_conditions(r)} for r in db.rules()
        ],
    }
    encoded = json.dumps(data, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError(tr("Plik kategorii przekracza 2 MB."))
    Path(path).write_text(encoded + "\n", encoding="utf-8")


def _read_export(data):
    """Validate the portable format before making database changes."""
    if (
        data.get("version") != 1
        or not isinstance(data.get("categories"), list)
        or not isinstance(data.get("rules"), list)
    ):
        raise ValueError(tr("Nieprawidłowy format eksportu kategorii."))
    identifiers = {}
    for item in data["categories"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), int)
            or item["id"] in identifiers
        ):
            raise ValueError(tr("Nieprawidłowy format eksportu kategorii."))
        text(item.get("name"), "Kategoria", limit=100)
        identifiers[item["id"]] = item
    for item in identifiers.values():
        parent = item.get("parent_id")
        if parent is not None and (
            not isinstance(parent, int)
            or parent not in identifiers
            or identifiers[parent].get("parent_id") is not None
            or parent == item["id"]
        ):
            raise ValueError(tr("Nieprawidłowy format eksportu kategorii."))
    for rule in data["rules"]:
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("category_id"), int)
            or rule.get("category_id") not in identifiers
        ):
            raise ValueError(tr("Nieprawidłowy format eksportu kategorii."))
        validate_conditions(rule.get("conditions"))
    return data


def _import_export(db, data):
    added = rules_added = repeated = 0
    targets = {}
    with db.transaction():
        for item in sorted(data["categories"], key=lambda c: c.get("parent_id") is not None):
            parent_id = targets.get(item.get("parent_id"))
            existing = _find_import_category(db, item["name"], parent_id)
            if existing is not None:
                if existing["is_default"]:
                    raise ValueError(tr("Nieprawidłowy format eksportu kategorii."))
                targets[item["id"]] = existing["id"]
            else:
                targets[item["id"]] = db.save_category(
                    item["name"],
                    parent_id=parent_id,
                    color=item.get("color"),
                    icon_name=item.get("icon_name"),
                )
                added += 1
        for rule in data["rules"]:
            target = targets[rule["category_id"]]
            conditions = validate_conditions(rule["conditions"])
            signature = sorted(
                (c["column_name"], c["mode"], c["pattern"].casefold()) for c in conditions
            )
            existing = next(
                (
                    r
                    for r in db.rules()
                    if sorted(
                        (c["column_name"], c["mode"], c["pattern"].casefold())
                        for c in rule_conditions(r)
                    )
                    == signature
                ),
                None,
            )
            if existing is not None:
                if existing["category_id"] != target:
                    raise ValueError(tr("Istniejąca reguła wskazuje inną kategorię."))
                repeated += 1
                continue
            first = conditions[0]
            db.save_rule(
                target,
                first["column_name"],
                first["pattern"],
                first["mode"],
                conditions=conditions[1:],
            )
            rules_added += 1
    return added, rules_added, repeated
