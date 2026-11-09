import unittest
from datetime import date

from matplotlib.figure import Figure

from home_finance_cockpit.ui.chart_dates import (
    format_chart_dates,
    format_date,
    format_timestamp,
    set_date_format,
)


class ChartDateTests(unittest.TestCase):
    def tearDown(self):
        set_date_format("dd.MM.yyyy")

    def test_formats_are_consistent_for_daily_and_monthly_axes(self):
        for value, day, month in (
            ("dd.MM.yyyy", "25.10.2026", "10.2026"),
            ("yyyy-MM-dd", "2026-10-25", "2026-10"),
            ("dd/MM/yyyy", "25/10/2026", "10/2026"),
        ):
            set_date_format(value)
            self.assertEqual(format_date("2026-10-25"), day)
            self.assertEqual(format_date("2026-10"), month)
            self.assertEqual(format_timestamp("2026-10-25T14:32:10"), day + " 14:32:10")
            figure = Figure(figsize=(12, 4))
            ax = figure.subplots()
            ax.plot([date(2026, 10, 25), date(2026, 10, 26)], [1, 2])
            format_chart_dates(figure)
            self.assertEqual(
                ax.xaxis.get_major_formatter().fmt,
                value.replace("yyyy", "%Y").replace("MM", "%m").replace("dd", "%d"),
            )
            self.assertTrue(all(t.get_rotation() == 0 for t in ax.get_xticklabels()))
            categorical = Figure().subplots()
            categorical.bar(["2026-10", "2026-11"], [1, 2])
            format_chart_dates(categorical.figure)
            self.assertEqual(categorical.xaxis.get_major_formatter()(0), month)

    def test_invalid_format_is_rejected(self):
        with self.assertRaises(ValueError):
            set_date_format("invalid")
