import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase

from PyQt6.QtCore import QByteArray, QObject, Qt, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QApplication

from home_finance_cockpit.services.currency_history import (
    CurrencyHistoryService,
    history_chunks,
    parse_history,
)
from home_finance_cockpit.storage import Database


class Reply(QObject):
    finished = pyqtSignal()
    downloadProgress = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.status = 200
        self.payload = b""

    def attribute(self, key):
        return self.status

    def error(self):
        return (
            QNetworkReply.NetworkError.NoError
            if self.status == 200
            else QNetworkReply.NetworkError.ContentNotFoundError
        )

    def errorString(self):
        return "Not found"

    def readAll(self):
        return QByteArray(self.payload)

    def abort(self):
        self.status = 0
        self.finished.emit()


class Network:
    def __init__(self):
        self.requests = []
        self.replies = []

    def get(self, request):
        self.requests.append(request)
        reply = Reply()
        self.replies.append(reply)
        return reply


def payload(table="A", day="2026-01-02", rate=4.3):
    return json.dumps(
        dict(code="EUR", table=table, rates=[dict(effectiveDate=day, mid=rate)])
    ).encode()


class CurrencyHistoryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.db.save_currency("EUR", "Euro")

    def test_daily_refresh_history_upsert_and_validation(self):
        self.db.store_quote("EUR", "4.3", "2026-01-02")
        self.db.store_quote("EUR", "4.4", "2026-01-02")
        rows = self.db.rate_history("EUR", "2026-01-01", "2026-01-03")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rate"], "4.4")
        self.assertTrue(rows[0]["fetched_at"])
        with self.assertRaises(ValueError):
            self.db.store_rate_history("EUR", [("2026-01-03", "4.2"), ("invalid", "4")])
        self.assertEqual(len(self.db.rate_history("EUR", "2026-01-01", "2026-01-04")), 1)

    def test_v11_migration_backup_seeds_current_quote_and_reopens(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            db = Database(path)
            db.save_currency("EUR", "Euro")
            db.store_quote("EUR", "4.3", "2026-01-02")
            db.execute("DROP TABLE currency_rate_history")
            db.execute("DROP TABLE currency_history_requests")
            db.execute("PRAGMA user_version=11")
            db.close()
            db = Database.open_existing(path)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 12)
            self.assertEqual(db.rate_history("EUR", "2026-01-01", "2026-01-03")[0]["rate"], "4.3")
            db.close()
            backups = list((path.parent / "backups").glob("before_v12_*.db"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as old:
                self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 11)
            db = Database.open_existing(path)
            db.close()

    def test_chunk_limit_and_response_contract(self):
        chunks = list(history_chunks("2025-01-01", "2026-01-01"))
        self.assertEqual(chunks[0], ("2025-01-01", "2025-04-03"))
        self.assertEqual(chunks[-1][1], "2026-01-01")
        self.assertEqual(
            parse_history(payload(), "EUR", "A", "2026-01-01", "2026-01-05"),
            [("2026-01-02", "4.3")],
        )
        with self.assertRaises(ValueError):
            parse_history(payload(day="2026-01-08"), "EUR", "A", "2026-01-01", "2026-01-05")
        with self.assertRaises(ValueError):
            list(history_chunks("2026-01-02", "2026-01-01"))

    def test_deleted_currency_history_can_be_restored_and_rename_clears_wrong_quotes(self):
        self.db.store_quote("EUR", "4.3", "2026-01-02")
        request = self.db.start_history_request("EUR", "2026-01-01", "2026-01-05")
        self.db.finish_history_request(request, "success", 1)
        identifier = next(c["id"] for c in self.db.currencies() if c["code"] == "EUR")
        self.db.delete("currencies", [identifier])
        self.db.undo_delete()
        self.assertEqual(len(self.db.rate_history("EUR", "2026-01-01", "2026-01-05")), 1)
        self.db.save_currency("USD", "Dollar", identifier)
        self.assertEqual(self.db.rate_history("USD", "2026-01-01", "2026-01-05"), [])

    def test_range_fetch_b_fallback_logs_and_does_not_replace_current_rate(self):
        self.db.store_quote("EUR", "4.8", "2026-02-02")
        service = CurrencyHistoryService(self.db)
        network = Network()
        service.network = network
        self.addCleanup(service.stop)
        service.refresh(["EUR"], "2026-01-01", "2026-01-05")
        network.replies[-1].status = 404
        network.replies[-1].finished.emit()
        self.app.processEvents()
        self.assertIn("/B/EUR/", network.requests[-1].url().toString())
        network.replies[-1].payload = payload("B")
        network.replies[-1].finished.emit()
        self.app.processEvents()
        self.assertFalse(service.busy)
        self.assertEqual(self.db.rate_history("EUR", "2026-01-01", "2026-01-05")[0]["rate"], "4.3")
        self.assertEqual(str(self.db.effective_rate("EUR")[0]), "4.8")
        log = self.db.execute("SELECT * FROM currency_history_requests").fetchone()
        self.assertEqual(log["status"], "success")
        self.assertEqual(log["quote_count"], 1)
        self.assertTrue(log["finished_at"])

    def test_invalid_response_preserves_saved_quotes_and_records_failure(self):
        self.db.store_quote("EUR", "4.1", "2026-01-02")
        service = CurrencyHistoryService(self.db)
        service.network = Network()
        self.addCleanup(service.stop)
        service.refresh(["EUR"], "2026-01-01", "2026-01-05")
        service.network.replies[-1].payload = payload(day="2026-01-10")
        service.network.replies[-1].finished.emit()
        self.app.processEvents()
        self.assertEqual(self.db.rate_history("EUR", "2026-01-01", "2026-01-05")[0]["rate"], "4.1")
        self.assertEqual(
            self.db.execute("SELECT status FROM currency_history_requests").fetchone()[0], "failed"
        )

    def test_cancel_records_outcome_and_cannot_write_after_close(self):
        service = CurrencyHistoryService(self.db)
        service.network = Network()
        self.addCleanup(service.stop)
        service.refresh(["EUR"], "2026-01-01", "2026-01-05")
        service.cancel()
        self.assertEqual(
            self.db.execute("SELECT status FROM currency_history_requests").fetchone()[0],
            "canceled",
        )
        self.assertFalse(service.busy)

    def test_history_page_uses_saved_points_and_is_embedded(self):
        from home_finance_cockpit.ui.analyses import AnalysesTab

        self.db.store_quote("EUR", "4.3", "2026-01-02")
        page = AnalysesTab(self.db)
        self.addCleanup(page.deleteLater)
        page.tabs.setCurrentIndex(5)
        history = page.currency_rates
        from PyQt6.QtCore import QDate

        history.start.setDate(QDate(2026, 1, 1))
        history.end.setDate(QDate(2026, 1, 5))
        history.refresh_chart()
        self.assertEqual(history.table.rowCount(), 1)
        self.assertEqual(history.chart_data["series"]["EUR"][0]["rate"], "4.3")
        self.assertFalse(hasattr(page, "pdf_button"))

    def test_manual_history_is_visible_marked_and_does_not_override_nbp(self):
        from PyQt6.QtCore import QDate

        from home_finance_cockpit.ui.currency_rates import CurrencyRatesTab

        self.db.store_rate_history(
            "EUR", [("2026-01-02", "4.2"), ("2026-01-05", "4.1")], source="manual"
        )
        self.db.store_quote("EUR", "4.3", "2026-01-02")
        page = CurrencyRatesTab(self.db)
        self.addCleanup(page.deleteLater)
        page.start.setDate(QDate(2026, 1, 1))
        page.end.setDate(QDate(2026, 1, 6))
        page.refresh_chart()
        values = page.chart_data["series"]["EUR"]
        self.assertEqual(
            [(r["quote_date"], r["rate"], r["source"]) for r in values],
            [("2026-01-02", "4.3", "NBP"), ("2026-01-05", "4.1", "manual")],
        )
        self.assertEqual(page.table.rowCount(), 2)
        self.assertTrue(
            "manual" in page.table.item(0, 3).text() or "ręcznie" in page.table.item(0, 3).text()
        )

    def test_quote_columns_fill_viewport_after_refresh_and_resize(self):
        from PyQt6.QtCore import QDate

        from home_finance_cockpit.ui.currency_rates import CurrencyRatesTab

        self.db.store_quote("EUR", "4.3", "2026-01-02")
        page = CurrencyRatesTab(self.db)
        self.addCleanup(page.deleteLater)
        page.start.setDate(QDate(2026, 1, 1))
        page.end.setDate(QDate(2026, 1, 5))
        page.resize(1200, 800)
        page.show()
        for width in (1200, 900, 1400):
            page.resize(width, 800)
            self.app.processEvents()
            page.refresh_chart()
            self.app.processEvents()
            total = sum(page.table.columnWidth(i) for i in range(4))
            self.assertLessEqual(abs(total - page.table.viewport().width()), 2)
            self.assertLessEqual(
                max(page.table.columnWidth(i) for i in range(4))
                - min(page.table.columnWidth(i) for i in range(4)),
                1,
            )
        page.hide()

    def interaction_page(self):
        from PyQt6.QtCore import QDate

        from home_finance_cockpit.ui.currency_rates import CurrencyRatesTab

        self.db.store_rate_history("EUR", [("2026-01-02", "4.3"), ("2026-01-05", "4.4")])
        page = CurrencyRatesTab(self.db)
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close_windows)
        page.start.setDate(QDate(2026, 1, 1))
        page.end.setDate(QDate(2026, 1, 6))
        page.resize(1100, 800)
        page.show()
        self.app.processEvents()
        page.canvas.draw()
        return page

    def test_chart_click_selects_exact_quote_and_table_row(self):
        from datetime import date

        from matplotlib.backend_bases import MouseEvent
        from matplotlib.dates import date2num

        page = self.interaction_page()
        ax = page.canvas.figure.axes[0]
        x, y = ax.transData.transform((date2num(date(2026, 1, 2)), 4.3))
        event = MouseEvent("button_press_event", page.canvas, x, y, button=1)
        page.canvas.callbacks.process("button_press_event", event)
        self.assertEqual(page.selected_point, ("EUR", "2026-01-02"))
        self.assertEqual(page.table.selectionModel().selectedRows()[0].row(), 1)
        self.assertTrue(any("4.3 PLN" in t.get_text() for t in page.canvas.figure.axes[0].texts))
        self.assertEqual(page.windows, [])
        page.hide()

    def test_double_click_enlarges_and_selection_syncs_both_views(self):
        from datetime import date

        from matplotlib.backend_bases import MouseEvent
        from matplotlib.dates import date2num
        from PyQt6.QtTest import QTest

        page = self.interaction_page()
        QTest.mouseDClick(page.canvas, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(len(page.windows), 1)
        dialog = page.windows[0]
        dialog.canvas.draw()
        self.assertEqual(dialog.data["currency"], "PLN")
        page.table.selectRow(0)
        self.assertEqual(page.selected_point, ("EUR", "2026-01-05"))
        self.assertEqual(dialog.data["selected"], page.selected_point)
        self.assertTrue(any("4.4 PLN" in t.get_text() for t in dialog.canvas.figure.axes[0].texts))
        dialog.canvas.draw()
        ax = dialog.canvas.figure.axes[0]
        x, y = ax.transData.transform((date2num(date(2026, 1, 2)), 4.3))
        event = MouseEvent("button_press_event", dialog.canvas, x, y, button=1)
        dialog.canvas.callbacks.process("button_press_event", event)
        self.assertEqual(page.selected_point, ("EUR", "2026-01-02"))
        self.assertEqual(page.table.selectionModel().selectedRows()[0].row(), 1)
        page.close_windows()
        self.app.processEvents()
        self.assertEqual(page.windows, [])
        page.hide()

    def test_refresh_preserves_selection_and_clears_hidden_point(self):
        from PyQt6.QtCore import QDate

        page = self.interaction_page()
        page.table.selectRow(0)
        page.refresh_chart()
        self.assertEqual(page.selected_point, ("EUR", "2026-01-05"))
        self.assertEqual(len(page.table.selectionModel().selectedRows()), 1)
        page.end.setDate(QDate(2026, 1, 3))
        self.assertIsNone(page.selected_point)
        self.assertFalse(page.table.selectionModel().selectedRows())
        page.hide()
