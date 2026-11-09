"""CSV/Excel input with shared column mapping and atomic multi-file imports."""

from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
from itertools import islice
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from home_finance_cockpit.localization import tr
from home_finance_cockpit.services.import_columns import header_warnings, unique_headers
from home_finance_cockpit.services.import_table import (
    HEADER_SCAN_LIMIT,
    header_score,
    validate_header_row,
)
from home_finance_cockpit.services.importing import CSVFile, commit_import, prepare_import, read_csv

SUPPORTED_FILES = (".csv", ".xlsx", ".xlsm")


def read_import_file(path, encoding="auto", delimiter="auto", sheet=None, *, header_row=None):
    validate_header_row(header_row)
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path, encoding, delimiter, header_row=header_row)
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(
            tr("Obsługiwane pliki: CSV, XLSX i XLSM. Stary plik XLS zapisz jako XLSX.")
        )
    from xml.etree.ElementTree import ParseError

    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    data = path.read_bytes()
    if len(data) > 25 * 1024 * 1024:
        raise ValueError(tr("Plik przekracza limit 25 MB."))
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 150 * 1024 * 1024:
                raise ValueError(tr("Rozpakowany arkusz przekracza limit 150 MB."))
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except (
        BadZipFile,
        KeyError,
        OSError,
        InvalidFileException,
        ParseError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(tr("Nieprawidłowy plik Excel: {v0}", v0=exc)) from None
    try:
        visible = [ws for ws in workbook.worksheets if ws.sheet_state == "visible"]
        if sheet is None:
            if not visible:
                raise ValueError(tr("Plik nie ma widocznego arkusza."))
            worksheet = visible[0]
        else:
            if sheet not in workbook.sheetnames:
                raise ValueError(tr("Brak arkusza „{v0}” w pliku {v1}.", v0=sheet, v1=path.name))
            worksheet = workbook[sheet]
        if worksheet.max_column and worksheet.max_column > 500:
            raise ValueError(tr("Arkusz ma ponad 500 kolumn. Usuń puste formatowanie poza tabelą."))

        def cell_value(cell):
            if cell.data_type == "f":
                raise ValueError(
                    tr(
                        "{v0}!{v1}: formuła zamiast wartości. Zapisz eksport jako wartości przed importem.",
                        v0=worksheet.title,
                        v1=cell.coordinate,
                    )
                )
            value = cell.value
            if isinstance(value, datetime):
                return value.date().isoformat()
            if isinstance(value, date):
                return value.isoformat()
            return str(value).strip() if value is not None else ""

        if header_row is None:
            sample = []
            for cells in islice(worksheet.iter_rows(), HEADER_SCAN_LIMIT + 1):
                values = [str(c.value).strip() if c.value is not None else "" for c in cells]
                while values and not values[-1]:
                    values.pop()
                sample.append(values)
            candidates = [
                (header_score(values, sample[index + 1] if index + 1 < len(sample) else []), -index)
                for index, values in enumerate(sample[:HEADER_SCAN_LIMIT])
                if values
            ]
            if not candidates:
                raise ValueError(tr("Arkusz jest pusty."))
            score, index = max(candidates)
            if score < 0:
                raise ValueError(
                    tr(
                        "Nie znaleziono tabeli. Podaj numer wiersza z nazwami kolumn i sprawdź separator."
                    )
                )
            header_row = -index + 1
        iterator = worksheet.iter_rows(min_row=header_row)
        first = next(iterator, None)
        if first is None or not any(c.value is not None for c in first):
            raise ValueError(tr("Wiersz nagłówków {row} nie istnieje w pliku.", row=header_row))
        headers = [cell_value(c).lstrip("\ufeff") for c in first]
        while headers and not headers[-1]:
            headers.pop()
        original_headers = headers
        headers = unique_headers(original_headers)
        rows, source_rows, row_errors = [], [], {}
        for line, cells in enumerate(iterator, header_row + 1):
            if line - header_row > 200000:
                raise ValueError(tr("Arkusz przekracza limit 200 000 wierszy."))
            try:
                values = [cell_value(c) for c in cells]
            except ValueError as exc:
                values = [str(c.value) if c.value is not None else "" for c in cells]
                row_errors[line] = str(exc)
            if not any(values):
                continue
            if any(values[len(headers) :]):
                row_errors[line] = tr("Wiersz {v0}: dane poza kolumnami z nagłówkami.", v0=line)
            source_rows.append((line, values))
            values = (values + [""] * len(headers))[: len(headers)]
            rows.append((line, dict(zip(headers, values))))
        if not rows:
            raise ValueError(tr("Arkusz nie zawiera transakcji."))
        digest = sha256(data + b"\x00sheet:" + worksheet.title.encode("utf-8")).hexdigest()
        return CSVFile(
            f"{path.name} [{worksheet.title}]",
            digest,
            headers,
            rows,
            source_rows=source_rows,
            row_errors=row_errors,
            header_row=header_row,
            header_warnings=header_warnings(original_headers, headers),
        )
    finally:
        workbook.close()


def prepare_import_batch(db, files, wallet_id, mapping, *, excluded_rows=None):
    """Simulate on a separate in-memory snapshot; never write a preview to the live DB."""
    from home_finance_cockpit.services.conflicts import annotate_conflicts

    if not files:
        raise ValueError(tr("Wybierz co najmniej jeden plik."))
    if len(files) > 50:
        raise ValueError(tr("Jedna paczka może zawierać maksymalnie 50 plików."))
    if db._depth:
        raise ValueError(tr("Poczekaj na zakończenie bieżącej operacji bazy."))
    copy = db.memory_snapshot()
    plans = []
    try:
        for file in files:
            try:
                file_mapping = dict(mapping)
                file_mapping["excluded_lines"] = sorted((excluded_rows or {}).get(file.digest, []))
                plan = prepare_import(copy, file, wallet_id, file_mapping)
            except ValueError as exc:
                raise ValueError(tr("{v0}: {v1}", v0=file.name, v1=exc)) from None
            plans.append(plan)
            if plan.rows:
                commit_import(copy, plan)
        preview = [row for plan in plans for row in plan.rows]
        annotated = iter(annotate_conflicts(preview, copy.rules(), context=db.transactions()))
        for plan in plans:
            plan.rows = [next(annotated) for _ in plan.rows]
        return plans
    finally:
        copy.close()


def commit_import_batch(db, plans):
    if not plans:
        raise ValueError(tr("Najpierw sprawdź podgląd importu."))
    if not any(plan.rows for plan in plans):
        raise ValueError(tr("Brak zakończonych transakcji do zapisania."))
    counts = []
    with db.transaction():
        for plan in plans:
            counts.append(commit_import(db, plan) if plan.rows else 0)
    return counts
