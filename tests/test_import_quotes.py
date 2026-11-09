"""Stray quotation marks must not discard bank transactions or later CSV rows."""

import tempfile
import unittest
from pathlib import Path

from home_finance_cockpit.services.importing import read_csv


class ImportQuoteTests(unittest.TestCase):
    def read(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bank.csv"
            path.write_text(content, encoding="utf-8", newline="")
            return read_csv(path)

    def test_inner_and_double_wrapped_literal_quotes_are_preserved(self):
        for description, expected in (
            ('"Shop "Name""', 'Shop "Name"'),
            ('""Shop""', '"Shop"'),
            ('"Bad"x', '"Bad"x'),
        ):
            with self.subTest(description=description):
                file = self.read(
                    f"Date;Amount;Description\n2026-10-01;-10;{description}\n2026-10-02;-20;Next\n"
                )
                self.assertFalse(file.row_errors)
                self.assertEqual(file.rows[0][1]["Description"], expected)
                self.assertEqual([line for line, _ in file.rows], [2, 3])

    def test_valid_escaped_quotes_separators_and_multiline_are_unchanged(self):
        file = self.read(
            'Date;Amount;Description\n2026-10-01;-10;"Shop ""Name""; first\nsecond"\n2026-10-02;-20;Next\n'
        )
        self.assertFalse(file.row_errors)
        self.assertEqual(file.rows[0][1]["Description"], 'Shop "Name"; first\nsecond')
        self.assertEqual([line for line, _ in file.rows], [2, 4])

    def test_inner_quotes_with_embedded_separator_can_be_recovered(self):
        file = self.read('Date;Amount;Description\n2026-10-01;-10;"Shop "Name"; branch"\n')
        self.assertFalse(file.row_errors)
        self.assertEqual(file.rows[0][1]["Description"], 'Shop "Name"; branch')

    def test_unclosed_quote_does_not_consume_following_transactions(self):
        file = self.read('Date;Amount;Description\n2026-10-01;-10;"Shop\n2026-10-02;-20;Next\n')
        self.assertEqual(len(file.rows), 2)
        self.assertEqual(file.rows[1][1]["Amount"], "-20")

    def test_user_bank_export_preserves_company_amount_and_trailing_columns(self):
        row = """1999-09-30;1999-09-30;" "MOBILE-TRAFFIC-DATA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ" UL. DRUŻBICKIEGO 11 61-693 POZNAŃ ";" Kraków ZTP";'00000000000000000000000000 ';"xx.";"PRZELEW  ";'000000000000000000';-4,00;PLN;;;;;99,99;PLN;;;;;"""
        headers = [
            "Date",
            "Booking date",
            "Counterparty",
            "Description",
            "Account",
            "Details",
            "Type",
            "Reference",
            "Amount",
            "Currency",
        ]
        headers += [f"Extra {i}" for i in range(len(row.split(";")) - len(headers))]
        file = self.read(";".join(headers) + "\n" + row + "\n")
        self.assertFalse(file.row_errors)
        values = file.rows[0][1]
        self.assertIn(
            '"MOBILE-TRAFFIC-DATA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ"', values["Counterparty"]
        )
        self.assertEqual(values["Description"], " Kraków ZTP")
        self.assertEqual(values["Amount"], "-4,00")
        self.assertEqual(values["Currency"], "PLN")
        self.assertEqual(file.source_rows[0][1][14], "99,99")
        self.assertEqual(len(values), len(headers))
