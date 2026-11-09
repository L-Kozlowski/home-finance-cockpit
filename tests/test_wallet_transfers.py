"""Atomic wallet moves, independent copies and import provenance."""

import sqlite3
import unittest

from home_finance_cockpit.storage import Database


class WalletTransferTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.source = self.db.save_wallet("Source", "100", "PLN", "2026-01-01")
        self.target = self.db.save_wallet("Target", "200", "PLN", "2026-01-01")
        self.category = self.db.save_category("Food")
        self.batch = self.db.execute(
            "INSERT INTO imports(wallet_id,file_name,file_hash,mapping_json,imported_at,row_count) VALUES (?,?,?,?,?,?)",
            (self.source, "bank.csv", "digest", "{}", "2026-11-05T12:00:00", 2),
        ).lastrowid
        self.ids = [
            self.db.save_transaction(
                self.source,
                amount,
                self.category,
                "Shop",
                "2026-10-01",
                import_id=self.batch,
                source_line=line,
                external_id=f"bank-{line}",
                raw_json='{"merchant":"Shop"}',
            )
            for line, amount in ((2, "-10"), (3, "-20"))
        ]
        self.db.set_report_inclusion(self.ids[0], False)

    def test_move_preserves_ids_metadata_and_balances(self):
        before = {r["id"]: dict(r) for r in self.db.transactions()}
        self.assertEqual(self.db.relocate_transactions(self.ids, self.target), self.ids)
        for row in self.db.transactions():
            original = before[row["id"]]
            for key in original:
                if key not in ("wallet_id", "wallet"):
                    self.assertEqual(row[key], original[key], key)
            self.assertEqual(row["wallet_id"], self.target)
        self.assertEqual(
            {r["id"]: r["balance"] for r in self.db.wallet_balances()},
            {self.source: 10000, self.target: 17000},
        )

    def test_copies_preserve_review_and_survive_source_import_deletion(self):
        copies = self.db.relocate_transactions(self.ids, self.target, copy=True)
        self.assertEqual(len(set(copies)), 2)
        for original_id, copy_id in zip(self.ids, copies):
            original = self.db.transactions(transaction_id=original_id)[0]
            clone = self.db.transactions(transaction_id=copy_id)[0]
            for key in (
                "amount_minor",
                "category_id",
                "raw_json",
                "include_in_reports",
                "analysis_kind",
                "category_source",
            ):
                self.assertEqual(clone[key], original[key])
            for key in ("import_id", "source_line", "external_id"):
                self.assertIsNone(clone[key])
        self.db.delete_import_transactions(self.batch)
        self.assertEqual({r["id"] for r in self.db.transactions()}, set(copies))

    def test_bank_id_collision_rolls_back_entire_selection(self):
        self.db.save_transaction(
            self.target, "-1", self.category, "Existing", "2026-10-01", external_id="bank-3"
        )
        with self.assertRaises(ValueError):
            self.db.relocate_transactions(self.ids, self.target)
        self.assertTrue(
            all(
                self.db.transactions(transaction_id=i)[0]["wallet_id"] == self.source
                for i in self.ids
            )
        )

    def test_invalid_currency_date_and_missing_row_leave_source_untouched(self):
        self.db.save_currency("EUR", "Euro")
        foreign = self.db.save_wallet("EUR", "0", "EUR", "2026-01-01")
        later = self.db.save_wallet("Later", "0", "PLN", "2026-11-01")
        for destination, ids in (
            (foreign, self.ids),
            (later, self.ids),
            (self.target, [*self.ids, 9999]),
        ):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                self.db.relocate_transactions(ids, destination)
        self.assertTrue(all(r["wallet_id"] == self.source for r in self.db.transactions()))

    def test_import_move_includes_previously_relocated_rows_and_no_unrelated_rows(self):
        third = self.db.save_wallet("Third", "0", "PLN", "2026-01-01")
        self.db.relocate_transactions(self.ids[:1], third)
        unrelated = self.db.save_transaction(
            self.source, "-1", self.category, "Manual", "2026-10-01"
        )
        self.assertEqual(self.db.move_import(self.batch, self.target), 2)
        self.assertEqual(self.db.import_history()[0]["wallet_id"], self.target)
        self.assertEqual(
            self.db.transactions(transaction_id=unrelated)[0]["wallet_id"], self.source
        )
        self.assertTrue(
            all(
                self.db.transactions(transaction_id=i)[0]["wallet_id"] == self.target
                for i in self.ids
            )
        )

    def test_import_move_failure_rolls_back_history_and_transactions(self):
        self.db.execute(
            "CREATE TRIGGER fail_move BEFORE UPDATE OF wallet_id ON imports BEGIN SELECT RAISE(ABORT, 'test'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.move_import(self.batch, self.target)
        self.assertEqual(self.db.import_history()[0]["wallet_id"], self.source)
        self.assertTrue(all(r["wallet_id"] == self.source for r in self.db.transactions()))

    def test_import_hash_collision_is_rejected(self):
        self.db.execute(
            "INSERT INTO imports(wallet_id,file_name,file_hash,mapping_json,imported_at,row_count) VALUES (?,?,?,?,?,?)",
            (self.target, "same.csv", "digest", "{}", "2026-11-05T12:00:00", 0),
        )
        with self.assertRaises(ValueError):
            self.db.move_import(self.batch, self.target)
