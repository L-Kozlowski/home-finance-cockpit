from unittest import TestCase

from home_finance_cockpit.services.analysis import summarize
from home_finance_cockpit.services.spending import spending_snapshot
from home_finance_cockpit.storage import Database


class VisualizationRateTests(TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.db.save_currency("EUR", "Euro")
        self.eur = self.db.save_wallet("Euro", "100", "EUR", "2026-01-01")
        self.pln = self.db.save_wallet("Zloty", "200", "PLN", "2026-01-01")
        self.category = self.db.save_category("Food")
        self.db.save_transaction(self.eur, "-10", self.category, "Shop", "2026-10-02")
        self.db.save_transaction(self.pln, "-20", self.category, "Shop", "2026-10-02")

    def test_pln_totals_and_charts_share_configured_rate_without_mutating_transactions(self):
        self.db.save_rate_config("EUR", "manual", "4.25")
        dashboard = summarize(self.db, currency="PLN")
        self.assertEqual(dashboard["expense"], 6250)
        self.assertEqual(dashboard["balance"], 56250)
        self.assertEqual(dashboard["balance_trend"][-1][1], 56250)
        analytics = spending_snapshot(self.db, "PLN", after_refunds=False)
        self.assertEqual(analytics["gross"], 6250)
        self.assertEqual(summarize(self.db, self.eur, currency="EUR")["expense"], 1000)
        self.assertEqual(self.db.transactions(self.eur)[0]["amount_minor"], -1000)
        self.db.save_rate_config("EUR", "manual", "4.50")
        self.assertEqual(summarize(self.db, currency="PLN")["expense"], 6500)

    def test_missing_rate_is_explicit_and_api_quote_is_used(self):
        with self.assertRaises(ValueError):
            summarize(self.db, currency="PLN")
        self.db.store_quote("EUR", "4.30", "2026-10-01")
        self.assertEqual(summarize(self.db, currency="PLN")["expense"], 6300)
