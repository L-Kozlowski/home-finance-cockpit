"""Removing a batch must never affect other imports or manual transactions."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from home_finance_cockpit.services.importing import (
    commit_import,
    prepare_import,
    read_csv,
    suggested_mapping,
)
from home_finance_cockpit.storage import Database


class ImportRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("A", "0", "PLN", "2026-01-01")

    def batch(self, filename, amount, wallet=None):
        path = Path(self.temp.name) / filename
        path.write_text(f"Date,Amount,Description\n2026-10-01,{amount},shop\n", encoding="utf-8")
        file = read_csv(path)
        plan = prepare_import(self.db, file, wallet or self.wallet, suggested_mapping(file.headers))
        commit_import(self.db, plan)
        import_id = self.db.execute(
            "SELECT id FROM imports WHERE file_name=? ORDER BY id DESC", (filename,)
        ).fetchone()[0]
        return import_id, plan

    def test_scoped_deletion_removes_history_and_preserves_all_unrelated_rows(self):
        first, plan = self.batch("first.csv", "-10")
        second, _ = self.batch("second.csv", "-20")
        other_wallet = self.db.save_wallet("B", "0", "PLN", "2026-01-01")
        third, _ = self.batch("first.csv", "-10", other_wallet)
        manual = self.db.save_transaction(
            self.wallet, "-10", self.db.default_category_id(), "shop", "2026-10-01"
        )
        self.assertEqual(self.db.delete_import_transactions(first, expected_count=1), 1)
        self.assertEqual(
            {r["import_id"] for r in self.db.transactions() if r["import_id"]}, {second, third}
        )
        self.assertIn(manual, {r["id"] for r in self.db.transactions()})
        self.assertNotIn(first, {r["id"] for r in self.db.import_history()})
        with self.assertRaises(ValueError):
            self.db.delete_import_transactions(first)

    def test_empty_import_can_be_removed_from_history(self):
        import_id, _ = self.batch("first.csv", "-10")
        self.db.delete("transactions", [self.db.transactions()[0]["id"]])
        self.assertEqual(self.db.delete_import_transactions(import_id, expected_count=0), 0)
        self.assertFalse(self.db.import_history())

    def test_history_delete_failure_restores_transactions(self):
        import_id, _ = self.batch("first.csv", "-10")
        self.db.execute("""CREATE TRIGGER fail_history_delete BEFORE DELETE ON imports
                           BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete_import_transactions(import_id)
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertEqual(len(self.db.import_history()), 1)

    def test_reimport_restores_removed_batch_without_duplicate_history(self):
        import_id, plan = self.batch("first.csv", "-10")
        self.db.delete_import_transactions(import_id)
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.import_history()), 1)
        self.assertEqual(self.db.import_history()[0]["current_count"], 1)
        self.assertEqual(commit_import(self.db, plan), 0)

    def test_changed_count_and_missing_import_are_rejected(self):
        import_id, _ = self.batch("first.csv", "-10")
        with self.assertRaises(ValueError):
            self.db.delete_import_transactions(import_id, expected_count=2)
        with self.assertRaises(ValueError):
            self.db.delete_import_transactions(999)
        self.assertEqual(len(self.db.transactions()), 1)

    def test_edited_or_moved_transaction_still_belongs_to_original_import(self):
        import_id, _ = self.batch("first.csv", "-10")
        row = self.db.transactions()[0]
        other = self.db.save_wallet("B", "0", "PLN", "2026-01-01")
        self.db.save_transaction(
            other, "-12", row["category_id"], "Edited", row["date"], transaction_id=row["id"]
        )
        self.assertEqual(self.db.delete_import_transactions(import_id), 1)
        self.assertFalse(self.db.transactions())

    def test_failure_during_batch_delete_rolls_back_every_row(self):
        import_id, _ = self.batch("first.csv", "-10")
        with self.db.transaction():
            self.db.save_transaction(
                self.wallet,
                "-20",
                self.db.default_category_id(),
                "other",
                "2026-10-02",
                import_id=import_id,
                source_line=3,
            )
            self.db.execute("""CREATE TRIGGER fail_batch_delete BEFORE DELETE ON transactions WHEN OLD.source_line=3
                               BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete_import_transactions(import_id)
        self.assertEqual(len(self.db.transactions()), 2)
