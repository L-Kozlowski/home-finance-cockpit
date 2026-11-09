"""The English showcase is reproducible, balanced and uses the real importer."""

import csv
import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.reports.generator import generate_reports
from home_finance_cockpit.services.importing import commit_import, prepare_import, read_csv
from home_finance_cockpit.storage import Database
from tools.create_demo_database import populate

EXAMPLE = Path(__file__).resolve().parents[1] / "example"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.summary = populate(self.db)
        self.setup = json.loads((EXAMPLE / "config/demo_setup.json").read_text(encoding="utf-8"))

    def test_rebuild_matches_published_database_and_totals(self):
        expected = json.loads((EXAMPLE / "expected_totals.json").read_text(encoding="utf-8"))
        normalize = lambda value: {
            **value,
            "wallets": sorted(value["wallets"], key=lambda w: w["id"]),
        }
        self.assertEqual(normalize(self.summary), normalize(expected))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "demo.db"
            shutil.copy2(EXAMPLE / "database/home_finance_demo.db", path)
            saved = Database.open_existing(path)
            try:
                self.assertEqual(len(saved.transactions()), 667)
                self.assertEqual(len(saved.import_history()), 70)
                self.assertEqual(len(saved.savings_goals()), 4)
                self.assertCountEqual(
                    [(w["name"], w["balance"]) for w in saved.wallet_balances()],
                    [(w["name"], w["balance"]) for w in self.db.wallet_balances()],
                )
            finally:
                saved.close()

    def test_ten_months_have_income_varied_expenses_and_a_real_large_drop(self):
        rows = self.db.transactions()
        self.assertEqual(sorted({r["date"][:7] for r in rows}), list(self.setup["months"]))
        self.assertEqual({r["currency"] for r in rows}, {"PLN", "USD", "EUR"})
        self.assertEqual(sum(r["analysis_kind"] == "salary" for r in rows), 12)
        self.assertTrue(any(r["analysis_kind"] == "refund" for r in rows))
        self.assertTrue(any(r["analysis_kind"] == "reimbursement" for r in rows))
        self.assertEqual(sum(bool(r["is_uncategorized"]) for r in rows), 6)
        self.assertFalse(any(r["category_conflict"] for r in rows))
        self.assertTrue(all(r["matched_rule_id"] for r in rows if r["category_source"] == "rule"))
        wealth = self.summary["monthly_wealth_pln_minor"]
        self.assertGreater(wealth["2026-03"], wealth["2026-01"])
        self.assertLess(wealth["2026-04"], wealth["2026-03"] - 3000000)
        self.assertGreater(wealth["2026-10"], wealth["2026-01"])
        for wallet in self.db.wallets():
            balance = wallet["opening_minor"]
            for row in sorted(
                [r for r in rows if r["wallet_id"] == wallet["id"]],
                key=lambda r: (r["date"], r["external_id"]),
            ):
                balance += row["amount_minor"]
                self.assertGreaterEqual(balance, 0)
        pln = snapshot(self.db, ReportOptions(currency="PLN", year=2026))
        self.assertEqual(len(pln["annual_months"]), 10)
        self.assertGreater(len({s["expenses"] for s in pln["summaries"].values()}), 8)
        self.assertTrue(
            any("Toyota" in r["description"] and r["amount_minor"] == -5200000 for r in rows)
        )

    def test_internal_transfers_have_two_legs_and_preserve_valued_wealth(self):
        rows = {r["external_id"]: r for r in self.db.transactions()}
        rates = {"PLN": Decimal(1), "EUR": Decimal("4.30"), "USD": Decimal("4.00")}
        for pair in self.setup["transfers"]:
            debit, credit = rows[pair["debit"]], rows[pair["credit"]]
            self.assertEqual(
                (debit["analysis_kind"], credit["analysis_kind"]), ("transfer", "transfer")
            )
            self.assertEqual(debit["date"], credit["date"])
            self.assertEqual(
                debit["amount_minor"] * rates[debit["currency"]]
                + credit["amount_minor"] * rates[credit["currency"]],
                0,
            )
        reports = snapshot(self.db, ReportOptions(currency="PLN", year=2026))
        self.assertFalse(
            any(
                r["analysis_kind"] == "transfer"
                for s in reports["summaries"].values()
                for r in s["rows"]
            )
        )
        self.assertEqual(sum(not r["include_in_reports"] for r in rows.values()), 4)

    def test_review_hints_are_few_old_and_absent_from_latest_twenty(self):
        from home_finance_cockpit.services.conflicts import annotate_conflicts

        rows = annotate_conflicts(self.db.transactions(), self.db.rules())
        warnings = [r for r in rows if r["possible_conflict"] or r["category_conflict"]]
        self.assertEqual(len(warnings), 3)
        self.assertTrue(
            all(r["from_to"] == "AMAZON" and r["date"] < "2026-07-01" for r in warnings)
        )
        scopes = [rows]
        scopes += [[r for r in rows if r["currency"] == code] for code in ("PLN", "EUR", "USD")]
        scopes += [
            [r for r in rows if r["wallet_id"] == wallet["id"]] for wallet in self.db.wallets()
        ]
        for scope in scopes:
            newest = sorted(scope, key=lambda r: (r["date"], r["id"]), reverse=True)[:20]
            self.assertFalse(any(r["possible_conflict"] or r["category_conflict"] for r in newest))
        self.assertEqual(sum(bool(r["is_uncategorized"]) for r in rows), 6)

    def test_all_base_files_reimport_without_duplicates_or_retained_balance_columns(self):
        wallets = {w["name"]: w["id"] for w in self.db.wallets()}
        for batch in self.setup["imports"]:
            wallet = next(w["name"] for w in self.setup["wallets"] if w["key"] == batch["wallet"])
            plan = prepare_import(
                self.db,
                read_csv(EXAMPLE / batch["file"], delimiter=batch["delimiter"]),
                wallets[wallet],
                batch["mapping"],
            )
            self.assertEqual(plan.errors, [])
            self.assertEqual(commit_import(self.db, plan), 0)
        self.assertEqual(len(self.db.transactions()), 667)
        for row in self.db.transactions():
            self.assertNotIn("Balance", json.loads(row["raw_json"] or "{}"))

    def test_overlap_validation_and_import_removal(self):
        wallet = next(w["id"] for w in self.db.wallets() if w["name"] == "Cash wallet")
        mapping = next(b["mapping"] for b in self.setup["imports"] if b["wallet"] == "cash")
        before = self.db.wallet_balances()
        path = EXAMPLE / "transactions/scenarios/cash_overlap_2026-10.csv"
        plan = prepare_import(self.db, read_csv(path), wallet, mapping)
        self.assertEqual(plan.errors, [])
        self.assertEqual(sum(r["duplicate"] for r in plan.rows), 2)
        self.assertEqual(commit_import(self.db, plan), 2)
        import_id = next(i["id"] for i in self.db.import_history() if i["file_name"] == path.name)
        self.db.delete_import_transactions(import_id)
        self.assertEqual(self.db.wallet_balances(), before)
        validation = prepare_import(
            self.db,
            read_csv(EXAMPLE / "transactions/scenarios/import_validation.csv"),
            wallet,
            mapping,
        )
        self.assertTrue(validation.errors)

    def test_excel_sheets_match_csv_without_formulas(self):
        for batch in self.setup["imports"] + [
            dict(file="transactions/scenarios/cash_overlap_2026-10.csv")
        ]:
            path = EXAMPLE / batch["file"]
            with path.open(encoding="utf-8-sig", newline="") as stream:
                csv_rows = list(csv.reader(stream, delimiter=batch.get("delimiter", ",")))
            with ZipFile(path.with_suffix(".xlsx")) as workbook:
                self.assertIsNone(workbook.testzip())
                for filename in workbook.namelist():
                    ET.fromstring(workbook.read(filename))
                sheet = ET.fromstring(workbook.read("xl/worksheets/sheet2.xml"))
                self.assertFalse(sheet.findall(".//s:f", NS))
                rows = sheet.findall("s:sheetData/s:row", NS)
                self.assertEqual(len(rows), len(csv_rows))
                for values, row in zip(csv_rows, rows):
                    for value, cell in zip(values, row.findall("s:c", NS)):
                        if cell.get("t") == "inlineStr":
                            self.assertEqual(cell.find("s:is/s:t", NS).text or "", value)
                        else:
                            self.assertEqual(Decimal(cell.find("s:v", NS).text), Decimal(value))

    def test_offline_history_goals_and_reports_in_all_currencies(self):
        self.assertEqual(len(self.db.savings_goals()), 4)
        self.assertFalse(self.db.exchange_config()["enabled"])
        for code in ("USD", "EUR"):
            history = self.db.rate_history(code, "2026-01-01", "2026-10-31")
            self.assertGreater(len(history), 200)
            self.assertTrue(all(r["source"] == "manual" for r in history))
        with tempfile.TemporaryDirectory() as folder:
            for code in ("PLN", "EUR", "USD"):
                data = snapshot(
                    self.db, ReportOptions(currency=code, year=2026, months=("2026-07",))
                )
                result = generate_reports(data, folder, database_name="showcase")
                self.assertEqual(len(result["pdfs"]), 2)
                self.assertEqual(result["folder"].parent, Path(folder).resolve())
                for path in result["pdfs"]:
                    self.assertEqual(path.read_bytes()[:5], b"%PDF-")
