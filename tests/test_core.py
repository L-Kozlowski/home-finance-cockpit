import sqlite3
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from home_finance_cockpit.domain.validation import (
    amount_label,
    currency_code,
    date_range,
    iso_date,
    money_minor,
)
from home_finance_cockpit.services.analysis import balances_by_currency, summarize
from home_finance_cockpit.services.categorization import apply_rules, classify
from home_finance_cockpit.services.importing import (
    commit_import,
    prepare_import,
    read_csv,
    suggested_mapping,
)
from home_finance_cockpit.storage.database import Database


class ValidationTests(unittest.TestCase):
    def test_exact_money_and_locale_formats(self):
        for value in (
            "1234.56",
            "1,234.56",
            "1.234,56",
            "1 234,56",
            "1\u00a0234,56",
            Decimal("1234.56"),
        ):
            with self.subTest(value=value):
                self.assertEqual(money_minor(value), 123456)
        self.assertEqual(money_minor("-0,01"), -1)
        self.assertEqual(money_minor("0.10") + money_minor("0.20"), 30)
        self.assertEqual(amount_label(-123456, "PLN"), "-1 234.56 PLN")

    def test_reject_invalid_money(self):
        for value in (
            "",
            "NaN",
            "Infinity",
            "1e2",
            "1.001",
            "1,234",
            "1 23",
            "1,2.34",
            "1.2.3",
            "99999999999999",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money_minor(value)

    def test_dates_and_ranges(self):
        for value in (
            "2026-10-16",
            "16.10.2026",
            "16/10/2026",
            "2026-10-16 12:34:56",
            "2026-10-16T12:34:56Z",
        ):
            self.assertEqual(iso_date(value), "2026-10-16")
        for value in ("2026-02-30", "", "yesterday"):
            with self.assertRaises(ValueError):
                iso_date(value)
        with self.assertRaises(ValueError):
            date_range("2026-10-02", "2026-10-01")
        self.assertEqual(currency_code(" eur "), "EUR")
        with self.assertRaises(ValueError):
            currency_code("EURO")


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "1000", "PLN", "2026-01-01")
        self.category = self.db.default_category_id()

    def tx(self, amount, day="2026-10-01", category=None, **kwargs):
        return self.db.save_transaction(
            self.wallet, amount, category or self.category, "shop", day, **kwargs
        )


class DatabaseTests(DatabaseCase):
    def test_sign_balance_and_net(self):
        self.tx("100")
        self.tx("-30", "2026-10-02")
        data = summarize(self.db)
        self.assertEqual(
            (data["balance"], data["income"], data["expense"], data["net"]),
            (107000, 10000, 3000, 7000),
        )

    def test_balance_at_end_includes_prior_history(self):
        self.tx("-100", "2026-09-01")
        self.tx("-30", "2026-10-02")
        self.tx("20", "2026-11-01")
        data = summarize(self.db, start="2026-10-01", end="2026-10-31")
        self.assertEqual((data["balance"], data["expense"], data["count"]), (87000, 3000, 1))
        self.assertEqual(summarize(self.db, end="2025-12-31")["balance"], 0)

    def test_currency_separation(self):
        self.db.save_currency("EUR", "€")
        self.db.save_wallet("Euro", "10", "EUR", "2026-01-01")
        with self.assertRaises(ValueError):
            summarize(self.db)
        grouped = balances_by_currency(self.db)
        self.assertEqual(grouped["EUR"]["balance"], 1000)
        self.assertEqual(grouped["PLN"]["balance"], 100000)

    def test_foreign_keys_and_invalid_dates_enforced(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.db.save_transaction(999, "1", self.category, "", "2026-10-01")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO transactions(wallet_id,amount_minor,category_id,date) VALUES (?,?,?,?)",
                (999, 100, self.category, "2026-10-01"),
            )
        self.db.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO transactions(wallet_id,amount_minor,category_id,date) VALUES (?,?,?,?)",
                (self.wallet, 100, self.category, "2026-02-30"),
            )
        self.db.conn.rollback()

    def test_transaction_validation(self):
        for amount, day in (
            ("0", "2026-10-01"),
            ("NaN", "2026-10-01"),
            ("1", "bad"),
            ("1", "2025-12-01"),
        ):
            with self.subTest(amount=amount, day=day), self.assertRaises(ValueError):
                self.tx(amount, day)
        self.assertEqual(len(self.db.transactions()), 0)

    def test_nested_atomic_rollback(self):
        with self.assertRaises(ValueError):
            with self.db.transaction():
                self.tx("10")
                self.db.save_category("Transient")
                raise ValueError("stop")
        self.assertFalse(self.db.transactions())
        self.assertEqual(len(self.db.categories()), 1)

    def test_wallet_validation_and_history_protection(self):
        self.tx("-10")
        with self.assertRaises(ValueError):
            self.db.save_wallet("Main", "0", "PLN", "2026-11-01", self.wallet)
        self.db.save_currency("EUR", "€")
        with self.assertRaises(ValueError):
            self.db.save_wallet("Main", "0", "EUR", "2026-01-01", self.wallet)
        euro = self.db.save_wallet("Euro", "0", "EUR", "2026-01-01")
        with self.assertRaises(ValueError):
            self.db.save_transaction(
                euro,
                "-10",
                self.category,
                "",
                "2026-10-01",
                transaction_id=self.db.transactions()[0]["id"],
            )

    def test_delete_referenced_records_is_atomic(self):
        unused = self.db.save_category("Unused")
        used = self.db.save_category("Used")
        self.tx("-10", category=used)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete("categories", [unused, used])
        self.assertIn(unused, [r["id"] for r in self.db.categories()])
        with self.assertRaises(ValueError):
            self.db.delete("categories", [self.category])

    def test_default_category_rename_does_not_break_rules(self):
        self.db.save_category("Unassigned", self.category)
        food = self.db.save_category("Food")
        self.db.save_rule(food, "description", "shop")
        self.tx("-10", source="unassigned")
        self.assertEqual(apply_rules(self.db), (1, 0))
        self.assertEqual(self.db.transactions()[0]["category_id"], food)

    def test_currency_code_change_cannot_relabel_history(self):
        cur = self.db.currencies()[0]
        with self.assertRaises(ValueError):
            self.db.save_currency("EUR", "€", cur["id"])
        self.db.save_currency("PLN", "PLN", cur["id"])
        self.assertEqual(self.db.wallet(self.wallet)["currency"], "PLN")


class ClassificationTests(DatabaseCase):
    def test_longest_match_unicode_and_conflict(self):
        food, other = self.db.save_category("Food"), self.db.save_category("Other")
        self.db.save_rule(other, "description", "ŻÓŁĆ")
        winner = self.db.save_rule(food, "description", "ŻÓŁĆ market")
        self.tx("-10", source="unassigned")
        tx_id = self.db.transactions()[0]["id"]
        self.db.execute("UPDATE transactions SET description=? WHERE id=?", ("żółć MARKET", tx_id))
        self.db.conn.commit()
        self.assertEqual(apply_rules(self.db), (1, 1))
        row = self.db.transactions()[0]
        self.assertEqual(
            (row["category_id"], row["matched_rule_id"], row["category_conflict"]),
            (food, winner, 1),
        )

    def test_manual_category_protection(self):
        food = self.db.save_category("Food")
        self.db.save_rule(food, "description", "shop")
        self.tx("-10", source="manual")
        self.assertEqual(apply_rules(self.db), (0, 0))
        self.assertEqual(self.db.transactions()[0]["category_id"], self.category)

    def test_literal_metacharacters_and_like(self):
        rule = dict(id=1, category_id=2, column_name="description", pattern="a.b", mode="literal")
        self.assertIsNone(classify(dict(description="axb"), [rule])[0])
        self.assertIsNotNone(classify(dict(description="a.b"), [rule])[0])
        rule.update(pattern="a_b%", mode="like")
        self.assertIsNotNone(classify(dict(description="prefix axb text"), [rule])[0])

    def test_rule_validation_and_deleted_rule_reclassification(self):
        food = self.db.save_category("Food")
        rule = self.db.save_rule(food, "description", "shop")
        with self.assertRaises(ValueError):
            self.db.save_rule(food, "description", "SHOP")
        with self.assertRaises(ValueError):
            self.db.save_rule(food, "invalid_column", "2026")
        with self.assertRaises(ValueError):
            self.db.save_rule(food, "description", "%%_", "like")
        self.tx("-10", source="unassigned")
        apply_rules(self.db)
        self.db.delete("rules", [rule])
        apply_rules(self.db)
        self.assertEqual(self.db.transactions()[0]["category_id"], self.category)


class ImportTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def file(self, content, name="input.csv", encoding="utf-8-sig"):
        path = Path(self.temp.name) / name
        path.write_text(content, encoding=encoding)
        return read_csv(path, encoding)

    def plan(self, content, mapping=None, name="input.csv"):
        file = self.file(content, name)
        return prepare_import(
            self.db, file, self.wallet, mapping or suggested_mapping(file.headers)
        )

    def test_bom_trimmed_headers_quoted_fields_and_provenance(self):
        plan = self.plan(
            ' Data ; Kwota ; Opis ; Waluta\n2026-10-01;-12,34;"market; groceries";PLN\n'
        )
        self.assertFalse(plan.errors)
        self.assertEqual(commit_import(self.db, plan), 1)
        tx = self.db.transactions()[0]
        self.assertEqual(
            (tx["amount_minor"], tx["source_line"], tx["description"]),
            (-1234, 2, "market; groceries"),
        )
        self.assertIn("market; groceries", tx["raw_json"])
        self.assertEqual(self.db.execute("SELECT row_count FROM imports").fetchone()[0], 1)

    def test_only_date_and_amount_required_and_ids_are_automatic(self):
        plan = self.plan(
            "Date,Amount\n2026-10-01,-10\n2026-10-02,20\n", dict(date="Date", amount="Amount")
        )
        self.assertFalse(plan.errors)
        self.assertEqual(commit_import(self.db, plan), 2)
        rows = self.db.transactions()
        self.assertEqual(len({row["id"] for row in rows}), 2)
        self.assertTrue(all(row["external_id"] is None for row in rows))
        self.assertTrue(all(row["category_source"] == "unassigned" for row in rows))

    def test_shared_optional_text_column_is_allowed(self):
        plan = self.plan(
            "Date,Amount,Description\n2026-10-01,-10,shop\n",
            dict(date="Date", amount="Amount", description="Description", from_to="Description"),
        )
        self.assertEqual(commit_import(self.db, plan), 1)
        row = self.db.transactions()[0]
        self.assertEqual((row["description"], row["from_to"]), ("shop", "shop"))

    def test_inactive_amount_columns_are_ignored(self):
        plan = self.plan(
            "Date,Amount\n2026-10-01,-10\n",
            dict(
                date="Date",
                amount="Amount",
                debit="Missing",
                credit="Missing",
                amount_mode="signed",
            ),
        )
        self.assertEqual(commit_import(self.db, plan), 1)

    def test_missing_required_mapping_names_the_field(self):
        file = self.file("Date,Amount\n2026-10-01,-10\n")
        with self.assertRaisesRegex(ValueError, "Data"):
            prepare_import(self.db, file, self.wallet, dict(amount="Amount"))

    def test_reimport_same_content_even_when_renamed(self):
        content = "Date,Amount,Description\n2026-10-01,-10,shop\n"
        commit_import(self.db, self.plan(content))
        plan = self.plan(content, name="renamed.csv")
        self.assertTrue(plan.already_imported)
        self.assertEqual(commit_import(self.db, plan), 0)
        self.assertEqual(len(self.db.transactions()), 1)

    def test_validation_skips_invalid_rows_and_imports_valid_rows(self):
        plan = self.plan("Date,Amount\n2026-10-01,-10\n2026-02-30,-20\n")
        self.assertIn("Wiersz 3", plan.errors[0])
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.transactions()), 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM imports").fetchone()[0], 1)

    def test_rollback_on_write_failure_in_middle(self):
        plan = self.plan("Date,Amount,Description\n2026-10-01,-10,a\n2026-10-02,-20,b\n")
        original = self.db.save_transaction
        calls = []

        def fail(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise sqlite3.IntegrityError("failure")
            return original(*args, **kwargs)

        with (
            patch.object(self.db, "save_transaction", side_effect=fail),
            self.assertRaises(sqlite3.IntegrityError),
        ):
            commit_import(self.db, plan)
        self.assertFalse(self.db.transactions())
        self.assertEqual(self.db.execute("SELECT count(*) FROM imports").fetchone()[0], 0)

    def test_overlap_skips_existing_count_but_keeps_additional_identical_payment(self):
        self.tx("-10")
        plan = self.plan("Date,Amount,Description\n2026-10-01,-10,shop\n2026-10-01,-10,shop\n")
        self.assertEqual(len(plan.duplicates), 1)
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.transactions()), 2)

    def test_split_debit_credit(self):
        mapping = dict(date="Date", debit="Debit", credit="Credit", amount_mode="split")
        plan = self.plan("Date;Debit;Credit\n2026-10-01;20;0\n2026-10-02;;50\n", mapping)
        self.assertEqual([r["amount_minor"] for r in plan.rows], [-2000, 5000])
        self.assertFalse(plan.errors)
        bad = self.plan("Date;Debit;Credit\n2026-10-01;20;10\n", mapping)
        self.assertTrue(bad.errors)

    def test_currency_and_status_validation(self):
        plan = self.plan(
            "Date,Amount,Currency,Status\n2026-10-01,-10,EUR,COMPLETED\n2026-10-02,-20,PLN,UNKNOWN\n2026-10-03,-10,PLN,PENDING\n"
        )
        self.assertEqual(len(plan.errors), 2)
        self.assertEqual(plan.skipped, 1)

    def test_empty_headers_and_bad_field_count(self):
        unnamed = self.file("Date,,Amount\n1,2,3\n")
        self.assertEqual(unnamed.headers, ["Date", "Column B", "Amount"])
        self.assertEqual(unnamed.rows[0][1]["Column B"], "2")
        self.assertTrue(unnamed.header_warnings)
        file = self.file("Date,Amount\n2026-10-01,1,extra\n")
        self.assertIn(2, file.row_errors)

    def test_unique_bank_id_duplicates_are_not_inserted_twice(self):
        content = "Date,Amount,Transaction ID\n2026-10-01,-10,abc\n2026-10-01,-10,abc\n"
        plan = self.plan(content)
        self.assertEqual(commit_import(self.db, plan), 1)

    def test_same_bank_id_with_conflicting_amount_is_rejected(self):
        plan = self.plan("Date,Amount,Transaction ID\n2026-10-01,-10,abc\n2026-10-01,-20,abc\n")
        self.assertTrue(plan.errors)
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.transactions()), 1)

    def test_preview_revalidated_when_data_changes(self):
        plan = self.plan("Date,Amount,Description\n2026-10-01,-10,shop\n")
        self.tx("-10")
        self.assertEqual(commit_import(self.db, plan), 0)

    def test_multiline_description_uses_physical_line_numbers(self):
        plan = self.plan(
            'Date,Amount,Description\n2026-10-01,-10,"line1\nline2"\n2026-10-02,-20,end\n'
        )
        self.assertEqual([r["source_line"] for r in plan.rows], [2, 4])


class MigrationTests(unittest.TestCase):
    def legacy(self, path, *, bad=False, old_columns=False):
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript("""
                CREATE TABLE wallets(id INTEGER PRIMARY KEY,name TEXT,opening_balance REAL,created_at TEXT);
                INSERT INTO wallets VALUES(7,'Legacy',1000,'2026-10-16');
                CREATE TABLE categories(id INTEGER PRIMARY KEY,name TEXT,created_at TEXT);
                INSERT INTO categories VALUES(3,'Ogólne','2026-10-16');
                CREATE TABLE transactions(id INTEGER PRIMARY KEY,wallet_id INTEGER,type TEXT,amount REAL,
                    category_id INTEGER,description TEXT,date TEXT);
                INSERT INTO transactions VALUES(11,7,'income',100,3,'in','2026-10-01');
                INSERT INTO transactions VALUES(12,7,'expense',30,3,'out','2026-10-02');
            """)
            if bad:
                conn.execute("UPDATE transactions SET date='invalid' WHERE id=12")
            conn.commit()

    def test_legacy_upgrade_preserves_ids_normalizes_sign_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            self.legacy(path)
            db = Database(path)
            self.assertEqual(db.wallets()[0]["id"], 7)
            self.assertEqual(db.wallets()[0]["opening_date"], "2026-10-01")
            self.assertEqual(
                {t["id"]: t["amount_minor"] for t in db.transactions()}, {11: 10000, 12: -3000}
            )
            self.assertEqual(summarize(db)["balance"], 107000)
            self.assertEqual(len(list((Path(tmp) / "backups").glob("*.db"))), 1)
            db.close()
            db = Database(path)
            self.assertEqual(len(db.transactions()), 2)
            db.close()

    def test_failed_migration_rolls_back_schema_and_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.db"
            self.legacy(path, bad=True)
            with self.assertRaises(ValueError):
                Database(path)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT amount,date FROM transactions WHERE id=12").fetchone(),
                    (30, "invalid"),
                )
                self.assertIn(
                    "opening_balance", [r[1] for r in conn.execute("PRAGMA table_info(wallets)")]
                )

    def test_backup_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.db"
            db = Database(":memory:")
            db.save_wallet("A", "10", "PLN", "2026-01-01")
            db.backup(path)
            with self.assertRaises(ValueError):
                db.backup(path)
            db.close()
            copy = Database(path)
            self.assertEqual(copy.wallets()[0]["opening_minor"], 1000)
            copy.close()


if __name__ == "__main__":
    unittest.main()
