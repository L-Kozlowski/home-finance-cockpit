"""CSV preparation is read-only; commit writes the entire batch atomically."""

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from io import StringIO
from pathlib import Path

from home_finance_cockpit.domain.validation import currency_code, iso_date, money_minor, text
from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.categorization import classify
from home_finance_cockpit.services.import_columns import header_warnings, unique_headers
from home_finance_cockpit.services.import_table import BankCSVReader, locate_csv_table

IMPORT_FIELDS = {
    "date": "Data",
    "amount": "Kwota ze znakiem",
    "amount_fallback": "Kwota zapasowa",
    "debit": "Obciążenie",
    "credit": "Uznanie",
    "description": "Opis",
    "from_to": "Kontrahent",
    "category": "Kategoria bankowa",
    "currency": "Waluta",
    "status": "Status",
    "external_id": "ID z banku",
}


def required_fields(mode):
    if mode not in ("signed", "split"):
        raise ValueError(tr("Wybierz sposób odczytu kwoty."))
    return ("date", "debit", "credit") if mode == "split" else ("date", "amount")


@dataclass
class CSVFile:
    name: str
    digest: str
    headers: list
    rows: list
    encoding: str | None = None
    source_rows: list = field(default_factory=list)
    row_errors: dict = field(default_factory=dict)
    header_row: int = 1
    header_warnings: list = field(default_factory=list)


@dataclass
class ImportPlan:
    file: CSVFile
    wallet_id: int
    mapping: dict
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    skipped: int = 0
    already_imported: bool = False
    skipped_rows: dict = field(default_factory=dict)
    opening_date: str | None = None


def read_csv(path, encoding="auto", delimiter="auto", *, header_row=None):
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 25 * 1024 * 1024:
        raise ValueError(tr("Plik przekracza limit 25 MB. Podziel eksport na mniejsze okresy."))
    selected = encoding
    try:
        if encoding == "auto":
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                selected = "utf-16"
            else:
                selected = "utf-8-sig"
                try:
                    data.decode(selected)
                except UnicodeDecodeError:
                    selected = "cp1250"
        content = data.decode(selected)
        if "\x00" in content:
            raise UnicodeError("NUL characters in decoded CSV")
    except (UnicodeError, LookupError):
        raise ValueError(
            tr(
                "Nie można odczytać kodowania CSV. Wybierz ręcznie UTF-8, Windows-1250, ISO-8859-2 lub UTF-16."
            )
        ) from None
    separator, header_row = locate_csv_table(content, delimiter, header_row)
    offset = header_row - 1
    stream = StringIO("".join(content.splitlines(keepends=True)[offset:]), newline="")
    reader = BankCSVReader(stream, separator)
    try:
        original_headers = next(reader)
        headers = unique_headers(original_headers)
        rows, source_rows, row_errors = [], [], {}
        while True:
            line = offset + reader.line_num + 1
            try:
                values = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                row_errors[line] = tr("Nie można odczytać wiersza CSV: {error}", error=exc)
                source_rows.append((line, []))
                rows.append((line, {}))
                if offset + reader.line_num < line:
                    break
                continue
            if not values or not any(v.strip() for v in values):
                continue
            if len(values) != len(headers):
                row_errors[line] = tr(
                    "Wiersz {v0}: oczekiwano {v1} pól, otrzymano {v2}.",
                    v0=line,
                    v1=len(headers),
                    v2=len(values),
                )
            source_rows.append((line, values))
            rows.append((line, dict(zip(headers, values))))
    except StopIteration:
        raise ValueError(tr("Plik CSV jest pusty.")) from None
    except csv.Error as exc:
        raise ValueError(
            tr("Błąd CSV w pobliżu wiersza {v0}: {v1}", v0=offset + reader.line_num, v1=exc)
        ) from None
    if not rows:
        raise ValueError(tr("CSV nie zawiera transakcji."))
    return CSVFile(
        path.name,
        sha256(data).hexdigest(),
        headers,
        rows,
        selected,
        source_rows,
        row_errors,
        header_row,
        header_warnings(original_headers, headers),
    )


def suggested_mapping(headers):
    aliases = {
        "date": [
            "Data transakcji",
            "Data rozpoczęcia",
            "Started Date",
            "Data",
            "Date",
            "Data księgowania",
            "Data operacji",
            "Transaction Date",
            "Booking Date",
        ],
        "amount": ["Kwota transakcji (waluta rachunku)", "Kwota", "Amount"],
        "description": ["Tytuł", "Opis", "Description", "Details"],
        "from_to": ["Dane kontrahenta", "Kontrahent", "Od/Do", "Counterparty"],
        "category": ["Kategoria", "Category"],
        "currency": ["Waluta", "Currency"],
        "status": ["State", "Status"],
        "external_id": ["Transaction ID", "ID transakcji", "Nr transakcji"],
    }
    folded = {h.casefold(): h for h in headers}
    mapping = {
        field: next((folded[a.casefold()] for a in names if a.casefold() in folded), None)
        for field, names in aliases.items()
    }
    if not mapping["amount"]:
        candidates = [
            h
            for h in headers
            if h.casefold().startswith(("kwota operacji", "kwota transakcji", "amount ("))
        ]
        if len(candidates) == 1:
            mapping["amount"] = candidates[0]
    return mapping


def _signature(wallet_id, day, amount, description, counterparty):
    return (
        wallet_id,
        day,
        amount,
        " ".join(description.casefold().split()),
        " ".join(counterparty.casefold().split()),
    )


def prepare_import(db, file, wallet_id, mapping):
    wallet = db.wallet(wallet_id)
    mapping = dict(mapping)
    mode = mapping.get("amount_mode", "signed")
    # Stored/programmatic legacy mappings remain readable. The import UI only
    # creates signed-amount mappings and does not expose split/status/ID fields.
    required = required_fields(mode)
    for inactive in ("amount",) if mode == "split" else ("debit", "credit"):
        mapping.pop(inactive, None)
    plan = ImportPlan(file, wallet_id, dict(mapping))
    excluded_lines = set(mapping.get("excluded_lines", []))
    history = db.execute(
        "SELECT id FROM imports WHERE wallet_id=? AND file_hash=?", (wallet_id, file.digest)
    ).fetchone()
    plan.already_imported = history is not None
    missing = [tr(IMPORT_FIELDS[key]) for key in required if not mapping.get(key)]
    if missing:
        raise ValueError(
            (
                (tr("Uzupełnij wymagane mapowanie (*): ") + ", ".join(missing))
                + tr(". Pozostałe pola są opcjonalne.")
            )
        )
    for key, label in IMPORT_FIELDS.items():
        if mapping.get(key) and mapping[key] not in file.headers:
            raise ValueError(tr("{v0}: wybrana kolumna nie istnieje w CSV.", v0=tr(label)))
    chosen = [mapping[key] for key in required]
    if len(set(chosen)) != len(chosen):
        raise ValueError(tr("Data i kolumny kwot muszą wskazywać różne kolumny CSV."))

    def signature(day, minor, description, counterparty):
        return _signature(
            wallet_id,
            day,
            minor,
            description if mapping.get("description") else "",
            counterparty if mapping.get("from_to") else "",
        )

    stored_transactions = db.transactions(wallet_id)
    comparable = [t for t in stored_transactions if not history or t["import_id"] != history["id"]]
    existing = Counter(
        signature(t["date"], t["amount_minor"], t["description"], t["from_to"]) for t in comparable
    )
    without_bank_id = Counter(
        signature(t["date"], t["amount_minor"], t["description"], t["from_to"])
        for t in comparable
        if not t["external_id"]
    )
    imported_lines = {
        t["source_line"] for t in stored_transactions if history and t["import_id"] == history["id"]
    }
    occurrences = Counter()
    ids = {}
    rules = db.rules()
    categories = {c["id"]: c for c in db.categories()}
    for line, raw in file.rows:
        if line in excluded_lines:
            plan.skipped_rows[line] = tr("Pominięty przez użytkownika")
            continue
        if line in file.row_errors:
            plan.skipped_rows[line] = file.row_errors[line]
            plan.errors.append(tr("Wiersz {v0}: {v1}", v0=line, v1=file.row_errors[line]))
            continue

        def get(field):
            return raw.get(mapping.get(field), "").strip()

        try:
            status = get("status").casefold()
            if mapping.get("status"):
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
                    plan.skipped += 1
                    plan.skipped_rows[line] = tr("Operacja niezakończona")
                    continue
                if status not in ("completed", "zakończono", "zrealizowano", "booked", "settled"):
                    raise ValueError(tr("Nieznany status operacji: {v0!r}.", v0=get("status")))
            day = iso_date(get("date"))
            if mode == "signed":
                minor = money_minor(get("amount") or get("amount_fallback"))
            else:
                debit = money_minor(get("debit")) if get("debit") else 0
                credit = money_minor(get("credit")) if get("credit") else 0
                if debit < 0 or credit < 0 or (debit and credit):
                    raise ValueError(
                        tr(
                            "Obciążenie i uznanie muszą być nieujemne; tylko jedno może być niezerowe."
                        )
                    )
                minor = credit - debit
            if not minor:
                raise ValueError(tr("Zerowa kwota transakcji."))
            if mapping.get("currency") and currency_code(get("currency")) != wallet["currency"]:
                raise ValueError(tr("Waluta transakcji różni się od waluty portfela."))
            description = text(get("description"), "Opis", required=False, limit=5000)
            counterparty = text(get("from_to"), "Kontrahent", required=False)
            category = text(get("category"), "Kategoria", required=False, limit=100)
            external_id = (
                text(get("external_id"), "ID transakcji", required=False, limit=200) or None
            )
            identity = signature(day, minor, description, counterparty)
            duplicate = False
            if external_id:
                stored = db.execute(
                    "SELECT * FROM transactions WHERE wallet_id=? AND external_id=?",
                    (wallet_id, external_id),
                ).fetchone()
                previous = ids.get(external_id)
                full_signature = identity
                if previous and previous != full_signature:
                    raise ValueError(
                        tr(
                            "ID bankowe {v0!r} występuje z innymi danymi. Wyjaśnij różnicę przed importem.",
                            v0=external_id,
                        )
                    )
                duplicate = stored is not None or previous is not None
                ids[external_id] = full_signature
            occurrence_key = (identity, bool(external_id))
            potential = False
            if not duplicate and line not in imported_lines:
                occurrences[occurrence_key] += 1
                potential = occurrences[occurrence_key] <= (
                    without_bank_id[identity] if external_id else existing[identity]
                )
            duplicate = duplicate or potential or line in imported_lines
            if potential or duplicate:
                plan.duplicates.append(line)
            row = dict(
                date=day,
                amount_minor=minor,
                description=description,
                from_to=counterparty,
                currency=wallet["currency"],
                category=category,
                source_line=line,
                raw_json=json.dumps(
                    {
                        header: raw[header]
                        for field in IMPORT_FIELDS
                        if isinstance((header := mapping.get(field)), str) and header in raw
                    },
                    ensure_ascii=False,
                ),
                external_id=external_id,
                duplicate=duplicate,
                potential_duplicate=potential,
            )
            rule, conflict = classify(row, rules)
            target = categories[rule["category_id"]] if rule else None
            row["category_name"] = (
                (target["parent_name"] or target["name"])
                if target
                else category or categories[db.default_category_id()]["name"]
            )
            row["subcategory_name"] = (
                target["name"] if target and target["parent_id"] is not None else ""
            )
            row["category_conflict"] = conflict
            row["is_uncategorized"] = not target and (
                not category or category == categories[db.default_category_id()]["name"]
            )
            plan.rows.append(row)
        except ValueError as exc:
            plan.skipped_rows[line] = str(exc)
            plan.errors.append(tr("Wiersz {v0}: {v1}", v0=line, v1=exc))
    earliest = min((row["date"] for row in plan.rows if not row["duplicate"]), default=None)
    if earliest and earliest < wallet["opening_date"]:
        plan.opening_date = earliest
    return plan


def commit_import(db, plan):
    """Revalidate against current data to avoid stale preview and concurrent reimports."""
    with db.transaction():
        current = prepare_import(db, plan.file, plan.wallet_id, plan.mapping)
        plan.rows, plan.errors = current.rows, current.errors
        plan.skipped_rows, plan.duplicates = current.skipped_rows, current.duplicates
        plan.opening_date = current.opening_date
        if not current.rows:
            return 0
        if current.opening_date:
            db.execute(
                "UPDATE wallets SET opening_date=? WHERE id=?",
                (current.opening_date, plan.wallet_id),
            )
        existing_import = db.execute(
            "SELECT id FROM imports WHERE wallet_id=? AND file_hash=?",
            (plan.wallet_id, plan.file.digest),
        ).fetchone()
        cursor = db.execute(
            """INSERT OR IGNORE INTO imports(wallet_id,file_name,file_hash,mapping_json,imported_at,row_count)
            VALUES (?,?,?,?,?,0)""",
            (
                plan.wallet_id,
                plan.file.name,
                plan.file.digest,
                json.dumps(plan.mapping, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        import_id = existing_import["id"] if existing_import else cursor.lastrowid
        rules = db.rules()
        inserted = 0
        for tx in current.rows:
            if tx["duplicate"]:
                continue
            category_id = db.default_category_id()
            source = "unassigned"
            rule, conflict = classify(tx, rules)
            if rule:
                category_id, source = rule["category_id"], "rule"
            elif tx["category"]:
                found = db.find_category(tx["category"])
                category_id = found["id"] if found else db.save_category(tx["category"])
                source = "bank" if category_id != db.default_category_id() else "unassigned"
            from decimal import Decimal

            tx_id = db.save_transaction(
                plan.wallet_id,
                Decimal(tx["amount_minor"]) / 100,
                category_id,
                tx["description"],
                tx["date"],
                tx["from_to"],
                source=source,
                import_id=import_id,
                source_line=tx["source_line"],
                raw_json=tx["raw_json"],
                external_id=tx["external_id"],
            )
            db.execute(
                "UPDATE transactions SET matched_rule_id=?,category_conflict=? WHERE id=?",
                (rule["id"] if rule else None, int(conflict), tx_id),
            )
            inserted += 1
        db.execute("UPDATE imports SET row_count=row_count+? WHERE id=?", (inserted, import_id))
        return inserted
