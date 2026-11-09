"""Public PDF entry points for the branded Cockpit report layout."""

from home_finance_cockpit.reports.cockpit import CockpitReport


def monthly_pdf(data, month, charts, path):
    # Standalone PNG exports remain available; PDF charts are sized for their panels.
    return CockpitReport(data, month, path).build()


def annual_pdf(data, year, charts, path):
    return CockpitReport(data, year, path, annual=True).build()
