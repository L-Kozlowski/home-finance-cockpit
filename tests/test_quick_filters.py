"""Quick filter menus, shared amount drafts and selectable table data."""

import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.amount_range import amount_range
from home_finance_cockpit.storage import Database
from home_finance_cockpit.ui.analyses import AnalysesTab
from home_finance_cockpit.ui.common import fill_table, table
from home_finance_cockpit.ui.filters import FiltersDialog


class QuickFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.wallet = self.db.save_wallet("Main", "0", "PLN", "2026-01-01")
        self.other = self.db.save_wallet("Cash", "0", "PLN", "2026-01-01")
        self.db.save_currency("EUR", "Euro")
        self.db.save_wallet("Euro", "0", "EUR", "2026-01-01")
        category = self.db.default_category_id()
        for amount in ("-10", "-100", "5"):
            self.db.save_transaction(self.wallet, amount, category, "Shop", "2026-10-01")
        self.page = AnalysesTab(self.db)
        self.page.render_current = Mock()
        self.addCleanup(self.page.deleteLater)

    def test_period_tiles_and_dialog_share_state(self):
        tiles = self.page.quick_filters
        tiles.choose_period("this_month")
        dialog = FiltersDialog(self.page)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.preset.currentData(), "this_month")
        dialog.choose_period("last_year")
        dialog.apply()
        self.assertEqual(self.page.preset.currentData(), "last_year")
        self.assertEqual(tiles.period_mode, "year")
        self.assertEqual(tiles.period_caption.text(), str(QDate.currentDate().year() - 1))

    def test_period_menu_has_five_modes_and_arrows_change_complete_periods(self):
        tiles = self.page.quick_filters
        tiles.populate("period")
        self.assertEqual(len(tiles.buttons["period"].menu().actions()), 5)
        tiles.period_anchor = QDate(2024, 1, 31)
        tiles.choose_mode("month")
        tiles.next.click()
        self.assertEqual(self.page.start.date(), QDate(2024, 2, 1))
        self.assertEqual(self.page.end.date(), QDate(2024, 2, 29))
        tiles.previous.click()
        self.assertEqual(self.page.start.date(), QDate(2024, 1, 1))
        tiles.period_anchor = QDate(2026, 1, 1)
        tiles.choose_mode("week")
        self.assertEqual(self.page.start.date(), QDate(2025, 12, 29))
        self.assertEqual(self.page.end.date(), QDate(2026, 1, 4))
        tiles.next.click()
        self.assertEqual(self.page.start.date(), QDate(2026, 1, 5))
        tiles.choose_mode("year")
        tiles.previous.click()
        self.assertEqual(self.page.start.date(), QDate(2025, 1, 1))
        self.assertEqual(self.page.end.date(), QDate(2025, 12, 31))
        tiles.choose_mode("day")
        day = self.page.start.date()
        tiles.next.click()
        self.assertEqual(self.page.start.date(), day.addDays(1))
        self.assertEqual(self.page.start.date(), self.page.end.date())
        tiles.choose_mode("all")
        self.assertEqual(self.page.preset.currentData(), "all")
        self.assertFalse(tiles.previous.isHidden())
        self.assertFalse(tiles.next.isHidden())
        self.assertFalse(tiles.previous.isEnabled())
        self.assertFalse(tiles.next.isEnabled())
        self.assertEqual(tiles.period_caption.text(), tiles.buttons["period"].text())
        tiles.previous.click()
        tiles.next.click()
        self.assertEqual(self.page.preset.currentData(), "all")

    def test_filter_order_and_clear_button_at_far_right(self):
        self.page.resize(1500, 800)
        self.page.show()
        self.app.processEvents()
        tiles = self.page.quick_filters
        self.assertGreater(tiles.period_controls.x(), tiles.buttons["currency"].geometry().right())
        widgets = [
            tiles.buttons["wallet"],
            tiles.buttons["currency"],
            tiles.buttons["period"],
            tiles.previous,
            tiles.period_caption,
            tiles.next,
        ]
        positions = [widget.mapTo(self.page, widget.rect().topLeft()).x() for widget in widgets]
        self.assertEqual(positions, sorted(positions))
        from PyQt6.QtWidgets import QPushButton

        from home_finance_cockpit.localization import tr

        clear = next(
            button
            for button in self.page.findChildren(QPushButton)
            if button.text() == tr("Wyczyść filtry")
        )
        self.assertGreater(clear.mapTo(self.page, clear.rect().topLeft()).x(), positions[-1])

    def test_wallet_and_currency_menus_use_current_choices(self):
        tiles = self.page.quick_filters
        tiles.populate("wallet")
        action = next(a for a in tiles.buttons["wallet"].menu().actions() if a.text() == "Cash")
        action.trigger()
        self.assertEqual(self.page.wallet.currentData(), self.other)
        tiles.populate("currency")
        next(a for a in tiles.buttons["currency"].menu().actions() if a.text() == "EUR").trigger()
        self.assertEqual(self.page.currency.currentData(), "EUR")
        self.assertEqual(self.page.wallet.count(), 2)

    def test_amount_range_is_draft_until_applied_and_filters_analysis(self):
        dialog = FiltersDialog(self.page)
        self.addCleanup(dialog.deleteLater)
        dialog.amount_min.setText("-50,00")
        dialog.amount_max.setText("-1")
        self.assertEqual(self.page.amount_min.text(), "")
        dialog.apply()
        self.page.refresh(force=True)
        self.assertEqual(self.page.data["gross"], 1000)
        self.assertEqual(self.page.amount_min.text(), "-50,00")
        dialog.reset_filters()
        dialog.apply()
        self.page.refresh(force=True)
        self.assertEqual(self.page.data["gross"], 11000)
        with self.assertRaises(ValueError):
            amount_range("10", "-10")

    def test_table_copies_selected_visible_numbers_and_text(self):
        clipboard = self.app.clipboard()
        previous = clipboard.text()
        self.addCleanup(clipboard.setText, previous)
        widget = table(["Text", "Amount", "Hidden"])
        self.addCleanup(widget.deleteLater)
        fill_table(widget, [["Shop", "0", "secret"], ["Other", "-10", "secret"]])
        widget.hideColumn(2)
        widget.selectAll()
        QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(clipboard.text(), "Shop\t0\nOther\t-10")
