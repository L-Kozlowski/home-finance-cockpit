"""Stable column identities for bank exports with repeated display headings."""

from collections import Counter

from home_finance_cockpit.localization import tr


def column_letter(position):
    result = ""
    while position:
        position, remainder = divmod(position - 1, 26)
        result = chr(65 + remainder) + result
    return result


def unique_headers(values):
    headers = [value.lstrip("\ufeff").strip() for value in values]
    if not any(headers):
        raise ValueError(tr("Plik nie zawiera nagłówków."))
    reserved = {header.casefold() for header in headers if header}
    for position, header in enumerate(headers, 1):
        if not header:
            # Synthetic column identities stay stable when the UI language changes.
            base = f"Column {column_letter(position)}"
            candidate, suffix = base, 2
            while candidate.casefold() in reserved:
                candidate = f"{base} [{suffix}]"
                suffix += 1
            headers[position - 1] = candidate
            reserved.add(candidate.casefold())
    counts = Counter(header.casefold() for header in headers)
    reserved = {header.casefold() for header in headers}
    result = []
    for position, header in enumerate(headers, 1):
        if counts[header.casefold()] > 1:
            candidate = f"{header} [{column_letter(position)}]"
            suffix = 2
            while candidate.casefold() in reserved:
                candidate = f"{header} [{column_letter(position)}] [{suffix}]"
                suffix += 1
            header = candidate
            reserved.add(header.casefold())
        result.append(header)
    return result


def header_warnings(values, headers):
    columns = [
        f"{column_letter(index)} → {headers[index - 1]}"
        for index, value in enumerate(values, 1)
        if not value.strip().lstrip("\ufeff")
    ]
    return (
        [
            tr(
                "Puste nazwy kolumn zastąpiono: {columns}. Sprawdź mapowanie przed zapisem.",
                columns=", ".join(columns),
            )
        ]
        if columns
        else []
    )
