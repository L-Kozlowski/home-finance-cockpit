"""Report selection and background generation from an immutable database snapshot."""

import sqlite3
from threading import Event

from PyQt6.QtCore import QObject, QSignalBlocker, Qt, QThread, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from home_finance_cockpit.localization import tr
from home_finance_cockpit.reports.data import ReportOptions, snapshot
from home_finance_cockpit.reports.generator import ReportCancelled, generate_reports
from home_finance_cockpit.ui.common import show_error


class ReportWorker(QObject):
    progress = pyqtSignal(int, int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, data, output, database_name):
        super().__init__()
        self.data, self.output, self.database_name = data, output, database_name
        self.cancel_event = Event()

    @pyqtSlot()
    def run(self):
        try:
            result = generate_reports(
                self.data,
                self.output,
                database_name=self.database_name,
                progress=self.progress.emit,
                cancelled=self.cancel_event.is_set,
            )
            self.succeeded.emit(result)
        except ReportCancelled:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class ReportGeneratorPanel(QWidget):
    busy_changed = pyqtSignal(bool)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.is_running = False
        self.thread = None
        self.last_result = None
        self.summary_data = None
        self.summary_closed = False
        from home_finance_cockpit.ui.report_workspace import build_workspace

        build_workspace(self)
        self.db._close_callbacks.append(self.stop_summary)
        self.currency.currentIndexChanged.connect(self.refresh_wallets)
        self.wallet.currentIndexChanged.connect(self.refresh_years)
        self.year.currentIndexChanged.connect(self.refresh_months)
        self.monthly.toggled.connect(self.months.setEnabled)
        self.refresh_filters()
        self.refresh_summary()

    def refresh_filters(self):
        if self.is_running:
            return
        current = self.currency.currentData()
        with QSignalBlocker(self.currency):
            self.currency.clear()
            for code in sorted({w["currency"] for w in self.db.wallets()}):
                self.currency.addItem(code, code)
            self.currency.setCurrentIndex(
                max(0, self.currency.findData(current if current is not None else "PLN"))
            )
        self.refresh_wallets()

    def refresh_wallets(self):
        current = self.wallet.currentData()
        with QSignalBlocker(self.wallet):
            self.wallet.clear()
            self.wallet.addItem(tr("Wszystkie w wybranej walucie"), None)
            for row in self.db.wallets():
                if row["currency"] == self.currency.currentData():
                    self.wallet.addItem(row["name"], row["id"])
            self.wallet.setCurrentIndex(max(0, self.wallet.findData(current)))
        self.refresh_years()

    def scoped_months(self):
        return sorted(
            {
                r["date"][:7]
                for r in self.db.transactions(self.wallet.currentData())
                if r["currency"] == self.currency.currentData() and r["include_in_reports"]
            }
        )

    def refresh_years(self):
        current = self.year.currentData()
        with QSignalBlocker(self.year):
            self.year.clear()
            self.year.addItem(tr("Wszystkie lata"), None)
            for year in sorted({m[:4] for m in self.scoped_months()}):
                self.year.addItem(year, int(year))
            self.year.setCurrentIndex(max(0, self.year.findData(current)))
        self.refresh_months()

    def refresh_months(self):
        self.month_grid.setEnabled(False)
        previous = {
            self.months.item(i).text(): self.months.item(i).checkState()
            for i in range(self.months.count())
        }
        self.months.clear()
        year = self.year.currentData()
        for month in self.scoped_months():
            if year is None or month.startswith(f"{year:04d}-"):
                item = QListWidgetItem(month)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(previous.get(month, Qt.CheckState.Checked))
                self.months.addItem(item)
        self.generate_button.setEnabled(self.months.count() > 0)
        if not self.months.count():
            self.status.setText(
                tr("Brak transakcji zaznaczonych „W raportach” dla wybranego portfela i waluty.")
            )
        elif self.status.text() == tr(
            "Brak transakcji zaznaczonych „W raportach” dla wybranego portfela i waluty."
        ):
            self.status.setText(tr("Wybierz zakres raportów."))

        self.schedule_summary()

    def select_months(self, checked):
        for i in range(self.months.count()):
            self.months.item(i).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def schedule_summary(self, *_):
        if not self.is_running and not self.summary_closed:
            self.summary_timer.start()

    def stop_summary(self):
        self.summary_closed = True
        from PyQt6 import sip

        if not sip.isdeleted(self):
            self.summary_timer.stop()

    def refresh_summary(self):
        if self.is_running or self.summary_closed:
            return
        self.summary_timer.stop()
        from home_finance_cockpit.ui.report_workspace import refresh_documents, refresh_month_grid

        refresh_month_grid(self)
        eligible = [
            m
            for m in self.scoped_months()
            if self.year.currentData() is None or m.startswith(str(self.year.currentData()) + "-")
        ]
        years = sorted({m[:4] for m in eligible}) if self.annual.isChecked() else []
        monthly = (
            [
                self.months.item(i).text()
                for i in range(self.months.count())
                if self.months.item(i).checkState() == Qt.CheckState.Checked
            ]
            if self.monthly.isChecked()
            else []
        )
        self.selected_monthly = monthly
        self.selected_annual = years
        self.report_count.setText(tr("Raporty PDF: {count}", count=len(monthly) + len(years)))
        self.report_breakdown.setText(
            tr(
                "Miesi\u0119czne: {months} \u00b7 Roczne: {years}",
                months=len(monthly),
                years=len(years),
            )
        )
        self.annual_note.setText(
            tr(
                "Okres: {period} \u00b7 Wszystkie dost\u0119pne miesi\u0105ce",
                period=", ".join(years),
            )
            if years
            else tr("Brak raportu rocznego")
        )
        refresh_documents(self, monthly, years, eligible)
        try:
            self.summary_data = snapshot(self.db, self.options())
            error = ""
        except (ValueError, sqlite3.Error) as exc:
            self.summary_data = None
            error = str(exc)
        self.generate_button.setEnabled(
            self.summary_data is not None and bool(self.output.text().strip())
        )
        if self.last_result is None:
            self.status.setText(error or tr("Gotowe do generowania raport\u00f3w."))

    def show_running_state(self, running):
        self.output.setEnabled(not running)
        self.choose_button.setEnabled(not running)
        self.cancel_button.setVisible(running)
        self.progress.setVisible(running)
        self.status.show()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Folder raportów"), self.output.text())
        if folder:
            self.output.setText(folder)

    def options(self):
        return ReportOptions(
            currency=self.currency.currentData() or "",
            wallet_id=self.wallet.currentData(),
            year=self.year.currentData(),
            months=tuple(
                self.months.item(i).text()
                for i in range(self.months.count())
                if self.months.item(i).checkState() == Qt.CheckState.Checked
            ),
            monthly=self.monthly.isChecked(),
            annual=self.annual.isChecked(),
            transactions=self.transactions.isChecked(),
            uncategorized=self.uncategorized.isChecked(),
            comparison=self.comparison.isChecked(),
            exclude_recognized=self.exclude.isChecked(),
            after_refunds=self.after_refunds.isChecked(),
            omit_salary=self.omit_salary.isChecked(),
        )

    def generate(self):
        if self.is_running:
            return
        try:
            if not self.output.text().strip():
                raise ValueError(tr("Wybierz folder wyników."))
            data = snapshot(self.db, self.options())
        except (ValueError, sqlite3.Error) as exc:
            show_error(self, exc)
            return
        self.is_running = True
        self.summary_timer.stop()
        self.show_running_state(True)
        self.controls.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.progress.setRange(0, len(data["monthly_months"]) + len(data["years"]))
        self.progress.setValue(0)
        self.status.setText(tr("Generowanie raportów…"))
        self.thread = QThread(self)
        self.worker = ReportWorker(data, self.output.text().strip(), self.db.path)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.canceled.connect(
            lambda: self.status.setText(tr("Generowanie anulowane. Poprzednie raporty zachowano."))
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.generation_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.busy_changed.emit(True)
        self.thread.start()

    def on_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(tr(message))

    def on_success(self, result):
        self.last_result = result
        self.open_button.setEnabled(True)
        self.open_button.show()
        self.status.show()
        self.status.setText(
            tr("Wygenerowano PDF: {v0}. Folder: {v1}", v0=len(result["pdfs"]), v1=result["folder"])
        )

    def on_failure(self, message):
        self.status.show()
        self.status.setText((tr("Nie udało się wygenerować raportów: ") + tr(message)))

    def generation_finished(self):
        self.is_running = False
        self.controls.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.show_running_state(False)
        message = self.status.text()
        self.refresh_summary()
        self.status.setText(message)
        self.thread = None
        self.busy_changed.emit(False)

    def cancel(self):
        if self.is_running:
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText(tr("Anulowanie po zakończeniu bieżącego etapu…"))

    def open_output(self):
        if self.last_result and not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.last_result["folder"]))
        ):
            show_error(self, ValueError(tr("Nie udało się otworzyć folderu wyników.")))


class ReportGeneratorPage(QWidget):
    def __init__(self, parent, db):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = ReportGeneratorPanel(db, self)
        layout.addWidget(self.panel)
