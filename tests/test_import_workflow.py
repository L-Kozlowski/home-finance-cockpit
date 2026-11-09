"""Partial imports, exclusions, amount fallback and atomic wallet-date adjustment."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.localization import set_language
from home_finance_cockpit.services.import_files import (
    commit_import_batch,
    prepare_import_batch,
    read_import_file,
)
from home_finance_cockpit.services.importing import commit_import, prepare_import, suggested_mapping
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.editors import select_data
from home_finance_cockpit.ui.import_dialog import ImportDialog
from home_finance_cockpit.ui.import_history import import_file_extension


class ImportWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language("pl")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Synthetic", "1000", "PLN", "2026-10-10")

    def file(self, content, name="test.csv"):
        path = self.folder / name
        path.write_text(content, encoding="utf-8")
        return read_import_file(path, delimiter=";")

    def test_fallback_only_replaces_blank_primary_and_imports_remaining_valid_rows(self):
        file = self.file(
            "Date;Amount;Backup\n2026-10-02; ;-25\n2026-10-03;0;99\n"
            "2026-10-04;bad;17\n2026-10-05;-4;-99\n"
        )
        mapping = suggested_mapping(file.headers) | {"amount_fallback": "Backup"}
        plan = prepare_import(self.db, file, self.wallet, mapping)
        self.assertEqual([row["amount_minor"] for row in plan.rows], [-2500, -400])
        self.assertEqual(set(plan.skipped_rows), {3, 4})
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-10")
        self.assertEqual(commit_import(self.db, plan), 2)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-02")
        self.assertEqual(self.db.wallet(self.wallet)["opening_minor"], 100000)

    def test_excluded_earliest_row_does_not_change_start_date_and_can_be_imported_later(self):
        file = self.file("Date;Amount\n2026-10-01;-1\n2026-10-05;-5\ninvalid;-100\n")
        mapping = suggested_mapping(file.headers)
        plan = prepare_import(self.db, file, self.wallet, mapping | {"excluded_lines": [2]})
        self.assertEqual(plan.opening_date, "2026-10-05")
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-05")
        self.assertEqual(
            commit_import(self.db, prepare_import(self.db, file, self.wallet, mapping)), 1
        )
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-01")
        self.assertEqual(len(self.db.transactions()), 2)

    def test_database_failure_rolls_back_date_history_and_transactions(self):
        file = self.file("Date;Amount\n2026-10-01;-1\n")
        plan = prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
        with patch.object(
            self.db, "save_transaction", side_effect=sqlite3.OperationalError("disk")
        ):
            with self.assertRaises(sqlite3.OperationalError):
                commit_import(self.db, plan)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-10")
        self.assertEqual(self.db.transactions(), [])
        self.assertEqual(self.db.import_history(), [])

    def test_bad_csv_field_count_does_not_discard_following_valid_records(self):
        file = self.file("Date;Amount\n2026-10-01;-1\n2026-10-02;-2;extra\n2026-10-03;-3\n")
        self.assertEqual(file.source_rows[1][1], ["2026-10-02", "-2", "extra"])
        plan = prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
        self.assertEqual(set(plan.skipped_rows), {3})
        self.assertEqual(commit_import(self.db, plan), 2)

    def test_csv_parser_recovers_after_malformed_quoted_record(self):
        file = self.file(
            "Date;Amount;Description\n2026-10-01;-1;Good\n"
            '2026-10-02;-2;"Bad"x\n2026-10-03;-3;Good again\n'
        )
        plan = prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
        self.assertNotIn(3, plan.skipped_rows)
        self.assertEqual(file.rows[1][1]["Description"], '"Bad"x')
        self.assertEqual(commit_import(self.db, plan), 3)

    def test_excel_formula_and_extra_cells_are_skipped_not_executed(self):
        book = Workbook()
        sheet = book.active
        sheet.append(["Date", "Amount"])
        sheet.append(["2026-10-01", "=1+2"])
        sheet.append(["2026-10-03", -3])
        sheet.append(["2026-10-04", -4, "extra"])
        path = self.folder / "test.xlsx"
        book.save(path)
        book.close()
        file = read_import_file(path)
        plan = prepare_import(self.db, file, self.wallet, suggested_mapping(file.headers))
        self.assertEqual(set(plan.skipped_rows), {2, 4})
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-03")

    def test_batch_simulation_skips_bad_rows_and_deduplicates_valid_ones(self):
        first = self.file("Date;Amount\n2026-10-01;-1\ninvalid;-2\n", "first.csv")
        second = self.file("Date;Amount\n2026-10-01;-1\n2026-10-02;-3\n", "second.csv")
        plans = prepare_import_batch(
            self.db, [first, second], self.wallet, suggested_mapping(first.headers)
        )
        self.assertEqual(self.db.transactions(), [])
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-10")
        self.assertEqual(commit_import_batch(self.db, plans), [1, 1])

    def test_source_preview_stays_available_and_checkbox_controls_import(self):
        file = self.file("Date;Amount;Backup\n2026-10-01;;-1\n2026-10-02;-2;\ninvalid;-3;\n")
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        dialog.load_paths([str(self.folder / file.name)])
        select_data(dialog.fields["amount_fallback"], "Backup")
        self.assertEqual(dialog.raw_preview.rowCount(), 3)
        dialog.raw_preview.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog.validate()
        self.assertEqual(dialog.raw_preview.rowCount(), 3)
        self.assertEqual(dialog.preview.rowCount(), 1)
        self.assertEqual(dialog.pages.count(), 3)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIn("wiersz 4", dialog.details.toPlainText())
        dialog.advance_step()
        dialog.advance_step()
        dialog.review_confirmation.setChecked(True)
        with patch.object(QMessageBox, "information"):
            dialog.save()
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-02")

    def test_raw_pagination_keeps_exclusions_past_first_500_rows(self):
        file = self.file(
            "Date;Amount;Description\n" + "\n".join(f"2026-10-01;-1;Row {i}" for i in range(501))
        )
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        dialog.load_paths([str(self.folder / file.name)])
        dialog.raw_next.click()
        self.assertEqual(dialog.raw_preview.rowCount(), 1)
        dialog.raw_preview.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog.raw_previous.click()
        dialog.raw_next.click()
        self.assertEqual(dialog.raw_preview.item(0, 0).checkState(), Qt.CheckState.Checked)
        dialog.validate()
        self.assertEqual(len(dialog.plan.rows), 500)

    def test_unreadable_file_is_reported_below_and_other_file_can_be_saved(self):
        good = self.file("Date;Amount\n2026-10-01;-1\n")
        bad = self.folder / "bad.csv"
        bad.write_bytes(b"Date;Amount\n\x00\n")
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        with patch.object(QMessageBox, "warning") as warning:
            dialog.load_paths([str(self.folder / good.name), str(bad)])
            dialog.validate()
        warning.assert_not_called()
        self.assertTrue(dialog.plans)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIn("bad.csv", dialog.details.toPlainText())
        dialog.load_paths([str(bad)])
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertEqual(dialog.raw_preview.rowCount(), 0)
        self.assertEqual(dialog.raw_file.count(), 0)

    def test_history_badge_uses_extension_not_excel_sheet_name(self):
        for name, expected in (
            ("report.xlsx [Transactions.2026]", "XLSX"),
            ("report.xlsm [Sheet.xlsx]", "XLSM"),
            ("report [final].xlsx", "XLSX"),
            ("report.csv", "CSV"),
        ):
            self.assertEqual(import_file_extension(name), expected)
