"""Live, nonblocking catalogue from the same NBP A/B tables as FX updates."""

import json

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from home_finance_cockpit.services.exchange_rates import parse_table


def parse_catalog(payload, table):
    quotes = parse_table(payload, table)
    block = json.loads(payload)[0]
    result = {}
    for row in block["rates"]:
        name = row.get("currency", row["code"])
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Invalid currency name")
        result[row["code"]] = dict(
            code=row["code"], name=name, rate=quotes[row["code"]][0], date=quotes[row["code"]][1]
        )
    return result


class CurrencyCatalog(QObject):
    updated = pyqtSignal()
    cache = {}

    def __init__(self, parent):
        super().__init__(parent)
        self.rows = dict(self.cache)
        self.errors = []
        self.pending = 0
        self.started = False
        self.network = QNetworkAccessManager(self)

    def start(self):
        if self.started:
            return
        self.started = True
        self.pending = 2
        for table in ("A", "B"):
            request = QNetworkRequest(
                QUrl(f"https://api.nbp.pl/api/exchangerates/tables/{table}/?format=json")
            )
            request.setTransferTimeout(15000)
            reply = self.network.get(request)
            reply.downloadProgress.connect(
                lambda received, total, r=reply: (
                    r.abort() if max(received, total) > 2_000_000 else None
                )
            )
            reply.finished.connect(lambda r=reply, t=table: self.finished(r, t))

    def finished(self, reply, table):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(reply.errorString())
            payload = bytes(reply.readAll())
            if len(payload) > 2_000_000:
                raise ValueError("Response too large")
            self.rows.update(parse_catalog(payload, table))
            CurrencyCatalog.cache.update(self.rows)
        except (ValueError, KeyError, TypeError) as exc:
            self.errors.append(str(exc))
        finally:
            self.pending -= 1
            reply.deleteLater()
            self.updated.emit()
