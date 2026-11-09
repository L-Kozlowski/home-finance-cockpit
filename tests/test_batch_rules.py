import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.categorization import apply_rules, classify
from home_finance_cockpit.services.conflicts import annotate_conflicts
from home_finance_cockpit.services.import_files import (
    commit_import_batch,
    prepare_import_batch,
    read_import_file,
)
from home_finance_cockpit.services.importing import suggested_mapping
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.editors import RuleDialog
from home_finance_cockpit.ui.import_dialog import ImportDialog


class NewImportRuleTests(unittest.TestCase):
    def setUp(self):
        from home_finance_cockpit.localization import set_language

        set_language("pl")
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.fuel, self.food = self.db.save_category("Fuel"), self.db.save_category("Food")

    def test_combined_contains_and_not_contains_share_primary_keyword(self):
        self.db.save_rule(
            self.fuel,
            "description",
            "MOL",
            conditions=[dict(column_name="description", mode="not_contains", pattern="parówka")],
        )
        self.db.save_rule(
            self.food,
            "description",
            "MOL",
            conditions=[dict(column_name="description", mode="literal", pattern="parówka")],
        )
        fuel, conflict = classify(dict(description="MOL paliwo"), self.db.rules())
        self.assertEqual((fuel["category_id"], conflict), (self.fuel, False))
        food, conflict = classify(dict(description="mol PARÓWKA"), self.db.rules())
        self.assertEqual((food["category_id"], conflict), (self.food, False))
        tx = self.db.save_transaction(
            self.wallet, "-10", self.db.default_category_id(), "MOL parówka", "2026-10-01"
        )
        apply_rules(self.db, include_manual=True)
        self.assertEqual(self.db.transactions(transaction_id=tx)[0]["category_id"], self.food)

    def test_conditions_validate_duplicates_and_contradictions(self):
        with self.assertRaises(ValueError):
            self.db.save_rule(
                self.fuel,
                "description",
                "MOL",
                conditions=[dict(column_name="description", mode="not_contains", pattern="mol")],
            )
        extra = [
            dict(column_name="description", mode="not_contains", pattern="parówka"),
            dict(column_name="from_to", mode="literal", pattern="MOL"),
        ]
        self.db.save_rule(self.fuel, "description", "MOL", conditions=extra)
        with self.assertRaises(ValueError):
            self.db.save_rule(self.fuel, "description", "mol", conditions=extra[::-1])
        with self.assertRaises(ValueError):
            self.db.save_rule(
                self.fuel,
                "description",
                "MOL",
                conditions=[dict(column_name="description", mode="literal", pattern=" ")],
            )

    def test_possible_counterparty_conflict_explains_both_categories_without_changing_them(self):
        self.db.save_transaction(
            self.wallet, "-10", self.fuel, "Fuel", "2026-10-01", " MOL  STACJA "
        )
        self.db.save_transaction(self.wallet, "-5", self.food, "Food", "2026-10-02", "mol stacja")
        rows = annotate_conflicts(self.db.transactions(), self.db.rules())
        self.assertTrue(all(r["possible_conflict"] for r in rows))
        self.assertTrue(
            all(
                "Fuel" in r["conflict_explanation"] and "Food" in r["conflict_explanation"]
                for r in rows
            )
        )
        self.assertEqual({r["category_id"] for r in self.db.transactions()}, {self.food, self.fuel})
        self.assertTrue(all(not r["category_conflict"] for r in self.db.transactions()))

    def test_rule_conflict_lists_matching_rules_and_categories(self):
        self.db.save_rule(self.fuel, "description", "MOL")
        self.db.save_rule(
            self.food,
            "description",
            "MOL",
            conditions=[dict(column_name="description", mode="literal", pattern="parówka")],
        )
        tx = self.db.save_transaction(
            self.wallet, "-5", self.db.default_category_id(), "MOL parówka", "2026-10-01"
        )
        apply_rules(self.db, include_manual=True)
        row = annotate_conflicts(self.db.transactions(), self.db.rules())[0]
        self.assertEqual(row["id"], tx)
        self.assertIn("ORAZ", row["conflict_explanation"])
        self.assertIn("Fuel", row["conflict_explanation"])
        self.assertIn("Food", row["conflict_explanation"])

    def csv(self, name, values):
        path = self.folder / name
        path.write_text(
            "Date,Amount,Description,Counterparty,Currency\n"
            + "\n".join(",".join(map(str, row)) for row in values),
            encoding="utf-8",
        )
        return path

    def xlsx(self, name, values):
        path = self.folder / name
        book = Workbook()
        sheet = book.active
        sheet.title = "Transactions"
        sheet.append(["Date", "Amount", "Description", "Counterparty", "Currency"])
        for row in values:
            sheet.append(row)
        book.save(path)
        book.close()
        return path

    def test_mixed_batch_preview_is_read_only_and_deduplicates_between_files(self):
        first = ["2026-10-01", -10, "A", "MOL", "PLN"]
        second = [datetime(2026, 10, 2), -20, "B", "MOL", "PLN"]
        third = ["2026-10-03", -30, "C", "MOL", "PLN"]
        paths = [
            self.csv("first.csv", [first]),
            self.xlsx("second.xlsx", [first, second]),
            self.xlsx("third.xlsx", [second, third]),
        ]
        files = [read_import_file(path) for path in paths]
        mapping = suggested_mapping(files[0].headers)
        plans = prepare_import_batch(self.db, files, self.wallet, mapping)
        self.assertEqual(self.db.transactions(), [])
        self.assertEqual(self.db.import_history(), [])
        self.assertEqual([len(p.duplicates) for p in plans], [0, 1, 1])
        self.assertEqual(commit_import_batch(self.db, plans), [1, 1, 1])
        self.assertEqual(len(self.db.transactions()), 3)
        repeated = prepare_import_batch(self.db, files, self.wallet, mapping)
        self.assertEqual(commit_import_batch(self.db, repeated), [0, 0, 0])
        self.assertEqual(len(self.db.import_history()), 3)

    def test_earlier_dates_extend_wallet_and_invalid_file_does_not_block_others(self):
        late = read_import_file(self.csv("late.csv", [["2026-10-02", -10, "Late", "MOL", "PLN"]]))
        early = read_import_file(
            self.xlsx("early.xlsx", [["2026-10-01", -20, "Early", "MOL", "PLN"]])
        )
        mapping = suggested_mapping(late.headers)
        plans = prepare_import_batch(self.db, [late, early], self.wallet, mapping)
        self.db.save_wallet("Main", "0", "PLN", "2026-10-02", self.wallet)
        self.assertEqual(commit_import_batch(self.db, plans), [1, 1])
        self.assertEqual(self.db.wallet(self.wallet)["opening_date"], "2026-10-01")
        bad = read_import_file(self.csv("bad.csv", [["invalid", -1, "Bad", "MOL", "PLN"]]))
        new = read_import_file(self.csv("new.csv", [["2026-10-03", -30, "New", "MOL", "PLN"]]))
        plans = prepare_import_batch(self.db, [new, bad], self.wallet, mapping)
        self.assertEqual(commit_import_batch(self.db, plans), [1, 0])
        self.assertEqual(len(self.db.import_history()), 3)

    def test_excel_rejects_formulas_and_uses_explicit_sheet(self):
        path = self.xlsx("book.xlsx", [["2026-10-01", -10, "A", "MOL", "PLN"]])
        from openpyxl import load_workbook

        book = load_workbook(path)
        other = book.create_sheet("Other")
        other.append(["Date", "Amount"])
        other.append([datetime(2026, 10, 2), -99])
        book.save(path)
        book.close()
        self.assertNotEqual(
            read_import_file(path).digest, read_import_file(path, sheet="Other").digest
        )
        self.assertEqual(read_import_file(path, sheet="Other").rows[0][1]["Date"], "2026-10-02")
        with self.assertRaises(ValueError):
            read_import_file(path, sheet="Missing")
        formula = self.xlsx("formula.xlsx", [["2026-10-01", "=1+2", "A", "MOL", "PLN"]])
        file = read_import_file(formula)
        self.assertIn(2, file.row_errors)

    def test_pending_only_file_is_skipped_without_blocking_completed_file(self):
        files = []
        for name, status in (("pending.csv", "PENDING"), ("completed.csv", "COMPLETED")):
            path = self.folder / name
            path.write_text("Date,Amount,State\n2026-10-01,-10," + status + "\n", encoding="utf-8")
            files.append(read_import_file(path))
        plans = prepare_import_batch(
            self.db, files, self.wallet, suggested_mapping(files[0].headers)
        )
        self.assertEqual(commit_import_batch(self.db, plans), [0, 1])
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertEqual(len(self.db.import_history()), 1)


class BatchRuleUITests(unittest.TestCase):
    setUp = NewImportRuleTests.setUp
    csv = NewImportRuleTests.csv
    xlsx = NewImportRuleTests.xlsx

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rule_editor_plus_adds_and_persists_exclusion(self):
        dialog = RuleDialog(None, self.db, category_id=self.fuel)
        self.addCleanup(dialog.deleteLater)
        dialog.pattern.setText("MOL")
        dialog.add_condition_button.click()
        dialog.conditions[0][3].setText("parówka")
        dialog.persist()
        saved = self.db.rules()[0]
        reopened = RuleDialog(None, self.db, saved)
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.conditions[0][3].text(), "parówka")
        self.assertEqual(reopened.conditions[0][2].currentData(), "not_contains")

    def test_drop_loads_multiple_files_with_one_mapping(self):
        paths = [
            self.csv("a.csv", [["2026-10-01", -10, "A", "MOL", "PLN"]]),
            self.xlsx("b.xlsx", [["2026-10-02", -20, "B", "MOL", "PLN"]]),
        ]
        dialog = ImportDialog(None, self.db)
        self.addCleanup(dialog.deleteLater)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drop = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dialog.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(len(dialog.files), 2)
        dialog.validate()
        self.assertTrue(dialog.plans)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertEqual(dialog.preview.rowCount(), 1)
        self.assertEqual(sum(len(plan.rows) for plan in dialog.plans), 2)
        self.assertEqual(self.db.transactions(), [])

    def test_main_window_drop_opens_import_with_all_paths(self):
        from home_finance_cockpit.ui.main_window import FinanceApp

        window = FinanceApp(self.db)
        self.addCleanup(window.deleteLater)
        paths = [
            self.csv("a.csv", [["2026-10-01", -10, "A", "MOL", "PLN"]]),
            self.xlsx("b.xlsx", [["2026-10-02", -20, "B", "MOL", "PLN"]]),
        ]
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drop = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        with (
            patch("home_finance_cockpit.ui.main_window.ImportDialog.show"),
            patch("home_finance_cockpit.ui.main_window.ImportDialog.load_paths") as load,
        ):
            window.dropEvent(drop)
            self.assertTrue(drop.isAccepted())
            self.assertEqual([Path(path) for path in load.call_args.args[0]], paths)


class CompoundMigrationTests(unittest.TestCase):
    def test_real_v6_schema_migrates_with_backup_preserving_rule_and_transaction_links(self):
        import sqlite3
        from contextlib import closing

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.db"
            source = Database(":memory:")
            wallet = source.save_wallet("Main", "0", "PLN", "2026-01-01")
            root = source.save_category("Food", color="#78DFC1")
            child = source.save_category("Snacks", parent_id=root)
            rule = source.save_rule(child, "description", "MOL")
            tx = source.save_transaction(wallet, "-10", child, "MOL", "2026-10-01")
            source.set_classification_details(tx, rule, False)
            before = dict(source.transactions()[0])
            create = source.execute("SELECT sql FROM sqlite_master WHERE name='rules'").fetchone()[
                0
            ]
            old = (
                "\n".join(
                    line
                    for line in create.splitlines()
                    if not line.strip().startswith("conditions_json ")
                )
                .replace("'not_contains',", "")
                .replace("pattern,mode,conditions_json", "pattern,mode")
            )
            dump = "\n".join(
                line
                for line in source.conn.iterdump()
                if not line.startswith('INSERT INTO "rules"')
            )
            dump = dump.replace(create, old)
            old_rules = [dict(r) for r in source.rules()]
            source.close()
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(dump)
                for r in old_rules:
                    conn.execute(
                        "INSERT INTO rules(id,category_id,column_name,pattern,mode) VALUES (?,?,?,?,?)",
                        tuple(
                            r[k] for k in ("id", "category_id", "column_name", "pattern", "mode")
                        ),
                    )
                conn.execute("DROP TABLE savings_goals")
                conn.execute("DROP TABLE currency_rates")
                conn.execute("DROP TABLE exchange_settings")
                conn.execute("DROP TABLE IF EXISTS currency_history_requests")
                conn.execute("DROP TABLE IF EXISTS currency_rate_history")
                conn.execute("PRAGMA user_version=6")
                conn.commit()
            migrated = Database.open_existing(path)
            try:
                self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 12)
                self.assertEqual(dict(migrated.transactions()[0]), before)
                self.assertEqual(migrated.rules()[0]["conditions_json"], "[]")
                self.assertEqual(
                    len(list((Path(directory) / "backups").glob("before_v12_*.db"))), 1
                )
                self.assertEqual(migrated.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                migrated.close()
