"""Locate bank table headers without treating introductory text as transactions."""

import csv
from io import StringIO

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.search import normalize

HEADER_SCAN_LIMIT = 200


def recover_quoted_row(raw, separator, width):
    """Recover literal bank-export quotes only when column boundaries are clear."""
    values = next(csv.reader(StringIO(raw), delimiter=separator, quoting=csv.QUOTE_NONE), [])
    if len(values) == width:
        return [
            value[1:-1].replace('""', '"')
            if len(value) >= 2 and value.startswith('"') and value.endswith('"')
            else value
            for value in values
        ]
    # Keep embedded separators inside quoted fields, escaping stray inner quotes.
    repaired, quoted, at_start = [], False, True
    index = 0
    while index < len(raw):
        char = raw[index]
        following = raw[index + 1 : index + 2]
        if char == '"':
            if not quoted and at_start:
                quoted = True
            elif quoted:
                if following == '"':
                    repaired.append('""')
                    index += 2
                    continue
                if (
                    not following
                    or following in ("\r", "\n")
                    or (following == separator and raw[index + 1 :].count('"') % 2 == 0)
                ):
                    quoted = False
                else:
                    repaired.append('""')
                    index += 1
                    continue
        repaired.append(char)
        at_start = not quoted and char == separator
        index += 1
    try:
        values = list(csv.reader(StringIO("".join(repaired)), delimiter=separator, strict=True))
    except csv.Error:
        return None
    return values[0] if len(values) == 1 and len(values[0]) == width else None


class BankCSVReader:
    """Use strict CSV first; retry malformed physical rows without losing later rows."""

    def __init__(self, stream, separator):
        self.stream, self.separator = stream, separator
        self.reader = csv.reader(stream, delimiter=separator, strict=True)
        self.line_num = self.base_line = 0
        self.width = None

    def __iter__(self):
        return self

    def __next__(self):
        start, previous_line = self.stream.tell(), self.line_num
        try:
            values = next(self.reader)
            self.line_num = self.base_line + self.reader.line_num
        except csv.Error:
            self.stream.seek(start)
            raw = self.stream.readline()
            self.line_num = self.base_line = previous_line + 1
            self.reader = csv.reader(self.stream, delimiter=self.separator, strict=True)
            values = recover_quoted_row(raw, self.separator, self.width) if self.width else None
            if values is None:
                raise
        if self.width is None:
            self.width = len(values)
        return values


def header_score(values, following=()):
    names = [normalize(str(value)).strip().rstrip(":") for value in values]
    if len(names) < 2 or not any(names):
        return -1
    date_names = {
        "data",
        "date",
        "data transakcji",
        "data ksiegowania",
        "data operacji",
        "data waluty",
        "started date",
        "data rozpoczecia",
        "booking date",
        "transaction date",
    }
    amount_names = {
        "kwota",
        "amount",
        "kwota transakcji (waluta rachunku)",
        "transaction amount",
        "debit",
        "credit",
        "obciazenie",
        "uznanie",
    }
    dates = bool(set(names) & date_names)
    amounts = bool(set(names) & amount_names) or any(
        name.startswith(("kwota transakcji", "kwota operacji", "kwota w walucie", "amount ("))
        for name in names
    )
    known = sum(
        name
        in date_names
        | amount_names
        | {
            "opis",
            "description",
            "details",
            "tytul",
            "waluta",
            "currency",
            "kontrahent",
            "counterparty",
        }
        for name in names
    )
    consistent = len(following) == len(values)
    textual = all(name and not any(c.isdigit() for c in name) for name in names)
    return (
        100 * (dates and amounts)
        + 20 * (dates or amounts)
        + known * 3
        + 2 * consistent
        + textual
        - 10 * names.count("") / len(names)
    )


def validate_header_row(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
        raise ValueError(tr("Numer wiersza nagłówków musi być dodatnią liczbą całkowitą."))


def locate_csv_table(content, delimiter="auto", header_row=None):
    validate_header_row(header_row)
    if delimiter not in ("auto", ",", ";", "\t"):
        raise ValueError(tr("Nieobsługiwany separator CSV."))
    lines = content.splitlines(keepends=True)
    if not lines:
        raise ValueError(tr("Plik CSV jest pusty."))
    if header_row is not None and header_row > len(lines):
        raise ValueError(tr("Wiersz nagłówków {row} nie istnieje w pliku.", row=header_row))
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    positions = [header_row - 1] if header_row else range(min(len(lines), HEADER_SCAN_LIMIT))
    stream = StringIO(content, newline="")
    candidates = []
    for position in positions:
        for separator in (",", ";", "\t") if delimiter == "auto" else (delimiter,):
            stream.seek(offsets[position])
            reader = csv.reader(stream, delimiter=separator, strict=True)
            try:
                values = next(reader)
            except (StopIteration, csv.Error):
                continue
            try:
                following = next(reader, [])
            except csv.Error:
                following = []
            score = header_score(values, following)
            if score >= 0:
                candidates.append((score, -position, len(values), separator))
    if not candidates:
        raise ValueError(
            tr("Nie znaleziono tabeli. Podaj numer wiersza z nazwami kolumn i sprawdź separator.")
        )
    _, negative_position, _, separator = max(candidates)
    return separator, -negative_position + 1
