import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest import TestCase

from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.currency_catalog import parse_catalog
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.editors import CurrencyDialog
from home_finance_cockpit.ui.startup import StartupWindow


class CatalogTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_catalog_validation_selection_edit_and_manual_rate(self):
        payload = json.dumps(
            [
                dict(
                    table="A",
                    effectiveDate="2026-01-02",
                    rates=[dict(code="EUR", currency="euro", mid=4.25)],
                )
            ]
        ).encode()
        rows = parse_catalog(payload, "A")
        self.assertEqual(rows["EUR"]["rate"], "4.25")
        with self.assertRaises(ValueError):
            parse_catalog(payload, "B")
        db = Database(":memory:")
        self.addCleanup(db.close)
        dialog = CurrencyDialog(None, db)
        self.addCleanup(dialog.deleteLater)
        dialog.catalog.rows = rows
        dialog.populate_api_currencies()
        dialog.api_currency.setCurrentIndex(dialog.api_currency.findData("EUR"))
        self.assertEqual(
            (dialog.code.text(), dialog.symbol.text(), dialog.manual_rate.text()),
            ("EUR", "euro", "4.25"),
        )
        dialog.symbol.setText("Euro savings")
        dialog.manual_rate.setText("4.1")
        dialog.persist()
        self.assertEqual(db.effective_rate("EUR")[0].__str__(), "4.25")
        self.assertEqual(
            next(r for r in db.currencies() if r["code"] == "EUR")["symbol"], "Euro savings"
        )
        dialog.rate_mode.setCurrentIndex(dialog.rate_mode.findData("manual"))
        dialog.code.setText("ABC")
        dialog.symbol.setText("Custom exchange unit")
        dialog.manual_rate.setText("2.5")
        dialog.persist()
        self.assertEqual(db.effective_rate("ABC")[0].__str__(), "2.5")
        self.assertEqual(dialog.rate_mode.currentData(), "manual")

    def test_long_startup_path_is_elided_without_losing_full_path(self):
        window = StartupWindow()
        self.addCleanup(window.deleteLater)
        path = "C:/" + ("long-directory/" * 20) + "household.db"
        window.resize(520, 380)
        window.set_last_path(path)
        self.assertIn("…", window.last_path.text())
        self.assertTrue(window.last_path.text().endswith("household.db"))
        self.assertEqual(window.last_path.toolTip(), path)
        self.assertLessEqual(
            window.last_path.fontMetrics().horizontalAdvance(window.last_path.text()),
            window.width() - 56,
        )
