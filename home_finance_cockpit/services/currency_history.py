"""Asynchronous NBP historical mid quotes in bounded, sequential requests."""

import json
import sqlite3
from collections import deque
from datetime import date, timedelta
from decimal import Decimal, DecimalException

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from home_finance_cockpit.domain.validation import iso_date
from home_finance_cockpit.localization import tr
from home_finance_cockpit.storage.finance_features import rate_value


def history_chunks(start, end):
    first, last = date.fromisoformat(iso_date(start)), date.fromisoformat(iso_date(end))
    if first > last or first < date(2002, 1, 2) or last > date.today():
        raise ValueError(tr("Wybierz poprawny zakres od 02.01.2002 do dzisiaj."))
    while first <= last:
        stop = min(last, first + timedelta(days=92))
        yield first.isoformat(), stop.isoformat()
        first = stop + timedelta(days=1)


def parse_history(payload, code, table, start, end):
    data = json.loads(payload, parse_float=Decimal)
    if (
        not isinstance(data, dict)
        or data.get("code") != code
        or data.get("table") != table
        or not isinstance(data.get("rates"), list)
    ):
        raise ValueError(tr("Nieprawidłowa odpowiedź API NBP."))
    result = []
    seen = set()
    for row in data["rates"]:
        day = iso_date(row["effectiveDate"])
        rate = rate_value(row["mid"])
        if day < start or day > end or day in seen:
            raise ValueError(tr("Nieprawidłowa data kursu NBP."))
        seen.add(day)
        result.append((day, rate))
    return sorted(result)


class CurrencyHistoryService(QObject):
    changed = pyqtSignal()
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.queue = deque()
        self.busy = False
        self.closed = False
        self.requests = {}
        self.job = 0
        db._close_callbacks.append(self.stop)

    def refresh(self, codes, start, end):
        if self.busy or self.closed:
            return
        chunks = list(history_chunks(start, end))
        codes = sorted(set(codes))
        available = {r["code"] for r in self.db.rate_records() if r["code"] != "PLN"}
        if not codes or set(codes) - available:
            raise ValueError(tr("Wybierz co najmniej jedną dostępną walutę."))
        self.job += 1
        self.requests = {}
        self.errors = {code: [] for code in codes}
        self.counts = {code: 0 for code in codes}
        with self.db.transaction():
            for code in codes:
                self.requests[code] = self.db.start_history_request(code, start, end)
        self.queue = deque((code, a, b, "A") for code in codes for a, b in chunks)
        self.total = len(self.queue)
        self.done = 0
        self.busy = True
        self.busy_changed.emit(True)
        self._next()

    def _next(self):
        if not self.busy or self.closed or self.reply is not None:
            return
        if not self.queue:
            self._complete()
            return
        task = self.queue.popleft()
        code, start, end, table = task
        request = QNetworkRequest(
            QUrl(
                f"https://api.nbp.pl/api/exchangerates/rates/{table}/{code}/{start}/{end}/?format=json"
            )
        )
        request.setTransferTimeout(20000)
        request.setRawHeader(b"Accept", b"application/json")
        reply = self.network.get(request)
        self.reply = reply
        reply.downloadProgress.connect(
            lambda received, total, r=reply: (
                r.abort() if received > 4_000_000 or total > 4_000_000 else None
            )
        )
        reply.finished.connect(lambda r=reply, t=task, job=self.job: self._received(r, t, job))

    def _received(self, reply, task, job):
        code, start, end, table = task
        if self.reply is reply:
            self.reply = None
        if self.closed or not self.busy or job != self.job:
            reply.deleteLater()
            return
        fallback = False
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                if table == "A":
                    self.queue.appendleft((code, start, end, "B"))
                    fallback = True
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            else:
                payload = bytes(reply.readAll())
                if len(payload) > 4_000_000:
                    raise ValueError(tr("Odpowiedź API jest zbyt duża."))
                quotes = parse_history(payload, code, table, start, end)
                self.db.store_rate_history(code, quotes)
                self.counts[code] += len(quotes)
                if quotes:
                    self.changed.emit()
        except (
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            DecimalException,
            sqlite3.Error,
        ) as exc:
            self.errors[code].append(str(exc))
        finally:
            reply.deleteLater()
        if not fallback:
            self.done += 1
            self.progress.emit(self.done, self.total)
        QTimer.singleShot(0, self._next)

    def _complete(self, canceled=False):
        messages = []
        for code, identifier in self.requests.items():
            errors = self.errors[code]
            state = (
                "canceled"
                if canceled
                else ("partial" if self.counts[code] else "failed")
                if errors
                else "success"
            )
            self.db.finish_history_request(identifier, state, self.counts[code], "; ".join(errors))
            if errors:
                messages.append(code + ": " + errors[0])
        count = sum(self.counts.values())
        self.busy = False
        self.queue.clear()
        self.busy_changed.emit(False)
        self.changed.emit()
        message = (
            tr("Pobieranie anulowane. Zapisane notowania zachowano.")
            if canceled
            else tr("Zapisane notowania: {count}", count=count)
        )
        if messages:
            message += " · " + "; ".join(messages)
        self.finished.emit(message)

    def cancel(self):
        if not self.busy:
            return
        # Mark the job idle before abort can synchronously emit finished.
        self.busy = False
        if self.reply is not None:
            self.reply.abort()
        self._complete(canceled=True)

    def stop(self):
        from PyQt6 import sip

        if sip.isdeleted(self):
            return
        if self.busy:
            self.cancel()
        self.closed = True
