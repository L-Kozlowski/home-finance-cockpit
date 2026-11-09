"""Report definitions, PDF contents and the background report workflow."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.reports.data import ReportOptions, category_comparison, snapshot
from home_finance_cockpit.reports.generator import ReportCancelled, generate_reports
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.reports import ReportGeneratorPanel

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Demo PLN", "99999", "PLN", "2025-01-01")
        self.food = self.db.save_category("Food")
        self.grocery = self.db.save_category("Grocery", parent_id=self.food)
        self.options = ReportOptions(currency="PLN", year=2026)

    def tx(self, amount, day, *, category=None, raw=None, description="Example shop", wallet=None):
        return self.db.save_transaction(
            wallet or self.wallet,
            amount,
            category or self.grocery,
            description,
            day,
            raw_json=json.dumps(raw, ensure_ascii=False) if raw is not None else None,
        )


class ReportDataTests(ReportCase):
    def test_exact_expenses_subtotals_and_signed_net_without_opening_balance(self):
        self.tx("100", "2026-09-01")
        self.tx("-60.11", "2026-09-02")
        self.tx("-50.22", "2026-09-03", category=self.db.default_category_id())
        s = snapshot(self.db, self.options)["summaries"]["2026-09"]
        self.assertEqual((s["inflows"], s["expenses"], s["net"]), (10000, 11033, -1033))
        self.assertEqual(sum(s["subcategories"].values()), 11033)
        self.assertEqual(s["uncategorized_minor"], 5022)
        self.assertIsNone(s["fees"])

    def test_yearly_scope_is_independent_of_monthly_selection(self):
        for month in (9, 10, 11):
            self.tx("-10", f"2026-{month:02d}-01")
        data = snapshot(self.db, replace(self.options, months=("2026-10",)))
        self.assertEqual(data["monthly_months"], ("2026-10",))
        self.assertEqual(data["annual_months"], ("2026-09", "2026-10", "2026-11"))

    def test_missing_month_and_zero_baseline_are_not_invented(self):
        self.tx("100", "2026-01-01")
        self.tx("-10", "2026-02-01")
        self.tx("-30", "2026-04-01")
        data = snapshot(self.db, self.options)
        self.assertEqual(data["summaries"]["2026-02"]["change"], 1000)
        self.assertIsNone(data["summaries"]["2026-02"]["change_percent"])
        self.assertIsNone(data["summaries"]["2026-04"]["change"])
        self.assertNotIn("2026-03", data["annual_months"])

    def test_previous_calendar_year_is_available_for_january_comparison(self):
        self.tx("-100", "2025-12-31")
        self.tx("-125", "2026-01-01")
        s = snapshot(self.db, self.options)["summaries"]["2026-01"]
        self.assertEqual((s["change"], s["change_percent"]), (2500, Decimal("25")))

    def test_recognized_exclusions_and_fee_availability_are_explicit(self):
        self.tx("-10", "2026-09-01", raw={"Rodzaj": "Wymiana", "Opłata": "2.00"})
        self.tx("-20", "2026-09-02", raw={"State": "PENDING"})
        self.tx("-30", "2026-09-03", raw={"State": "ZAKOŃCZONO", "Opłata": "1.50"})
        self.tx("-40", "2026-09-04")
        self.tx("-50", "2026-09-05", raw={"Fee": "bad"})
        s = snapshot(self.db, self.options)["summaries"]["2026-09"]
        self.assertEqual(
            (len(s["raw"]), len(s["rows"]), s["expenses"], s["fees"], s["fee_count"]),
            (5, 3, 12000, 150, 1),
        )
        included = snapshot(self.db, replace(self.options, exclude_recognized=False))["summaries"][
            "2026-09"
        ]
        self.assertEqual(included["expenses"], 15000)

    def test_wallet_and_currency_scope(self):
        self.tx("-10", "2026-09-01")
        other = self.db.save_wallet("Other PLN", "0", "PLN", "2026-01-01")
        self.tx("-20", "2026-09-01", wallet=other)
        self.db.save_currency("EUR", "€")
        euro = self.db.save_wallet("Euro", "0", "EUR", "2026-01-01")
        self.tx("-30", "2026-09-01", wallet=euro)
        self.assertEqual(snapshot(self.db, self.options)["summaries"]["2026-09"]["expenses"], 3000)
        self.assertEqual(
            snapshot(self.db, replace(self.options, wallet_id=self.wallet))["summaries"]["2026-09"][
                "expenses"
            ],
            1000,
        )
        self.assertEqual(
            snapshot(self.db, replace(self.options, currency="EUR"))["summaries"]["2026-09"][
                "expenses"
            ],
            3000,
        )

    def test_snapshot_is_independent_of_subsequent_database_edits(self):
        self.tx("-10", "2026-09-01")
        data = snapshot(self.db, self.options)
        self.tx("-20", "2026-09-02")
        self.assertEqual(data["summaries"]["2026-09"]["expenses"], 1000)

    def test_empty_selection_and_missing_year_are_validated(self):
        with self.assertRaises(ValueError):
            snapshot(self.db, self.options)
        self.tx("-10", "2026-09-01")
        for options in (
            replace(self.options, year=2025),
            replace(self.options, months=()),
            replace(self.options, months=("2026-08",)),
            replace(self.options, monthly=False, annual=False),
        ):
            with self.assertRaises(ValueError):
                snapshot(self.db, options)
        self.assertEqual(
            snapshot(self.db, replace(self.options, monthly=False, months=()))["years"], ("2026",)
        )

    def test_category_comparison_includes_disappearing_categories(self):
        transport = self.db.save_category("Transport")
        self.tx("-10", "2026-09-01", category=transport)
        self.tx("-20", "2026-10-01")
        comparison = category_comparison(snapshot(self.db, self.options), "2026-10")
        self.assertIn(("Transport", 1000, 0, -1000, Decimal("-100")), comparison)


@unittest.skipUnless(PdfReader, "Install requirements-dev.txt for PDF inspection")
class PDFTests(ReportCase):
    def setUp(self):
        super().setUp()
        from home_finance_cockpit.localization import language, set_language

        self.addCleanup(set_language, language())
        set_language("en")

    def test_unchecked_transaction_is_absent_from_pdf_details_and_totals(self):
        self.tx("-10", "2026-09-01", description="Included purchase")
        excluded = self.tx("-20", "2026-09-02", description="UNIQUE_OMITTED_PURCHASE")
        self.db.set_report_inclusion(excluded, False)
        data = snapshot(self.db, replace(self.options, annual=False, exclude_recognized=False))
        result = generate_reports(data, self.temp.name)
        text = "\n".join(page.extract_text() for page in PdfReader(result["pdfs"][0]).pages)
        self.assertIn("Included purchase", text)
        self.assertNotIn("UNIQUE_OMITTED_PURCHASE", text)
        self.assertEqual(data["summaries"]["2026-09"]["expenses"], 1000)

    def test_monthly_and_annual_pdf_charts_contents_totals_and_fonts(self):
        self.tx("100", "2026-09-01")
        self.tx("-110.33", "2026-09-02", description="Żółć <market> & groceries")
        self.tx("-20", "2026-10-01", category=self.db.default_category_id())
        data = snapshot(self.db, replace(self.options, months=("2026-09",)))
        result = generate_reports(data, self.temp.name, database_name="example.db")
        self.assertEqual(result["folder"].parent, Path(self.temp.name).resolve())
        self.assertRegex(result["folder"].name, r"^\d{8}_\d{6}_\d{6}$")
        self.assertEqual(len(result["pdfs"]), 2)
        self.assertEqual(len(list(result["folder"].rglob("*.png"))), 5)
        monthly = PdfReader(result["pdfs"][0])
        text = "\n".join(p.extract_text() for p in monthly.pages)
        for expected in (
            "MONTHLY REPORT",
            "September 2026",
            "CATEGORY TOTAL",
            "Grocery",
            "110.33",
            "-10.33",
            "Żółć <market> & groceries",
            "Data coverage",
        ):
            self.assertIn(expected, text)
        self.assertTrue(monthly.outline)
        embedded = [
            font.get_object()
            for page in monthly.pages
            for font in page["/Resources"]["/Font"].values()
            if font.get_object().get("/Subtype") == "/TrueType"
        ]
        self.assertTrue(embedded)
        self.assertTrue(
            all(
                "/ToUnicode" in font and "/FontFile2" in font["/FontDescriptor"]
                for font in embedded
            )
        )
        annual_text = "\n".join(p.extract_text() for p in PdfReader(result["pdfs"][1]).pages)
        self.assertIn("2026-09, 2026-10", annual_text)
        self.assertIn("130.33", annual_text)
        self.assertIn("Months without saved data", annual_text)
        manifest = json.loads((result["folder"] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["amounts_minor"]["2026-09"]["net"], -1033)
        for relative, layout in result["layouts"].items():
            reader = PdfReader(result["folder"] / relative)
            self.assertEqual(layout["pages"], len(reader.pages))
            for page_number, heading in layout["headings"]:
                content = " ".join(reader.pages[page_number - 1].extract_text().split())
                self.assertIn(" ".join(heading.split()), content)

    def test_income_only_month_and_long_original_descriptions(self):
        self.tx("10", "2026-09-01", description="Original bank description " * 170)
        result = generate_reports(
            snapshot(self.db, replace(self.options, annual=False)), self.temp.name
        )
        reader = PdfReader(result["pdfs"][0])
        text = "\n".join(p.extract_text() for p in reader.pages)
        self.assertIn("Monthly transaction detail", text)
        self.assertIn("All expenses have been assigned", text)
        self.assertGreaterEqual(len(reader.pages), 2)
        normalized = " ".join(text.split())
        self.assertEqual(normalized.count("Original bank description"), 170)

    def test_cockpit_branding_locales_and_optional_sections(self):
        from concurrent.futures import ThreadPoolExecutor

        from home_finance_cockpit.localization import set_language
        from home_finance_cockpit.reports.pdf import monthly_pdf

        self.tx("-12.34", "2026-09-01", description="Original <bank> & text")
        data = snapshot(
            self.db,
            replace(
                self.options,
                annual=False,
                transactions=False,
                uncategorized=False,
                comparison=False,
            ),
        )
        for code, heading, amount in (("pl", "Podsumowanie", "12,34"), ("en", "Overview", "12.34")):
            set_language(code)
            path = Path(self.temp.name) / f"{code}.pdf"
            # Production generation runs outside the GUI thread as well.
            with ThreadPoolExecutor(max_workers=1) as executor:
                layout = executor.submit(monthly_pdf, data, "2026-09", (), path).result()
            reader = PdfReader(path)
            text = "\n".join(p.extract_text() for p in reader.pages)
            self.assertIn("Home Finance Cockpit", text)
            self.assertIn(heading, text)
            self.assertIn(amount, text)
            self.assertNotIn("Original <bank> & text", text)
            for unwanted in (
                "Szczegóły transakcji",
                "Monthly transaction detail",
                "Wydatki do przypisania",
                "Uncategorized expenses",
                "Porównanie miesięcy",
                "Monthly comparison",
            ):
                self.assertNotIn(unwanted, text)
            self.assertTrue(reader.pages[0]["/Resources"]["/XObject"])
            self.assertGreater(layout["pages"], 1)

    def test_many_categories_ring_matches_legend_and_tables_remain_complete(self):
        from home_finance_cockpit.reports.cockpit import CockpitReport, wrap_lines

        for i in range(28):
            cat = self.db.save_category(f"UNIQUE_CATEGORY_{i:02d}", icon_name="cart")
            self.tx(str(-i - 1), "2026-09-01", category=cat)
        data = snapshot(
            self.db,
            replace(
                self.options,
                annual=False,
                transactions=False,
                uncategorized=False,
                comparison=False,
            ),
        )
        report = CockpitReport(data, "2026-09", Path(self.temp.name) / "categories.pdf")
        self.assertEqual(len(report.ring_entries()), 8)
        self.assertEqual(sum(v for _, v, _, _ in report.ring_entries()), report.s["expenses"])
        self.assertEqual(report.ring_entries()[-1][0], "Other")
        layout = report.build()
        text = "\n".join(p.extract_text() for p in PdfReader(report.path).pages)
        for i in range(28):
            self.assertIn(f"UNIQUE_CATEGORY_{i:02d}", text)
        self.assertTrue(all(y <= report.bottom for _, y in layout["table_bottoms"]))
        identifier = "LONG_IDENTIFIER_WITHOUT_SPACES" * 40
        lines = wrap_lines(identifier, "Cockpit", 8.5, 90)
        self.assertEqual("".join(lines), identifier)
        from reportlab.pdfbase import pdfmetrics

        self.assertTrue(all(pdfmetrics.stringWidth(line, "Cockpit", 8.5) <= 90 for line in lines))


class GenerationSafetyTests(ReportCase):
    def test_cancellation_and_failure_leave_no_partial_reports(self):
        self.tx("-10", "2026-09-01")
        data = snapshot(self.db, replace(self.options, annual=False))
        root = Path(self.temp.name)
        sentinel = root / "existing.pdf"
        sentinel.write_bytes(b"existing")
        with self.assertRaises(ReportCancelled):
            generate_reports(data, root, cancelled=lambda: True)
        with (
            patch(
                "home_finance_cockpit.reports.charts.monthly_charts",
                return_value=(None, None, None),
            ),
            patch(
                "home_finance_cockpit.reports.pdf.monthly_pdf", side_effect=ValueError("PDF error")
            ),
        ):
            with self.assertRaises(ValueError):
                generate_reports(data, root)
        self.assertFalse(list(root.rglob(".generating-*")))
        self.assertEqual(list(root.rglob("*.pdf")), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"existing")


class ReportUITests(ReportCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_month_selection_preserves_full_year_for_annual_report(self):
        self.tx("-10", "2026-09-01")
        self.tx("-20", "2026-10-01")
        tab = ReportGeneratorPanel(self.db)
        self.addCleanup(tab.deleteLater)
        tab.select_months(False)
        tab.monthly.setChecked(False)
        data = snapshot(self.db, tab.options())
        self.assertEqual(data["annual_months"], ("2026-09", "2026-10"))
        self.assertEqual(data["monthly_months"], ())

    def test_month_grid_and_summary_follow_selected_documents(self):
        self.tx("-10", "2026-09-01")
        self.tx("-20", "2026-10-01")
        tab = ReportGeneratorPanel(self.db)
        self.addCleanup(tab.deleteLater)
        tab.refresh_summary()
        self.assertEqual(tab.selected_monthly, ["2026-09", "2026-10"])
        self.assertEqual(tab.selected_annual, ["2026"])
        self.assertEqual(len(tab.month_buttons), 12)
        self.assertFalse(tab.month_buttons["2026-01"].isEnabled())
        tab.month_buttons["2026-09"].click()
        tab.refresh_summary()
        self.assertEqual(tab.options().months, ("2026-10",))
        self.assertEqual(tab.selected_annual, ["2026"])
        self.assertEqual(tab.summary_data["annual_months"], ("2026-09", "2026-10"))
        tab.annual.setChecked(False)
        tab.refresh_summary()
        self.assertEqual(tab.selected_annual, [])
        tab.select_months(False)
        tab.refresh_summary()
        self.assertFalse(tab.generate_button.isEnabled())
        self.assertIsNone(tab.summary_data)

    def test_summary_respects_output_validation_and_contents(self):
        self.tx("-10", "2026-09-01")
        tab = ReportGeneratorPanel(self.db)
        self.addCleanup(tab.deleteLater)
        tab.transactions.setChecked(False)
        tab.refresh_summary()
        self.assertNotIn(tab.transactions.text(), tab.summary_features.text())
        tab.output.clear()
        tab.refresh_summary()
        self.assertFalse(tab.generate_button.isEnabled())
        tab.output.setText(self.temp.name)
        tab.refresh_summary()
        self.assertTrue(tab.generate_button.isEnabled())

    def test_month_grid_keeps_selections_when_switching_years(self):
        self.tx("-10", "2026-09-01")
        self.tx("-20", "2027-01-01")
        tab = ReportGeneratorPanel(self.db)
        self.addCleanup(tab.deleteLater)
        self.assertEqual(tab.grid_year.count(), 2)
        tab.grid_year.setCurrentIndex(tab.grid_year.findData("2026"))
        tab.month_buttons["2026-09"].click()
        tab.refresh_summary()
        self.assertEqual(tab.options().months, ("2027-01",))
        self.assertEqual(tab.selected_annual, ["2026", "2027"])
        tab.grid_year.setCurrentIndex(tab.grid_year.findData("2027"))
        self.assertTrue(tab.month_buttons["2027-01"].isChecked())

    def test_pending_summary_stops_before_database_is_closed(self):
        from home_finance_cockpit.storage import Database

        db = Database(":memory:")
        self.addCleanup(db.close)
        tab = ReportGeneratorPanel(db)
        self.addCleanup(tab.deleteLater)
        tab.schedule_summary()
        self.assertTrue(tab.summary_timer.isActive())
        db.close()
        self.assertFalse(tab.summary_timer.isActive())
        tab.refresh_summary()
        self.assertTrue(tab.summary_closed)

    def test_background_generation_does_not_access_sqlite_on_worker_thread(self):
        self.tx("-10", "2026-09-01")
        tab = ReportGeneratorPanel(self.db)
        self.addCleanup(tab.deleteLater)
        tab.output.setText(self.temp.name)
        result = dict(folder=Path(self.temp.name), pdfs=[Path(self.temp.name) / "example.pdf"])
        captured = []

        def fake_generate(data, output, **kwargs):
            captured.append(data["summaries"]["2026-09"]["expenses"])
            kwargs["progress"](1, 1, "Done")
            return result

        with patch("home_finance_cockpit.ui.reports.generate_reports", side_effect=fake_generate):
            tab.generate()
            for _ in range(100):
                if not tab.is_running:
                    break
                QTest.qWait(20)
        self.assertFalse(tab.is_running)
        self.assertEqual(captured, [1000])
        self.assertTrue(tab.open_button.isEnabled())
        self.assertIn("Wygenerowano", tab.status.text())

    def test_main_window_prevents_database_close_while_report_worker_is_running(self):
        from home_finance_cockpit.ui.main_window import FinanceApp

        self.tx("-10", "2026-09-01")
        window = FinanceApp(self.db)
        self.addCleanup(window.deleteLater)
        window.show_report_generator()
        panel = window.report_generator.panel
        panel.output.setText(self.temp.name)
        release = Event()

        def fake_generate(data, output, **kwargs):
            release.wait(3)
            raise ReportCancelled()

        with patch("home_finance_cockpit.ui.reports.generate_reports", side_effect=fake_generate):
            panel.generate()
            try:
                self.assertFalse(window.close())
                self.assertTrue(self.db.wallets())
                self.assertFalse(window.menuBar().isEnabled())
                self.assertTrue(window.centralWidget().isEnabled())
                self.assertFalse(window.workspace.sidebar.isEnabled())
                self.assertTrue(panel.cancel_button.isEnabled())
            finally:
                release.set()
                for _ in range(100):
                    if not panel.is_running:
                        break
                    QTest.qWait(20)
        self.assertFalse(panel.is_running)
        self.assertTrue(window.menuBar().isEnabled())
        window.report_generator.close()
