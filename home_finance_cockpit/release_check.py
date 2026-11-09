"""Offline integration check executed by the actual frozen application."""

import json
import os
import tempfile
import traceback
from pathlib import Path

from home_finance_cockpit.identity import APP_RELEASE


def run_release_check(destination):
    """Use synthetic data and temporary preferences; never open the user's database."""
    result = {"release": APP_RELEASE, "passed": False, "checks": []}
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    window = None
    try:
        with tempfile.TemporaryDirectory(prefix="hfc-release-check-") as temporary:
            folder = Path(temporary)
            os.environ["HFC_DATA_DIR"] = str(folder / "profile")
            os.environ["MPLCONFIGDIR"] = str(folder / "matplotlib")
            from PyQt6.QtCore import QCoreApplication, QEvent, QSettings
            from PyQt6.QtWidgets import QApplication

            from home_finance_cockpit.localization import set_language, tr
            from home_finance_cockpit.reports.data import ReportOptions, snapshot
            from home_finance_cockpit.reports.generator import generate_reports
            from home_finance_cockpit.services.import_files import read_import_file
            from home_finance_cockpit.services.importing import commit_import, prepare_import
            from home_finance_cockpit.storage import Database
            from home_finance_cockpit.storage.encryption import PasswordRequired
            from home_finance_cockpit.ui.about import AboutPage
            from home_finance_cockpit.ui.main_window import FinanceApp
            from home_finance_cockpit.ui.theme import configure_application

            app = QApplication.instance() or QApplication([])
            configure_application(app)
            database_path = folder / "synthetic.db"
            db = Database.create_new(database_path)
            wallet = db.save_wallet("Beta wallet", "1000", "PLN", "2026-01-01")
            category = db.save_category("Synthetic category")
            db.save_transaction(
                wallet, "-25.50", category, "Synthetic purchase", "2026-09-01", "Synthetic shop"
            )
            db.save_transaction(wallet, "100", category, "Synthetic income", "2026-10-01")
            goal = db.save_savings_goal("Synthetic goal", None, "1000", "250", currency="PLN")
            db.add_goal_amount(goal, "10")
            result["checks"].append("database_transactions_and_goals")

            csv = folder / "test.csv"
            csv.write_text(
                "Date;Amount;Description\n2026-09-03;-12.50;Synthetic CSV\n", encoding="utf-8"
            )
            mapping = {"date": "Date", "amount": "Amount", "description": "Description"}
            plan = prepare_import(db, read_import_file(csv), wallet, mapping)
            assert not plan.errors, "CSV preparation failed"
            commit_import(db, plan)
            from openpyxl import Workbook

            book = Workbook()
            sheet = book.active
            sheet.append(["Date", "Amount", "Description"])
            sheet.append(["2026-09-04", "-15", "Synthetic Excel"])
            workbook = folder / "test.xlsx"
            book.save(workbook)
            book.close()
            plan = prepare_import(db, read_import_file(workbook), wallet, mapping)
            assert not plan.errors, "Excel preparation failed"
            commit_import(db, plan)
            result["checks"].append("csv_and_excel_import")

            db.change_password("beta-self-test-password")
            db.close()
            try:
                Database.open_existing(database_path)
            except PasswordRequired:
                pass
            else:
                raise AssertionError("Encrypted database opened without a password")
            db = Database.open_existing(database_path, "beta-self-test-password")
            assert len(db.transactions()) == 4
            db.change_password(None, "beta-self-test-password")
            result["checks"].append("sqlcipher_encrypt_reopen_decrypt")

            from home_finance_cockpit.services.importing import suggested_mapping
            from home_finance_cockpit.ui.import_dialog import ImportDialog

            bank_headers = [
                "Data transakcji",
                "Kwota transakcji (waluta rachunku)",
                "Waluta",
                "Waluta",
                "Tytuł",
            ]
            bank_values = ["03.10.2026", "-12,34", "PLN", "EUR", "Żółty sklep"]
            bank_csv = folder / "bank-cp1250.csv"
            bank_csv.write_text(
                ";".join(bank_headers) + "\n" + ";".join(bank_values) + "\n", encoding="cp1250"
            )
            bank_xlsx = folder / "bank.xlsx"
            book = Workbook()
            book.active.append(bank_headers)
            book.active.append(bank_values)
            book.save(bank_xlsx)
            book.close()
            for path in (bank_csv, bank_xlsx):
                file = read_import_file(path)
                assert file.headers[2:4] == ["Waluta [C]", "Waluta [D]"]
                assert list(file.rows[0][1].values()) == bank_values
                bank_mapping = suggested_mapping(file.headers)
                bank_mapping["currency"] = "Waluta [C]"
                assert not prepare_import(db, file, wallet, bank_mapping).errors
            dialog = ImportDialog(None, db)
            dialog.load_paths([bank_csv])
            assert dialog.encoding.currentData() == "auto"
            assert dialog.fields["currency"].findData("Waluta [C]") >= 0
            assert dialog.fields["currency"].findData("Waluta [D]") >= 0
            dialog.deleteLater()
            result["checks"].append("bank_duplicate_headers_encoding_and_mapping_ui")

            data = snapshot(db, ReportOptions("PLN", year=2026, months=("2026-09",), annual=False))
            report = generate_reports(data, folder / "reports", database_name="synthetic")
            assert report["pdfs"] and all(path.is_file() for path in report["pdfs"]), (
                "No PDF generated"
            )
            result["checks"].append("pdf_charts_fonts_export")

            settings = QSettings(str(folder / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("general/language", "en")
            window = FinanceApp(db, settings=settings)
            window.exchange_rates.stop()
            window.show()
            for page in range(window.tabs.count()):
                window.tabs.setCurrentIndex(page)
                app.processEvents()
                assert not window.grab().isNull(), f"Cannot render page {page}"
            window.tabs.setCurrentIndex(4)
            for tab in range(window.analyses.tabs.count()):
                window.analyses.tabs.setCurrentIndex(tab)
                app.processEvents()
                assert not window.analyses.grab().isNull(), f"Cannot render analysis {tab}"
            result["checks"].append("all_pages_and_analytics_rendered")
            for code, heading in (("pl", "Ostatnie transakcje"), ("en", "Recent transactions")):
                window.change_language(code)
                set_language(code)
                assert tr("Ostatnie transakcje") == heading
                app.processEvents()
                about = AboutPage()
                assert not about.grab().isNull()
                about.deleteLater()
            result["checks"].append("polish_english_and_about")
            window.close()
            window.deleteLater()
            window = None
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        result["passed"] = True
    except Exception:
        # Only synthetic data is involved in this explicit diagnostic command.
        result["error"] = traceback.format_exc()
        if window is not None:
            window.close()
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1
