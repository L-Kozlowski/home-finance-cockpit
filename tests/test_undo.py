import sqlite3
import unittest

from home_finance_cockpit.storage import Database


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.category = self.db.save_category("Food")

    def tx(self, amount="-10", **kwargs):
        return self.db.save_transaction(
            self.wallet, amount, self.category, "Shop", "2026-10-01", **kwargs
        )

    def test_deleted_transaction_is_restored_without_reverting_other_edits(self):
        first, second = self.tx(), self.tx("-20")
        before = dict(self.db.transactions(transaction_id=first)[0])
        self.db.delete("transactions", [first])
        self.db.set_report_inclusion(second, False)
        self.assertEqual(self.db.undo_delete(), 1)
        self.assertEqual(dict(self.db.transactions(transaction_id=first)[0]), before)
        self.assertFalse(self.db.transactions(transaction_id=second)[0]["include_in_reports"])
        self.assertFalse(self.db.can_undo_delete())

    def test_import_undo_restores_history_and_all_transaction_fields(self):
        imported = self.db.execute(
            "INSERT INTO imports(wallet_id,file_name,file_hash,mapping_json,imported_at,row_count) VALUES (?,?,?,?,?,?)",
            (self.wallet, "example.csv", "hash", "{}", "2026-10-01T10:20:30", 1),
        ).lastrowid
        tx = self.tx(import_id=imported, raw_json='{"Description":"Shop"}', external_id="bank-id")
        self.db.set_report_inclusion(tx, False)
        before = dict(self.db.transactions()[0])
        self.db.delete_import_transactions(imported, expected_count=1)
        self.assertEqual(self.db.import_history(), [])
        self.db.undo_delete()
        self.assertEqual(dict(self.db.transactions()[0]), before)
        self.assertEqual(self.db.import_history()[0]["current_count"], 1)

    def test_reused_ids_never_overwrite_new_data_and_restore_is_atomic(self):
        first, last = self.tx(), self.tx("-20")
        self.db.delete("transactions", [first, last])
        replacement = self.tx("-99")
        with self.assertRaises(ValueError):
            self.db.undo_delete()
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertEqual(self.db.transactions()[0]["id"], replacement)
        self.assertEqual(self.db.transactions()[0]["amount_minor"], -9900)
        self.assertTrue(self.db.can_undo_delete())

    def test_failed_and_rolled_back_deletions_are_not_recorded(self):
        tx = self.tx()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete("wallets", [self.wallet])
        self.assertFalse(self.db.can_undo_delete())
        with self.assertRaises(ValueError):
            with self.db.transaction():
                self.db.delete("transactions", [tx])
                raise ValueError("rollback")
        self.assertFalse(self.db.can_undo_delete())
        self.assertEqual(len(self.db.transactions()), 1)

    def test_rule_undo_restores_links_without_overwriting_later_manual_changes(self):
        tx, manual = self.tx(), self.tx()
        rule = self.db.save_rule(self.category, "description", "Shop")
        for key in (tx, manual):
            self.db.set_classification_details(key, rule, False)
        self.db.delete("rules", [rule])
        self.db.set_report_inclusion(manual, False)
        self.db.undo_delete()
        self.assertEqual(self.db.transactions(transaction_id=tx)[0]["matched_rule_id"], rule)
        self.assertIsNone(self.db.transactions(transaction_id=manual)[0]["matched_rule_id"])
