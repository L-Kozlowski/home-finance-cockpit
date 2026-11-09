"""Guided import layout, file management and live review workflows."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from home_finance_cockpit.localization import language, set_language
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.editors import select_data
from home_finance_cockpit.ui.import_dialog import ImportDialog


class ImportWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        previous = language()
        self.addCleanup(set_language, previous)
        set_language("en")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main account", "1000", "PLN", "2026-10-10")
        self.first = self.root / "statement_oct.csv"
        self.first.write_text(
            "Bank statement\n\nDate;Amount;Backup;Description\n2026-10-01;-249.90;;Grocery\n2026-10-02;;-45;Coffee\n2026-10-03;abc;;Invalid\n2026-10-04;1250;;Transfer\n",
            encoding="utf-8",
        )
        self.second = self.root / "statement_nov.csv"
        self.second.write_text(
            "Date;Amount;Backup;Description\n2026-11-01;-15;;Book\n", encoding="utf-8"
        )

    def dialog(self):
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        dialog.resize(1450, 930)
        dialog.load_paths([str(self.first), str(self.second)])
        dialog.show()
        self.app.processEvents()
        return dialog

    def review(self, dialog):
        dialog.advance_step()
        self.assertEqual(dialog.current_step, 1)
        dialog.advance_step()
        self.assertEqual(dialog.current_step, 2)

    def test_three_distinct_pages_require_acceptance_before_any_write(self):
        dialog = self.dialog()
        self.assertEqual(dialog.pages.count(), 3)
        self.assertEqual(dialog.current_step, 0)
        self.assertTrue(dialog.raw_preview.isVisible())
        self.assertFalse(dialog.fields["date"].isVisible())
        self.assertFalse(dialog.issues_table.isVisible())
        dialog.go_to_step(2)
        dialog.save()
        self.assertEqual(dialog.current_step, 0)
        self.assertFalse(self.db.transactions())
        select_data(dialog.fields["amount_fallback"], "Backup")
        dialog.advance_step()
        self.assertTrue(dialog.fields["date"].isVisible())
        self.assertTrue(dialog.mapping_source_preview.isVisible())
        self.assertTrue(dialog.preview.isVisible())
        self.assertFalse(dialog.file_scroll.isVisible())
        self.assertFalse(dialog.issues_table.isVisible())
        dialog.save()
        self.assertFalse(self.db.transactions())
        dialog.advance_step()
        self.assertTrue(dialog.issues_table.isVisible())
        self.assertFalse(dialog.preview.isVisible())
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.save()
        self.assertFalse(self.db.transactions())
        dialog.review_confirmation.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        with patch.object(QMessageBox, "information"):
            dialog.save_button.click()
        self.assertEqual(len(self.db.transactions()), 4)
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-01")

    def test_live_mapping_and_exclusion_invalidate_previous_approval(self):
        dialog = self.dialog()
        dialog.advance_step()
        select_data(dialog.fields["amount_fallback"], "Backup")
        QTest.qWait(450)
        self.assertIn("4 ready", dialog.summary.text())
        dialog.raw_preview.item(0, 0).setCheckState(Qt.CheckState.Checked)
        QTest.qWait(450)
        self.assertIn("3 ready", dialog.summary.text())
        self.assertIn("1 excluded", dialog.summary.text())
        dialog.advance_step()
        dialog.review_confirmation.setChecked(True)
        dialog.back_button.click()
        select_data(dialog.fields["amount_fallback"], None)
        self.assertFalse(dialog.mapping_accepted)
        self.assertFalse(dialog.review_confirmation.isChecked())
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(self.db.transactions())

    def test_changes_since_review_require_another_acceptance(self):
        dialog = self.dialog()
        select_data(dialog.fields["amount_fallback"], "Backup")
        self.review(dialog)
        dialog.review_confirmation.setChecked(True)
        self.db.save_transaction(
            self.wallet, "-15", self.db.default_category_id(), "Book", "2026-11-01"
        )
        dialog.save()
        self.assertEqual(dialog.current_step, 1)
        self.assertFalse(dialog.review_confirmation.isChecked())
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertFalse(self.db.import_history())

    def test_file_removal_and_header_override_return_to_source_review(self):
        dialog = self.dialog()
        dialog.header_mode.setCurrentIndex(dialog.header_mode.findData("manual"))
        dialog.header_row.setValue(3)
        self.assertEqual(dialog.header_mode.currentData(), "manual")
        dialog.header_mode.setCurrentIndex(0)
        select_data(dialog.fields["amount_fallback"], "Backup")
        self.review(dialog)
        dialog.go_to_step(0)
        dialog.file_cards[0].remove_button.click()
        self.assertFalse(dialog.source_accepted)
        self.assertFalse(dialog.mapping_accepted)
        self.assertEqual(dialog.current_step, 0)
        self.assertEqual(len(dialog.file_cards), 1)
        self.assertEqual(dialog.fields["amount_fallback"].currentData(), "Backup")
        dialog.file_cards[0].remove_button.click()
        self.assertFalse(dialog.files)
        self.assertFalse(dialog.next_button.isEnabled())
        self.assertFalse(dialog.preview_timer.isActive())

    def test_columns_resize_and_keep_width_in_both_source_views(self):
        from PyQt6.QtWidgets import QHeaderView

        dialog = self.dialog()
        self.assertEqual(
            dialog.raw_preview.horizontalHeader().sectionResizeMode(2),
            QHeaderView.ResizeMode.Interactive,
        )
        dialog.raw_preview.setColumnWidth(2, 410)
        self.assertEqual(dialog.mapping_source_preview.columnWidth(2), 410)
        dialog.advance_step()
        self.assertEqual(dialog.raw_preview.columnWidth(2), 410)
        self.assertEqual(dialog.mapping_source_preview.columnWidth(2), 410)
        dialog.preview.setColumnWidth(3, 450)
        dialog.validate()
        self.assertEqual(dialog.preview.columnWidth(3), 450)

    def test_final_details_scroll_independently_and_actions_stay_visible(self):
        dialog = self.dialog()
        self.review(dialog)
        dialog.resize(1024, 640)
        dialog.issues_model.set_rows(
            [(self.first.name, index, f"Issue {index}") for index in range(200)]
        )
        self.app.processEvents()
        self.assertGreater(dialog.issues_table.verticalScrollBar().maximum(), 0)
        position = dialog.save_button.mapTo(dialog, dialog.save_button.rect().center())
        self.assertTrue(dialog.rect().contains(position))
        self.assertTrue(dialog.review_confirmation.isVisible())

    def test_table_splitters_allow_more_space_for_comparison(self):
        dialog = self.dialog()
        dialog.advance_step()
        before = dialog.comparison_splitter.widget(1).height()
        dialog.comparison_splitter.moveSplitter(80, 1)
        self.app.processEvents()
        self.assertGreater(dialog.comparison_splitter.widget(1).height(), before)

    def test_all_invalid_rows_can_be_reviewed_but_cannot_be_imported(self):
        path = self.root / "invalid.csv"
        path.write_text("Date;Amount\ninvalid;abc\n", encoding="utf-8")
        dialog = self.dialog()
        dialog.load_paths([str(path)])
        self.review(dialog)
        self.assertTrue(dialog.details.toPlainText())
        dialog.review_confirmation.setChecked(True)
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.save()
        self.assertFalse(self.db.transactions())

    def test_both_mapping_tables_follow_the_selected_file(self):
        dialog = self.dialog()
        select_data(dialog.fields["amount_fallback"], "Backup")
        dialog.advance_step()
        self.assertEqual(dialog.preview.rowCount(), 3)
        dialog.mapping_file.setCurrentIndex(1)
        refreshed = QSignalSpy(dialog.preview_timer.timeout)
        self.assertTrue(refreshed.wait(1500))
        self.assertEqual(dialog.raw_file.currentIndex(), 1)
        self.assertEqual(dialog.mapping_source_preview.model().rowCount(), 1)
        self.assertEqual(dialog.preview.rowCount(), 1)
        self.assertEqual(dialog.preview.item(0, 3).text(), "Book")

    def test_files_are_horizontal_and_source_values_share_one_column(self):
        dialog = self.dialog()
        first, second = dialog.file_cards
        self.assertEqual(first.y(), second.y())
        self.assertLess(first.x(), second.x())
        self.assertLess(dialog.file_bar.height(), 180)
        self.assertLess(
            dialog.file_scroll.mapTo(dialog, dialog.file_scroll.rect().bottomLeft()).y(),
            dialog.wallet.mapTo(dialog, dialog.wallet.rect().topLeft()).y(),
        )
        source = dialog.source_scroll.widget()
        self.assertEqual(
            dialog.encoding.mapTo(source, dialog.encoding.rect().topLeft()).x(),
            dialog.delimiter.mapTo(source, dialog.delimiter.rect().topLeft()).x(),
        )
        self.assertEqual(
            dialog.encoding.mapTo(source, dialog.encoding.rect().topLeft()).x(),
            dialog.header_row.mapTo(source, dialog.header_row.rect().topLeft()).x(),
        )
        dialog.advance_step()
        self.app.processEvents()
        self.assertLess(
            dialog.fields["date"].mapTo(dialog, dialog.fields["date"].rect().topLeft()).x(),
            dialog.mapping_source_preview.mapTo(
                dialog, dialog.mapping_source_preview.rect().topLeft()
            ).x(),
        )
        positions = [
            dialog.fields[key].mapTo(dialog, dialog.fields[key].rect().topLeft()).y()
            for key in (
                "date",
                "amount",
                "amount_fallback",
                "description",
                "from_to",
                "category",
                "currency",
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(set(positions)), 7)

    def test_issue_table_keeps_file_and_physical_row_separate_from_message(self):
        path = self.root / "blank-header.csv"
        path.write_text("Date;;Amount\n2026-10-01;;abc\n2026-10-02;;-5\n", encoding="utf-8")
        dialog = self.dialog()
        dialog.load_paths([str(path)])
        self.review(dialog)
        self.assertEqual(len(dialog.notice_labels), 1)
        self.assertIn("1", dialog.notice_labels[0].text())
        self.assertNotIn("Column B", dialog.notice_labels[0].text())
        errors = [(file, row, reason) for file, row, reason in dialog.issues_model.rows if row == 2]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], path.name)
        self.assertIn("amount", errors[0][2].lower())
        self.assertTrue(
            any(row is None and "Column B" in reason for _, row, reason in dialog.issues_model.rows)
        )
        self.assertTrue(
            any(
                row is None and "start date" in reason
                for _, row, reason in dialog.issues_model.rows
            )
        )
        model = dialog.issues_model
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole), path.name)

    def test_automatic_header_row_is_displayed_locked_and_varies_by_file(self):
        dialog = self.dialog()
        self.assertEqual(dialog.header_mode.currentData(), "auto")
        self.assertEqual(dialog.header_row.value(), 3)
        self.assertFalse(dialog.header_row.isEnabled())
        self.assertEqual(dialog.header_row_label.text(), "Detected row")
        dialog.raw_file.setCurrentIndex(1)
        self.assertEqual(dialog.header_row.value(), 1)
        self.assertEqual([file.header_row for file in dialog.files], [3, 1])
        dialog.raw_file.setCurrentIndex(0)
        dialog.header_mode.setCurrentIndex(dialog.header_mode.findData("manual"))
        self.assertTrue(dialog.header_row.isEnabled())
        self.assertEqual(dialog.header_row.value(), 3)
        self.assertEqual(dialog.header_row_label.text(), "Row number")
        dialog.header_mode.setCurrentIndex(dialog.header_mode.findData("auto"))
        self.assertFalse(dialog.header_row.isEnabled())
        self.assertEqual(dialog.header_row.value(), 3)
        self.assertEqual([file.header_row for file in dialog.files], [3, 1])

    def test_mapped_columns_initially_fill_viewport_and_remain_resizable(self):
        dialog = self.dialog()
        dialog.advance_step()
        self.app.processEvents()
        visible = [
            column
            for column in range(dialog.preview.columnCount())
            if not dialog.preview.isColumnHidden(column)
        ]
        self.assertAlmostEqual(
            sum(dialog.preview.columnWidth(column) for column in visible),
            dialog.preview.viewport().width(),
            delta=2,
        )
        position = 0
        header = dialog.preview.horizontalHeader()
        for column in visible:
            self.assertEqual(header.sectionViewportPosition(column), position)
            position += dialog.preview.columnWidth(column)
        dialog.preview.setColumnWidth(3, 430)
        dialog.validate()
        self.assertEqual(dialog.preview.columnWidth(3), 430)

    def test_exclude_header_and_error_row_preview_are_readable(self):
        dialog = self.dialog()
        dialog.advance_step()
        self.app.processEvents()
        title = dialog.raw_preview.horizontalHeaderItem(0).text()
        self.assertGreaterEqual(
            dialog.raw_preview.columnWidth(0),
            dialog.raw_preview.fontMetrics().horizontalAdvance(title) + 24,
        )
        self.assertEqual(dialog.mapping_position.text(), "Rows 1–4 of 4")
        tooltip = dialog.raw_preview.item(2, 0).toolTip()
        self.assertIn("abc", tooltip)
        self.assertIn("Invalid", tooltip)
        self.assertIn("Amount", tooltip)
