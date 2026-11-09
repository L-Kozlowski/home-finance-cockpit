"""Nonblocking official NBP mid rates, in PLN per one foreign currency unit."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from home_finance_cockpit.localization import tr
from home_finance_cockpit.storage.finance_features import rate_value


def parse_table(payload, table):
    data = json.loads(payload, parse_float=Decimal)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError(tr("Nieprawidłowa odpowiedź API NBP."))
    block = data[0]
    if (
        block.get("table") != table
        or not isinstance(block.get("rates"), list)
        or not block["rates"]
    ):
        raise ValueError(tr("Nieprawidłowa odpowiedź API NBP."))
    day = date.fromisoformat(block["effectiveDate"])
    if day > datetime.now(timezone.utc).date():
        raise ValueError(tr("Nieprawidłowa data kursu NBP."))
    result = {}
    for row in block["rates"]:
        code = row["code"]
        if (
            not isinstance(code, str)
            or len(code) != 3
            or not code.isascii()
            or not code.isalpha()
            or code != code.upper()
            or code in result
        ):
            raise ValueError(tr("Nieprawidłowa odpowiedź API NBP."))
        result[code] = (rate_value(row["mid"]), day.isoformat())
    return result


class ExchangeRateService(QObject):
    changed = pyqtSignal()
    busy_changed = pyqtSignal(bool)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.network = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.abort_pending)
        self.replies = set()
        self.pending = 0
        self.active = True
        self.quotes, self.errors = {}, []
        self.requested = set()
        db._close_callbacks.append(self.stop)
        if parent is not None:
            parent.destroyed.connect(self.stop)

    @property
    def busy(self):
        return bool(self.pending)

    def start(self):
        self.active = True
        self.timer.start(1000)

    def stop(self):
        from PyQt6 import sip

        if sip.isdeleted(self):
            return
        self.active = False
        self.timer.stop()
        self.deadline.stop()
        self.abort_pending()

    def abort_pending(self):
        for reply in list(self.replies):
            reply.abort()

    def check_due(self):
        self.timer.setInterval(60000)
        if not self.active or self.busy:
            return
        config = self.db.exchange_config()
        if not config["enabled"]:
            return
        try:
            last = datetime.fromisoformat(config["last_attempt"])
            if last.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            last = None
        if last is None or datetime.now(timezone.utc) - last >= timedelta(
            hours=config["interval_hours"]
        ):
            self.refresh_now()

    def refresh_now(self):
        if not self.active or self.busy:
            return
        self.requested = {
            r["code"] for r in self.db.rate_records() if r["code"] != "PLN" and r["mode"] == "api"
        }
        if not self.requested:
            self.changed.emit()
            return
        with self.db.transaction():
            self.db.execute(
                "UPDATE exchange_settings SET last_attempt=? WHERE id=1",
                (datetime.now(timezone.utc).isoformat(),),
            )
        self.quotes, self.errors = {}, []
        self.pending = 2
        self.deadline.start(20000)
        self.busy_changed.emit(True)
        for table in ("A", "B"):
            request = QNetworkRequest(
                QUrl(f"https://api.nbp.pl/api/exchangerates/tables/{table}/?format=json")
            )
            request.setTransferTimeout(15000)
            request.setRawHeader(b"Accept", b"application/json")
            reply = self.network.get(request)
            self.replies.add(reply)
            reply.downloadProgress.connect(
                lambda received, total, r=reply: (
                    r.abort() if received > 2_000_000 or total > 2_000_000 else None
                )
            )
            reply.finished.connect(lambda r=reply, t=table: self._finished(r, t))

    def _finished(self, reply, table):
        self.replies.discard(reply)
        if not self.active:
            reply.deleteLater()
            self.pending = max(0, self.pending - 1)
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(
                    tr("Nie udało się pobrać kursów NBP: {error}", error=reply.errorString())
                )
            payload = bytes(reply.readAll())
            if len(payload) > 2_000_000:
                raise ValueError(tr("Odpowiedź API jest zbyt duża."))
            self.quotes.update(parse_table(payload, table))
        except (ValueError, TypeError, KeyError, OverflowError, DecimalException) as exc:
            self.errors.append(str(exc))
        finally:
            reply.deleteLater()
            self.pending -= 1
        if self.pending:
            return
        self.deadline.stop()
        with self.db.transaction():
            for code in self.requested:
                # A currency switched to manual during the request must stay manual.
                if code in self.quotes:
                    rate, day = self.quotes[code]
                    self.db.store_quote(code, rate, day)
                else:
                    self.db.store_quote(
                        code,
                        error="; ".join(self.errors)
                        or tr("Waluta nie jest dostępna w tabelach A/B NBP. Ustaw kurs ręczny."),
                    )
        self.busy_changed.emit(False)
        self.changed.emit()
