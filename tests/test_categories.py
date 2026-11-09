"""Two-level category workflows and incremental overlapping CSV imports."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from home_finance_cockpit.services.categorization import apply_rules, classify
from home_finance_cockpit.services.category_files import export_category_file, import_category_file
from home_finance_cockpit.services.importing import (
    commit_import,
    prepare_import,
    read_csv,
    suggested_mapping,
)
from home_finance_cockpit.storage import Database


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")

    def json_file(self, data):
        path = self.root / "categories.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8-sig")
        return path

    def csv_plan(self, content, name="data.csv", wallet=None):
        path = self.root / name
        path.write_text(content, encoding="utf-8-sig")
        file = read_csv(path)
        return prepare_import(self.db, file, wallet or self.wallet, suggested_mapping(file.headers))

    def load_rules(self):
        return import_category_file(
            self.db, self.json_file({"Details": {"Food": {"Grocery": ["LIDL", "AUCHAN"]}}})
        )

    def test_import_tree_and_keywords_is_idempotent(self):
        self.assertEqual(self.load_rules(), (2, 2, 0))
        self.assertEqual(self.load_rules(), (0, 0, 2))
        food = self.db.find_category("Food")
        grocery = self.db.find_category("Grocery", food["id"])
        self.assertEqual(grocery["display_name"], "Food / Grocery")
        self.assertEqual({r["column_name"] for r in self.db.rules()}, {"description"})

    def test_import_merges_existing_branches_and_appends_keywords_and_categories(self):
        self.load_rules()
        food = self.db.find_category("Food")
        grocery = self.db.find_category("Grocery", food["id"])
        self.db.set_category_color(food["id"], "#22D3EE")
        added = import_category_file(
            self.db,
            self.json_file(
                {
                    "Details": {
                        "food": {"grocery": ["lidl", "NEW SHOP"], "Coffee": ["CAFE"]},
                        "Travel": {"Tickets": ["TRAIN"]},
                    }
                }
            ),
        )
        self.assertEqual(added, (3, 3, 1))
        self.assertEqual(self.db.find_category("Food")["id"], food["id"])
        self.assertEqual(self.db.find_category("Grocery", food["id"])["id"], grocery["id"])
        self.assertEqual(self.db.category(food["id"])["color"], "#22D3EE")
        self.assertEqual(
            {r["pattern"] for r in self.db.rules()}, {"LIDL", "AUCHAN", "NEW SHOP", "CAFE", "TRAIN"}
        )

    def test_import_merges_names_with_extra_spaces_and_unicode_variants(self):
        root = self.db.save_category("Żywność i napoje")
        child = self.db.save_category("Sklepy spożywcze", parent_id=root)
        added = import_category_file(
            self.db,
            self.json_file(
                {
                    "Details": {
                        "Z\u0307ywność  i napoje": {"Sklepy   spożywcze": ["SHOP"]},
                    }
                }
            ),
        )
        self.assertEqual(added, (0, 1, 0))
        self.assertEqual(self.db.rules()[0]["category_id"], child)

    def test_delete_hierarchy_reassigns_transactions_and_undo_restores_everything(self):
        self.load_rules()
        food = self.db.find_category("Food")
        grocery = self.db.find_category("Grocery", food["id"])
        transaction = self.db.save_transaction(
            self.wallet, "-10", grocery["id"], "LIDL", "2026-10-01"
        )
        apply_rules(self.db, include_manual=True)
        before = dict(
            self.db.execute("SELECT * FROM transactions WHERE id=?", (transaction,)).fetchone()
        )
        self.db.delete_category_tree(food["id"])
        current = self.db.transactions()[0]
        self.assertEqual(current["category_id"], self.db.default_category_id())
        self.assertEqual(current["category_source"], "unassigned")
        self.assertIsNone(current["matched_rule_id"])
        self.assertFalse(self.db.rules())
        self.assertIsNone(self.db.find_category("Food"))
        self.db.undo_delete()
        self.assertEqual(
            dict(
                self.db.execute("SELECT * FROM transactions WHERE id=?", (transaction,)).fetchone()
            ),
            before,
        )
        self.assertEqual(len(self.db.rules()), 2)
        with self.assertRaises(ValueError):
            self.db.delete_category_tree(self.db.default_category_id())

    def test_export_round_trip_preserves_empty_categories_appearance_and_compound_rules(self):
        root = self.db.save_category("Transport", color="#22D3EE", icon_name="car")
        child = self.db.save_category("Fuel", parent_id=root)
        self.db.save_category("Empty")
        self.db.save_rule(
            child,
            "description",
            "MOL",
            conditions=[dict(column_name="description", mode="not_contains", pattern="parówka")],
        )
        self.db.save_rule(root, "from_to", "BP", "exact")
        path = self.root / "export.json"
        export_category_file(self.db, path)
        with closing(Database(":memory:")) as target:
            self.assertEqual(import_category_file(target, path), (3, 2, 0))
            self.assertEqual(import_category_file(target, path), (0, 0, 2))
            category = target.find_category("Transport")
            self.assertEqual((category["color"], category["icon_name"]), ("#22D3EE", "car"))
            self.assertIsNotNone(target.find_category("Fuel", category["id"]))
            self.assertIn("parówka", target.rules()[0]["conditions_json"])
        self.assertNotIn("transactions", json.loads(path.read_text(encoding="utf-8")))

    def test_same_child_name_under_different_parents_and_same_name_as_parent(self):
        a = self.db.save_category("Medical")
        b = self.db.save_category("Travel")
        child = self.db.save_category("Medical", parent_id=a)
        self.db.save_category("Medical", parent_id=b)
        with self.assertRaises(ValueError):
            self.db.save_category("medical", parent_id=a)
        with self.assertRaises(ValueError):
            self.db.save_category("Third", parent_id=child)
        with self.assertRaises(ValueError):
            self.db.save_category("Medical", a, parent_id=b)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction():
                self.db.execute(
                    "INSERT INTO categories(name,parent_id) VALUES ('Third',?)", (child,)
                )

    def test_category_in_use_and_parent_with_children_cannot_be_deleted(self):
        self.load_rules()
        food = self.db.find_category("Food")
        grocery = self.db.find_category("Grocery", food["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete("categories", [food["id"]])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete("categories", [grocery["id"]])

    def test_apply_existing_transactions_and_bank_override(self):
        self.load_rules()
        self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "lidl",
            "2026-10-01",
            source="unassigned",
        )
        self.db.save_transaction(
            self.wallet,
            "-20",
            self.db.default_category_id(),
            "auchan",
            "2026-10-02",
            source="manual",
        )
        bank = self.db.save_category("Bank")
        self.db.save_transaction(self.wallet, "-30", bank, "LIDL", "2026-10-03", source="bank")
        self.assertEqual(apply_rules(self.db, include_bank=True), (2, 0))
        rows = self.db.transactions()
        self.assertEqual((rows[0]["category"], rows[0]["subcategory"]), ("Food", "Grocery"))
        self.assertEqual(rows[1]["category_source"], "manual")
        self.assertEqual(apply_rules(self.db, include_manual=True), (1, 0))

    def test_csv_preview_and_commit_assign_both_levels_before_bank_fallback(self):
        self.load_rules()
        plan = self.csv_plan(
            "Date,Amount,Description,Category\n2026-10-01,-10,LIDL,Incorrect bank category\n"
        )
        self.assertEqual(
            (plan.rows[0]["category_name"], plan.rows[0]["subcategory_name"]), ("Food", "Grocery")
        )
        self.assertEqual(commit_import(self.db, plan), 1)
        row = self.db.transactions()[0]
        self.assertEqual(
            (row["category"], row["subcategory"], row["category_source"]),
            ("Food", "Grocery", "rule"),
        )
        self.assertIsNone(self.db.find_category("Incorrect bank category"))

    def test_rule_uses_mapped_application_field_instead_of_raw_csv_column(self):
        import_category_file(self.db, self.json_file({"Opis": {"Account": {"Card": ["Bieżące"]}}}))
        path = self.root / "mapped.csv"
        path.write_text("Date,Amount,Produkt\n2026-10-01,-10,Bieżące\n", encoding="utf-8")
        plan = prepare_import(
            self.db,
            read_csv(path),
            self.wallet,
            {"date": "Date", "amount": "Amount", "description": "Produkt"},
        )
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(self.db.transactions()[0]["subcategory"], "Card")
        self.assertEqual(
            set(self.db.rule_columns()), {"description", "from_to", "date", "currency"}
        )

    def test_new_rules_and_category_imports_reject_unmapped_file_fields(self):
        category = self.db.save_category("Account")
        with self.assertRaises(ValueError):
            self.db.save_rule(category, "raw:Produkt", "Card")
        with self.assertRaises(ValueError):
            import_category_file(
                self.db, self.json_file({"Produkt": {"New": {"Card": ["Bieżące"]}}})
            )
        self.assertIsNone(self.db.find_category("New"))
        self.assertEqual(self.db.rules(), [])

    def test_legacy_raw_rules_do_not_match_missing_unmapped_values(self):
        category = self.db.save_category("Legacy")
        self.db.execute(
            "INSERT INTO rules(category_id,column_name,pattern,mode) VALUES (?,?,?,?)",
            (category, "raw:Private", "secret", "not_contains"),
        )
        tx = self.db.save_transaction(
            self.wallet,
            "-10",
            self.db.default_category_id(),
            "Shop",
            "2026-10-01",
            source="unassigned",
            raw_json='{"Description":"Shop"}',
        )
        apply_rules(self.db)
        self.assertEqual(
            self.db.transactions(transaction_id=tx)[0]["category_id"], self.db.default_category_id()
        )
        self.db.execute(
            "UPDATE transactions SET raw_json=? WHERE id=?",
            ('{"Private":"existing historical value"}', tx),
        )
        self.assertEqual(
            set(self.db.rule_columns()), {"description", "from_to", "date", "currency"}
        )
        self.assertIn(
            "existing historical value", self.db.transactions(transaction_id=tx)[0]["raw_json"]
        )

    def test_invalid_json_does_not_partially_add_categories(self):
        for data in (
            {"Details": {"Food": {"Grocery": ["LIDL"], "Other": ["lidl"]}}},
            {"Details": {"Food": {"Grocery": "LIDL"}}},
            {"Details": {"Food": {"Grocery": [123]}}},
        ):
            with self.assertRaises(ValueError):
                import_category_file(self.db, self.json_file(data))
            self.assertEqual(len(self.db.categories()), 1)
            self.assertEqual(len(self.db.rules()), 0)

    def test_conflicting_existing_keyword_rolls_back_whole_json_import(self):
        target = self.db.save_category("Other")
        self.db.save_rule(target, "description", "LIDL")
        with self.assertRaises(ValueError):
            self.load_rules()
        self.assertIsNone(self.db.find_category("Food"))
        self.assertEqual(len(self.db.rules()), 1)

    def test_exact_and_starts_with_conditions(self):
        base = dict(id=1, category_id=1, column_name="description", pattern="lidl", mode="exact")
        self.assertIsNotNone(classify(dict(description=" LIDL "), [base])[0])
        self.assertIsNone(classify(dict(description="LIDL Krakow"), [base])[0])
        base["mode"] = "starts_with"
        self.assertIsNotNone(classify(dict(description="LIDL Krakow"), [base])[0])
        self.assertIsNone(classify(dict(description="market LIDL"), [base])[0])

    def test_overlapping_file_adds_only_new_day_amount_and_description(self):
        first = self.csv_plan(
            "Date,Amount,Description\n2026-10-01,-10,LIDL\n2026-10-01,-20,AUCHAN\n"
        )
        self.assertEqual(commit_import(self.db, first), 2)
        second = self.csv_plan(
            "Date,Amount,Description\n2026-10-01,-20,auchan\n2026-10-01,-10,LIDL\n2026-10-01,-10,Taxi\n2026-10-02,-10,LIDL\n",
            name="overlap.csv",
        )
        self.assertEqual(len(second.duplicates), 2)
        self.assertEqual(commit_import(self.db, second), 2)
        self.assertEqual(commit_import(self.db, second), 0)
        self.assertEqual(len(self.db.transactions()), 4)

    def test_different_wallets_do_not_share_duplicate_detection(self):
        content = "Date,Amount,Description\n2026-10-01,-10,LIDL\n"
        self.assertEqual(commit_import(self.db, self.csv_plan(content)), 1)
        other = self.db.save_wallet("Other", "0", "PLN", "2026-01-01")
        self.assertEqual(commit_import(self.db, self.csv_plan(content, wallet=other)), 1)

    def test_distinct_bank_ids_keep_identical_legitimate_payments(self):
        first = self.csv_plan("Date,Amount,Description,Transaction ID\n2026-10-01,-10,LIDL,a\n")
        self.assertEqual(commit_import(self.db, first), 1)
        second = self.csv_plan(
            "Date,Amount,Description,Transaction ID\n2026-10-01,-10,LIDL,a\n2026-10-01,-10,LIDL,b\n",
            name="overlap.csv",
        )
        self.assertEqual(commit_import(self.db, second), 1)

    def test_reimport_does_not_duplicate_or_overwrite_manually_edited_bank_transaction(self):
        plan = self.csv_plan("Date,Amount,Description,Transaction ID\n2026-10-01,-10,LIDL,a\n")
        commit_import(self.db, plan)
        row = self.db.transactions()[0]
        self.db.save_transaction(
            self.wallet,
            "-12",
            self.db.default_category_id(),
            "Corrected",
            "2026-10-01",
            transaction_id=row["id"],
        )
        self.assertEqual(commit_import(self.db, plan), 0)
        self.assertEqual(self.db.transactions()[0]["amount_minor"], -1200)

    def test_same_file_can_restore_deleted_transaction_without_duplicating_others(self):
        content = "Date,Amount,Description\n2026-10-01,-10,LIDL\n2026-10-02,-20,AUCHAN\n"
        plan = self.csv_plan(content)
        commit_import(self.db, plan)
        self.db.delete("transactions", [self.db.transactions()[0]["id"]])
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.transactions()), 2)

    def test_same_file_restores_missing_occurrence_of_identical_payment(self):
        plan = self.csv_plan("Date,Amount,Description\n2026-10-01,-10,LIDL\n2026-10-01,-10,LIDL\n")
        self.assertEqual(commit_import(self.db, plan), 2)
        oldest = min(self.db.transactions(), key=lambda row: row["source_line"])
        self.db.delete("transactions", [oldest["id"]])
        self.assertEqual(commit_import(self.db, plan), 1)
        self.assertEqual(len(self.db.transactions()), 2)


class HierarchyMigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_rule_transaction_and_import_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""
                    CREATE TABLE currencies(id INTEGER PRIMARY KEY,code TEXT,symbol TEXT);
                    INSERT INTO currencies VALUES(1,'PLN','zł');
                    CREATE TABLE categories(id INTEGER PRIMARY KEY,name TEXT,is_default INTEGER);
                    INSERT INTO categories VALUES(1,'Ogólne',1),(5,'Food',0);
                    CREATE TABLE wallets(id INTEGER PRIMARY KEY,name TEXT,opening_minor INTEGER,currency TEXT,opening_date TEXT);
                    INSERT INTO wallets VALUES(7,'A',1000,'PLN','2026-01-01');
                    CREATE TABLE imports(id INTEGER PRIMARY KEY,wallet_id INTEGER,file_name TEXT,file_hash TEXT,mapping_json TEXT,imported_at TEXT,row_count INTEGER);
                    INSERT INTO imports VALUES(9,7,'a.csv','hash','{}','2026-10-01',1);
                    CREATE TABLE rules(id INTEGER PRIMARY KEY,category_id INTEGER,column_name TEXT,pattern TEXT,mode TEXT);
                    INSERT INTO rules VALUES(13,5,'description','shop','literal');
                    CREATE TABLE transactions(id INTEGER PRIMARY KEY,wallet_id INTEGER,amount_minor INTEGER,category_id INTEGER,description TEXT,
                    from_to TEXT,date TEXT,category_source TEXT,matched_rule_id INTEGER,category_conflict INTEGER,import_id INTEGER,source_line INTEGER,raw_json TEXT,external_id TEXT);
                    INSERT INTO transactions VALUES(17,7,-100,5,'shop','','2026-10-01','rule',13,0,9,2,'{}','bank-id');
                    PRAGMA user_version=1;
                """)
            db = Database.open_existing(path)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)
            row = db.transactions()[0]
            self.assertEqual(
                (
                    row["id"],
                    row["category_id"],
                    row["matched_rule_id"],
                    row["import_id"],
                    row["external_id"],
                ),
                (17, 5, 13, 9, "bank-id"),
            )
            self.assertIsNone(db.category(5)["parent_id"])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(len(list((Path(tmp) / "backups").glob("before_v12_*.db"))), 1)
            db.close()
