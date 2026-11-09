"""Repeated currency columns and Polish encodings must not lose bank-export data."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from home_finance_cockpit.services.import_columns import unique_headers
from home_finance_cockpit.services.import_files import read_import_file
from home_finance_cockpit.services.importing import commit_import, prepare_import, suggested_mapping
from home_finance_cockpit.storage import Database

HEADERS = [
    "Data transakcji",
    "Data księgowania",
    "Dane kontrahenta",
    "Tytuł",
    "Nr rachunku",
    "Nazwa banku",
    "Szczegóły",
    "Nr transakcji",
    "Kwota transakcji (waluta rachunku)",
    "Waluta",
    "Kwota blokady/zwolnienie blokady",
    "Waluta",
    "Kwota płatności w walucie",
    "Waluta",
    "Konto",
    "Saldo po transakcji",
    "Waluta",
]
VALUES = [
    "01.10.2026",
    "02.10.2026",
    "Żółty sklep",
    "Płatność kartą",
    "001234",
    "Demo bank",
    "Synthetic",
    "SYNTHETIC-1",
    "-12,34",
    "PLN",
    "0",
    "EUR",
    "-3",
    "USD",
    "Demo",
    "987,66",
    "PLN",
]


class BankImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def csv_file(self, encoding):
        path = self.folder / "synthetic.csv"
        with path.open("w", encoding=encoding, newline="") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(HEADERS)
            writer.writerow(VALUES)
        return path

    def test_csv_and_excel_preserve_preview_but_commit_only_mapped_columns(self):
        csv_path = self.csv_file("cp1250")
        xlsx_path = self.folder / "synthetic.xlsx"
        book = Workbook()
        book.active.append(HEADERS)
        book.active.append(VALUES)
        book.save(xlsx_path)
        book.close()
        for path in (csv_path, xlsx_path):
            with self.subTest(format=path.suffix):
                file = read_import_file(path)
                self.assertEqual(len(file.headers), 17)
                self.assertEqual(
                    [file.headers[i] for i in (9, 11, 13, 16)],
                    ["Waluta [J]", "Waluta [L]", "Waluta [N]", "Waluta [Q]"],
                )
                self.assertEqual(list(file.rows[0][1].values()), VALUES)
                mapping = suggested_mapping(file.headers)
                self.assertIsNone(mapping["currency"])
                mapping["currency"] = "Waluta [J]"
                db = Database(":memory:")
                try:
                    wallet = db.save_wallet("Demo", "0", "PLN", "2026-01-01")
                    wrong_currency = prepare_import(
                        db, file, wallet, mapping | {"currency": "Waluta [N]"}
                    )
                    self.assertTrue(wrong_currency.errors)
                    self.assertEqual(db.transactions(), [])
                    plan = prepare_import(db, file, wallet, mapping)
                    self.assertEqual(plan.errors, [])
                    self.assertEqual(commit_import(db, plan), 1)
                    row = db.transactions()[0]
                    self.assertEqual(row["amount_minor"], -1234)
                    self.assertEqual(row["description"], "Płatność kartą")
                    self.assertEqual(row["from_to"], "Żółty sklep")
                    self.assertEqual(row["external_id"], "SYNTHETIC-1")
                    stored = json.loads(row["raw_json"])
                    self.assertEqual(stored["Waluta [J]"], "PLN")
                    self.assertNotIn("Waluta [N]", stored)
                    self.assertEqual(
                        set(stored),
                        {
                            value
                            for key, value in mapping.items()
                            if isinstance(value, str) and value in file.headers
                        },
                    )
                finally:
                    db.close()

    def test_auto_encoding_preserves_polish_characters(self):
        for encoding, expected in (
            ("utf-8-sig", "utf-8-sig"),
            ("cp1250", "cp1250"),
            ("utf-16", "utf-16"),
        ):
            with self.subTest(encoding=encoding):
                file = read_import_file(self.csv_file(encoding))
                self.assertEqual(file.encoding, expected)
                self.assertEqual(file.rows[0][1]["Tytuł"], "Płatność kartą")

    def test_explicit_encoding_is_respected_and_does_not_replace_bad_bytes(self):
        path = self.csv_file("iso-8859-2")
        self.assertEqual(read_import_file(path, "iso-8859-2").rows[0][1]["Tytuł"], VALUES[3])
        with self.assertRaises(ValueError):
            read_import_file(self.csv_file("cp1250"), "utf-8-sig")

    def test_case_collisions_and_generated_labels_do_not_overwrite_original_columns(self):
        names = unique_headers(["Waluta", "waluta", "Waluta [A]", "Other"])
        self.assertEqual(names, ["Waluta [A] [2]", "waluta [B]", "Waluta [A]", "Other"])
        self.assertEqual(len({name.casefold() for name in names}), 4)

    def test_empty_column_gets_stable_identity_without_shifting_values(self):
        self.assertEqual(unique_headers(["Date", " ", "Amount"]), ["Date", "Column B", "Amount"])
        self.assertEqual(
            unique_headers(["Date", "", "Column B"]), ["Date", "Column B [2]", "Column B"]
        )

    def test_duplicate_columns_have_identical_ids_in_csv_and_excel(self):
        file = read_import_file(self.csv_file("utf-8"))
        self.assertEqual(file.headers, unique_headers(HEADERS))
