"""Bank metadata, automatic table discovery and explicit physical header rows."""

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.import_files import read_import_file
from home_finance_cockpit.services.importing import commit_import, prepare_import, suggested_mapping
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.import_dialog import ImportDialog


class PreambleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")

    def write(self, content, name="bank.csv", encoding="utf-8-sig"):
        path = self.root / name
        path.write_bytes(content.encode(encoding))
        return path

    def test_csv_auto_detects_delimiter_and_headers_after_bank_text(self):
        for separator in (";", ",", "\t"):
            content = (
                "Bank statement\r\nAccount: 1234\r\nPeriod: October 2026\r\n\r\n"
                + separator.join(("Data transakcji", "Kwota", "Opis"))
                + "\r\n"
                + separator.join(("2026-10-01", "-25", "Shop"))
                + "\r\n"
            )
            file = read_import_file(self.write(content))
            self.assertEqual(file.header_row, 5)
            self.assertEqual(file.rows[0][0], 6)
            self.assertEqual(file.rows[0][1]["Kwota"], "-25")

    def test_sparse_bank_metadata_does_not_replace_actual_operation_headers(self):
        path = self.write(
            "Data:;;\nAccount;123456;\n\nData operacji;;Kwota operacji (PLN);Opis\n2026-10-01;extra;-25;Shop\n"
        )
        file = read_import_file(path)
        self.assertEqual(file.header_row, 4)
        self.assertEqual(
            file.headers, ["Data operacji", "Column B", "Kwota operacji (PLN)", "Opis"]
        )
        self.assertEqual(file.rows[0][1]["Column B"], "extra")
        plan = prepare_import(
            self.db,
            file,
            self.wallet,
            {"date": "Data operacji", "amount": "Kwota operacji (PLN)", "description": "Opis"},
        )
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(self.db.transactions()[0]["amount_minor"], -2500)
        self.assertTrue(file.header_warnings)
        self.assertEqual(suggested_mapping(file.headers)["date"], "Data operacji")
        self.assertEqual(suggested_mapping(file.headers)["amount"], "Kwota operacji (PLN)")

    def test_blank_excel_header_is_named_and_remains_available_in_raw_preview(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Date", None, "Amount"])
        sheet.append(["2026-10-01", "Keep me", -10])
        path = self.root / "blank-header.xlsx"
        workbook.save(path)
        workbook.close()
        file = read_import_file(path)
        self.assertEqual(file.headers, ["Date", "Column B", "Amount"])
        self.assertEqual(file.rows[0][1]["Column B"], "Keep me")
        self.assertTrue(file.header_warnings)
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        dialog.load_paths([str(path)])
        self.assertIn("Column B", dialog.details.toPlainText())
        dialog.validate()
        self.assertIn("Column B", dialog.details.toPlainText())
        self.assertTrue(dialog.plans)
        self.assertFalse(dialog.save_button.isEnabled())

    def test_introductory_delimiters_do_not_beat_real_bank_headers(self):
        file = read_import_file(
            self.write(
                "Bank,Report,Details\nClient,Name,Example\n\nDate;Amount;Description\n2026-10-01;-10;Example\n"
            )
        )
        self.assertEqual(file.header_row, 4)
        self.assertEqual(file.headers, ["Date", "Amount", "Description"])

    def test_multiline_cells_keep_original_physical_line_numbers_and_exclusions(self):
        file = read_import_file(
            self.write(
                'Statement\n\nDate;Amount;Description\n2026-10-01;-10;"First\nsecond line"\n2026-10-02;-20;Other\n'
            )
        )
        self.assertEqual([line for line, _ in file.rows], [4, 6])
        mapping = suggested_mapping(file.headers)
        mapping["excluded_lines"] = [6]
        plan = prepare_import(self.db, file, self.wallet, mapping)
        self.assertEqual(len(plan.rows), 1)
        self.assertEqual(plan.rows[0]["description"], "First\nsecond line")
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(self.db.transactions()[0]["source_line"], 4)

    def test_manual_header_row_has_priority_over_earlier_table(self):
        path = self.write(
            "Date;Amount\n2026-01-01;-1\n\nCustom date;Custom amount\n2026-10-01;-20\n"
        )
        file = read_import_file(path, header_row=4)
        self.assertEqual(file.header_row, 4)
        self.assertEqual(file.headers, ["Custom date", "Custom amount"])
        self.assertEqual([line for line, _ in file.rows], [5])

    def test_manual_header_beyond_scan_limit_and_invalid_numbers(self):
        path = self.write("Bank information\n" * 220 + "Date;Amount\n2026-10-01;-10\n")
        with self.assertRaises(ValueError):
            read_import_file(path)
        self.assertEqual(read_import_file(path, header_row=221).header_row, 221)
        for value in (0, -1, True, "3", 999):
            with self.assertRaises(ValueError):
                read_import_file(path, header_row=value)

    def test_excel_auto_and_manual_start_preserve_physical_rows(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Bank statement"])
        sheet.append(["Account", "1234"])
        sheet.append([])
        sheet.append(["Date", "Amount", "Description"])
        sheet.append(["2026-10-01", -25, "Payment"])
        path = self.root / "bank.xlsx"
        workbook.save(path)
        workbook.close()
        for row in (None, 4):
            file = read_import_file(path, header_row=row)
            self.assertEqual(file.header_row, 4)
            self.assertEqual(file.rows[0][0], 5)
            self.assertEqual(file.headers, ["Date", "Amount", "Description"])
        with self.assertRaises(ValueError):
            read_import_file(path, header_row=100)

    def test_csv_encoding_and_duplicate_headers_work_after_intro(self):
        path = self.write(
            "Wyciąg z rachunku\nWłaściciel: Łukasz\nData;Kwota;Waluta;Waluta\n2026-10-01;-10;PLN;EUR\n",
            encoding="cp1250",
        )
        file = read_import_file(path)
        self.assertEqual(file.header_row, 3)
        self.assertEqual(file.encoding, "cp1250")
        self.assertEqual(file.headers, ["Data", "Kwota", "Waluta [C]", "Waluta [D]"])

    def test_dialog_explains_detected_row_and_reloads_manual_override(self):
        path = self.write("Statement\nDate;Amount\n2026-01-01;-1\nDate;Amount\n2026-10-01;-2\n")
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        dialog.load_paths([str(path)])
        self.assertEqual(dialog.file.header_row, 2)
        self.assertIn("2", dialog.details.toPlainText())
        dialog.header_mode.setCurrentIndex(dialog.header_mode.findData("manual"))
        dialog.header_row.setValue(4)
        self.assertEqual(dialog.file.header_row, 4)
        self.assertEqual(dialog.raw_preview.item(0, 1).text(), "5")
        dialog.validate()
        self.assertTrue(dialog.plans)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertEqual(len(dialog.plan.rows), 1)
        self.assertIn("4", dialog.details.toPlainText())
