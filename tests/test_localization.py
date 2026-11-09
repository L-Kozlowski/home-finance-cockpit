"""Language switching and counterparty conflict explanations."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ast
import json
import tempfile
import unittest
from pathlib import Path
from string import Formatter

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from home_finance_cockpit.localization import language, set_language, tr
from home_finance_cockpit.services.conflicts import annotate_conflicts
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.main_window import FinanceApp
from home_finance_cockpit.ui.settings import SettingsDialog


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("pl")

    def test_translations_preserve_values_and_validate_language(self):
        set_language("en")
        self.assertEqual(tr("Ustawienia"), "Settings")
        self.assertEqual(tr("Możliwy konflikt"), "Possible conflict")
        self.assertEqual(tr("{name}", name="Przegląd"), "Przegląd")
        with self.assertRaises(ValueError):
            set_language("de")
        self.assertEqual(language(), "en")
        set_language("pl")
        self.assertEqual(tr("Ustawienia"), "Ustawienia")

    def test_counterparty_conflict_explained_in_both_languages(self):
        rows = [
            dict(from_to="  MOL ", category_name="Transport", subcategory_name="Paliwo"),
            dict(from_to="mol", category_name="Żywność", subcategory_name="Przekąski"),
        ]
        for code, phrase in (("pl", "Możliwy konflikt"), ("en", "Possible conflict")):
            set_language(code)
            result = annotate_conflicts(rows)
            self.assertTrue(all(r["possible_conflict"] for r in result))
            self.assertIn(phrase, result[0]["conflict_explanation"])
            self.assertIn("Żywność / Przekąski", result[0]["conflict_explanation"])
            self.assertEqual(result[0]["category_name"], "Transport")
            self.assertFalse(annotate_conflicts([rows[0]])[0]["possible_conflict"])

    def test_catalog_preserves_all_format_arguments(self):
        catalog = json.loads(
            (Path(__file__).parents[1] / "home_finance_cockpit/locales/en.json").read_text(
                encoding="utf-8"
            )
        )

        def fields(value):
            return sorted(
                (field, spec, conversion)
                for _, field, spec, conversion in Formatter().parse(value)
                if field is not None
            )

        for source, target in catalog.items():
            self.assertEqual(fields(source), fields(target), source)

    def test_catalog_covers_literal_translation_calls_and_import_help(self):
        root = Path(__file__).parents[1] / "home_finance_cockpit"
        catalog = json.loads((root / "locales/en.json").read_text(encoding="utf-8"))
        messages = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "tr"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    messages.add(node.args[0].value)
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in ("IMPORT_FIELDS", "help_text")
                    for target in node.targets
                ):
                    if isinstance(node.value, ast.Dict):
                        messages.update(
                            value.value
                            for value in node.value.values
                            if isinstance(value, ast.Constant) and isinstance(value.value, str)
                        )
        self.assertEqual(sorted(messages - catalog.keys()), [])
        self.assertTrue(all(catalog[message].strip() for message in messages))

    def test_counterparties_recent_transactions_heading_in_both_languages(self):
        from home_finance_cockpit.ui.counterparties import Counterparties

        for code, expected, unexpected in (
            ("en", "Recent transactions", "Ostatnie transakcje"),
            ("pl", "Ostatnie transakcje", "Recent transactions"),
        ):
            with self.subTest(language=code):
                set_language(code)
                owner = QWidget()
                view = Counterparties(owner)
                captions = [widget.text() for widget in view.findChildren(QLabel)]
                self.assertIn(expected, captions)
                self.assertNotIn(unexpected, captions)
                owner.deleteLater()

    def test_english_summary_chart_titles(self):
        from matplotlib.figure import Figure

        from home_finance_cockpit.services.spending import spending_snapshot
        from home_finance_cockpit.ui.analysis_summary import render_summary

        set_language("en")
        db = Database(":memory:")
        try:
            wallet = db.save_wallet("Main", "0", "PLN", "2026-01-01")
            category = db.save_category("Żywność")
            db.save_transaction(wallet, "-10", category, "Lunch", "2026-10-12", "Shop")
            data = spending_snapshot(db, "PLN", year=2026, month="2026-10", after_refunds=False)
            for key, title in (
                ("months", "Wydatki miesięczne"),
                ("categories", "Udział kategorii"),
            ):
                figure = Figure()
                render_summary(figure, key, data)
                self.assertEqual(figure.axes[0].get_title(loc="left"), tr(title))
        finally:
            db.close()

    def test_english_conflict_filter_and_inspector_use_entire_history(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("general/language", "en")
            db = Database(":memory:")
            wallet = db.save_wallet("Main", "0", "PLN", "2026-01-01")
            fuel, food = db.save_category("Paliwo"), db.save_category("Żywność")
            db.save_transaction(wallet, "-10", fuel, "Petrol", "2026-10-01", "MOL")
            db.save_transaction(wallet, "-5", food, "Snack", "2026-10-02", "mol")
            window = FinanceApp(db, settings=settings)
            try:
                page = window.transaction_page
                page.search.setText("Petrol")
                page.set_mode("conflicts")
                self.assertEqual(len(page.records), 1)
                self.assertIn("Possible conflict", page.table.item(0, 3).toolTip())
                page.inspector.load(page.records[0])
                self.assertIn("Paliwo", page.inspector.status.text())
                self.assertIn("Żywność", page.inspector.status.text())
                self.assertIn("not been changed automatically", page.inspector.status.text())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_settings_switch_live_and_persist_without_changing_database(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            db = Database(":memory:")
            wallet = db.save_wallet("Ustawienia", "0", "PLN", "2026-01-01")
            window = FinanceApp(db, settings=settings)
            dialog = None
            try:
                window.tabs.setCurrentIndex(1)
                window.transaction_search.setText("MOL")
                dialog = SettingsDialog(window)
                dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("en"))
                self.assertTrue(dialog.save())
                self.assertEqual(language(), "en")
                self.assertEqual(window.tabs.tabText(1), "Transactions")
                self.assertEqual(window.tabs.currentIndex(), 1)
                self.assertEqual(window.transaction_search.text(), "MOL")
                self.assertEqual(dialog.sections.item(0).text(), "General")
                self.assertEqual(
                    window.db.execute("SELECT name FROM wallets WHERE id=?", (wallet,)).fetchone()[
                        0
                    ],
                    "Ustawienia",
                )
                self.assertEqual(settings.value("general/language"), "en")
                dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("pl"))
                self.assertTrue(dialog.save())
                self.assertEqual(window.tabs.tabText(1), "Transakcje")
                self.assertEqual(dialog.sections.item(0).text(), "Ogólne")
            finally:
                if dialog:
                    dialog.close()
                    dialog.deleteLater()
                window.close()
                window.deleteLater()
                self.app.processEvents()
