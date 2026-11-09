"""Generate real monthly/annual PDFs from a disposable copy of the demo database."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from home_finance_cockpit.localization import set_language
from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.reports.generator import generate_reports
from home_finance_cockpit.storage import Database


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/ui-concepts/implemented/reports"
    set_language("pl")
    with tempfile.TemporaryDirectory() as temporary:
        copied = Path(temporary) / "demo.db"
        shutil.copy2(root / "example/database/home_finance_demo.db", copied)
        db = Database.open_existing(copied)
        data = snapshot(db, ReportOptions(currency="PLN", year=2026, months=("2026-10",)))
        db.close()
        result = generate_reports(data, output, database_name="demo.db")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    for pdf in result["pdfs"]:
        doc = QPdfDocument(None)
        doc.load(str(pdf))
        sheet = QImage(936, ((doc.pageCount() + 2) // 3) * 436, QImage.Format.Format_RGB32)
        sheet.fill(QColor("#52677b"))
        painter = QPainter(sheet)
        for page in range(doc.pageCount()):
            painter.drawImage(
                (page % 3) * 312 + 6, (page // 3) * 436 + 6, doc.render(page, QSize(300, 424))
            )
            if page == 0:
                doc.render(page, QSize(1100, 1556)).save(str(output / f"{pdf.stem}-cover.png"))
        painter.end()
        sheet.save(str(output / f"{pdf.stem}-all.png"))
        doc.close()
    print(result["folder"])
    return app


if __name__ == "__main__":
    main()
