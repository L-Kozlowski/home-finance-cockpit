"""Generate a complete report run in a staging directory, then publish atomically."""

import json
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock

from home_finance_cockpit.localization import tr

REPORT_LOCK = Lock()


class ReportCancelled(Exception):
    pass


def generate_reports(data, output_root, *, database_name="database", progress=None, cancelled=None):
    # Lazy imports keep application startup and the selection screen lightweight.
    from home_finance_cockpit.reports.charts import annual_charts, monthly_charts
    from home_finance_cockpit.reports.pdf import annual_pdf, monthly_pdf

    progress = progress or (lambda done, total, message: None)
    cancelled = cancelled or (lambda: False)
    total = len(data["monthly_months"]) + len(data["years"])
    if not total:
        raise ValueError(tr("Nie wybrano raportów do wygenerowania."))
    base = Path(output_root).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".generating-", dir=base))
    target = base / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    generated = []
    layouts = {}
    try:
        with REPORT_LOCK:
            for folder in (
                "reports/monthly_reports",
                "reports/year_reports",
                "charts/month_charts",
                "charts/year_charts",
            ):
                (stage / folder).mkdir(parents=True)
            for month in data["monthly_months"]:
                if cancelled():
                    raise ReportCancelled()
                progress(len(generated), total, tr("Raport miesięczny: {v0}", v0=month))
                charts = monthly_charts(
                    data["summaries"][month],
                    data["options"].currency,
                    stage / "charts/month_charts",
                )
                if cancelled():
                    raise ReportCancelled()
                relative = f"reports/monthly_reports/report_{month}.pdf"
                layouts[relative] = monthly_pdf(data, month, charts, stage / relative)
                generated.append(relative)
            for year in data["years"]:
                if cancelled():
                    raise ReportCancelled()
                progress(len(generated), total, f"Raport roczny: {year}")
                charts = annual_charts(
                    data, year, data["options"].currency, stage / "charts/year_charts"
                )
                if cancelled():
                    raise ReportCancelled()
                relative = f"reports/year_reports/report_{year}.pdf"
                layouts[relative] = annual_pdf(data, year, charts, stage / relative)
                generated.append(relative)
            if cancelled():
                raise ReportCancelled()
            manifest = dict(
                generated_at=datetime.now().isoformat(timespec="seconds"),
                scope=data["scope"],
                database_name=database_name,
                options=asdict(data["options"]),
                category_colors=data.get("category_colors", {}),
                monthly_months=data["monthly_months"],
                annual_months=data["annual_months"],
                pdfs=generated,
                layouts=layouts,
                amounts_minor={
                    m: {k: data["summaries"][m][k] for k in ("inflows", "expenses", "net", "fees")}
                    for m in data["annual_months"]
                },
            )
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            stage.rename(target)
        progress(total, total, "Raporty gotowe")
        return dict(folder=target, pdfs=[target / name for name in generated], layouts=layouts)
    finally:
        # Only our uniquely created temporary directory can be removed here.
        if stage.exists() and stage.parent == base and stage.name.startswith(".generating-"):
            shutil.rmtree(stage)
