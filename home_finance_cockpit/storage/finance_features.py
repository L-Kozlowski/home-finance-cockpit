"""Savings allocations and current FX quotes; no changes to transaction amounts."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from home_finance_cockpit.domain.validation import MAX_MINOR, iso_date, money_minor, text
from home_finance_cockpit.localization import tr


def rate_value(value):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
        if not number.is_finite() or not Decimal("0") < number <= Decimal("1000000000"):
            raise InvalidOperation
        if number.as_tuple().exponent < -10:
            raise InvalidOperation
        return format(number, "f")
    except (InvalidOperation, ValueError):
        raise ValueError(
            tr("Kurs musi być dodatnią liczbą, maksymalnie 10 miejsc po przecinku.")
        ) from None


class FinanceFeatures:
    def _create_goals_schema(self):
        self.execute(f"""CREATE TABLE savings_goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name))>0),
            wallet_id INTEGER REFERENCES wallets(id) ON DELETE RESTRICT,
            currency TEXT NOT NULL REFERENCES currencies(code) ON UPDATE CASCADE ON DELETE RESTRICT,
            calculation_mode TEXT NOT NULL DEFAULT 'manual' CHECK(calculation_mode IN('wallet','manual')),
            target_minor INTEGER NOT NULL CHECK(typeof(target_minor)='integer' AND target_minor>0 AND target_minor<={MAX_MINOR}),
            allocated_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(allocated_minor)='integer' AND allocated_minor>=0 AND allocated_minor<={MAX_MINOR}),
            deadline TEXT CHECK(deadline IS NULL OR (length(deadline)=10 AND date(deadline,'+0 days') IS NOT NULL AND date(deadline,'+0 days')=deadline)),
            CHECK((calculation_mode='manual' AND wallet_id IS NULL) OR (calculation_mode='wallet' AND wallet_id IS NOT NULL)))""")

    def _upgrade_goals_schema(self):
        if self.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError(tr("Baza zawiera nieprawidłowe powiązania danych."))
        self.execute("ALTER TABLE savings_goals RENAME TO savings_goals_v8")
        self._create_goals_schema()
        self.execute("""INSERT INTO savings_goals(id,name,wallet_id,currency,calculation_mode,target_minor,allocated_minor,deadline)
            SELECT g.id,g.name,NULL,w.currency,'manual',g.target_minor,g.allocated_minor,g.deadline
            FROM savings_goals_v8 g JOIN wallets w ON w.id=g.wallet_id""")
        self.execute("DROP TABLE savings_goals_v8")

    def _create_finance_schema(self):
        self._create_goals_schema()
        self.execute("""CREATE TABLE currency_rates(
            id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE REFERENCES currencies(code) ON UPDATE CASCADE ON DELETE CASCADE,
            mode TEXT NOT NULL DEFAULT 'api' CHECK(mode IN('api','manual')),
            manual_rate TEXT, api_rate TEXT, quote_date TEXT, fetched_at TEXT,
            last_error TEXT NOT NULL DEFAULT '')""")
        self.execute("""CREATE TABLE exchange_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN(0,1)),
            interval_hours INTEGER NOT NULL DEFAULT 24 CHECK(interval_hours BETWEEN 1 AND 720),
            last_attempt TEXT)""")
        self.execute("INSERT INTO exchange_settings(id) VALUES(1)")
        self._create_rate_history_schema()

    def _create_rate_history_schema(self):
        self.execute("""CREATE TABLE currency_rate_history(
            code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE CASCADE ON DELETE CASCADE,
            quote_date TEXT NOT NULL CHECK(date(quote_date,'+0 days')=quote_date),
            rate TEXT NOT NULL CHECK(CAST(rate AS REAL)>0),
            source TEXT NOT NULL CHECK(source IN('NBP','manual')),
            fetched_at TEXT NOT NULL,
            PRIMARY KEY(code,quote_date,source))""")
        self.execute("""CREATE TABLE currency_history_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL REFERENCES currencies(code) ON UPDATE CASCADE ON DELETE CASCADE,
            start_date TEXT NOT NULL,end_date TEXT NOT NULL,
            started_at TEXT NOT NULL,finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN('running','success','partial','failed','canceled')),
            quote_count INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '')""")
        for row in self.execute(
            "SELECT code,api_rate,quote_date,fetched_at FROM currency_rates WHERE api_rate IS NOT NULL AND quote_date IS NOT NULL AND fetched_at IS NOT NULL"
        ).fetchall():
            self.store_rate_history(
                row["code"], [(row["quote_date"], row["api_rate"])], fetched_at=row["fetched_at"]
            )

    def store_rate_history(self, code, quotes, *, source="NBP", fetched_at=None):
        if not self.execute("SELECT 1 FROM currencies WHERE code=?", (code,)).fetchone():
            raise ValueError(tr("Najpierw dodaj wybraną walutę."))
        if source not in ("NBP", "manual"):
            raise ValueError(tr("Nieprawidłowe źródło kursu."))
        stamp = fetched_at or datetime.now(timezone.utc).isoformat()
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError(tr("Czas pobrania wymaga strefy czasowej."))
        rows = [(code, iso_date(day), rate_value(rate), source, stamp) for day, rate in quotes]
        with self.transaction():
            self.conn.executemany(
                """INSERT INTO currency_rate_history(code,quote_date,rate,source,fetched_at) VALUES(?,?,?,?,?)
                ON CONFLICT(code,quote_date,source) DO UPDATE SET rate=excluded.rate,fetched_at=excluded.fetched_at""",
                rows,
            )

    def rate_history(self, code, start, end):
        from home_finance_cockpit.domain.validation import date_range

        start, end = date_range(start, end)
        return [
            dict(r)
            for r in self.execute(
                "SELECT * FROM currency_rate_history WHERE code=? AND quote_date BETWEEN ? AND ? ORDER BY quote_date,source",
                (code, start, end),
            )
        ]

    def start_history_request(self, code, start, end):
        from home_finance_cockpit.domain.validation import date_range

        start, end = date_range(start, end)
        with self.transaction():
            return self.execute(
                "INSERT INTO currency_history_requests(code,start_date,end_date,started_at,status) VALUES(?,?,?,?, 'running')",
                (code, start, end, datetime.now(timezone.utc).isoformat()),
            ).lastrowid

    def finish_history_request(self, identifier, status, count=0, error=""):
        if status not in ("success", "partial", "failed", "canceled"):
            raise ValueError(tr("Nieprawidłowy status pobrania."))
        with self.transaction():
            self.execute(
                "UPDATE currency_history_requests SET finished_at=?,status=?,quote_count=?,error=? WHERE id=?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    count,
                    str(error)[:2000],
                    identifier,
                ),
            )

    def savings_goals(self):
        rows = [
            dict(r)
            for r in self.execute("""SELECT g.*,w.name AS wallet FROM savings_goals g
            LEFT JOIN wallets w ON w.id=g.wallet_id ORDER BY g.id""")
        ]
        balances = {w["id"]: max(0, w["balance"]) for w in self.wallet_balances()}
        for goal in rows:
            goal["funded_minor"] = (
                balances[goal["wallet_id"]]
                if goal["calculation_mode"] == "wallet"
                else goal["allocated_minor"]
            )
        return rows

    def save_savings_goal(
        self,
        name,
        wallet_id,
        target,
        allocated,
        deadline=None,
        goal_id=None,
        *,
        calculation_mode="manual",
        currency=None,
    ):
        name = text(name, "Nazwa", limit=100)
        target, allocated = (
            money_minor(target),
            money_minor(allocated) if calculation_mode != "wallet" else 0,
        )
        deadline = iso_date(deadline) if deadline else None
        if calculation_mode not in ("wallet", "manual"):
            raise ValueError(tr("Nieprawidłowy sposób liczenia celu."))
        if target <= 0 or allocated < 0:
            raise ValueError(tr("Kwota celu musi być dodatnia, a zebrana kwota nieujemna."))
        if calculation_mode == "manual":
            if currency is None and wallet_id is not None:
                currency = self.wallet(wallet_id)["currency"]
            wallet_id = None
            if not self.execute("SELECT 1 FROM currencies WHERE code=?", (currency,)).fetchone():
                raise ValueError(tr("Najpierw dodaj wybraną walutę."))
        else:
            currency = self.wallet(wallet_id)["currency"]
        if calculation_mode == "wallet":
            allocated = 0
        with self.transaction():
            if goal_id is not None:
                self._exists("savings_goals", goal_id)
                if calculation_mode == "wallet":
                    old = self.execute(
                        "SELECT allocated_minor,currency FROM savings_goals WHERE id=?", (goal_id,)
                    ).fetchone()
                    allocated = old["allocated_minor"] if old["currency"] == currency else 0
            if goal_id is None:
                return self.execute(
                    "INSERT INTO savings_goals(name,wallet_id,target_minor,allocated_minor,deadline,calculation_mode,currency) VALUES(?,?,?,?,?,?,?)",
                    (name, wallet_id, target, allocated, deadline, calculation_mode, currency),
                ).lastrowid
            self.execute(
                "UPDATE savings_goals SET name=?,wallet_id=?,target_minor=?,allocated_minor=?,deadline=?,calculation_mode=?,currency=? WHERE id=?",
                (name, wallet_id, target, allocated, deadline, calculation_mode, currency, goal_id),
            )
            return goal_id

    def add_goal_amount(self, goal_id, amount):
        amount = money_minor(amount)
        if amount == 0:
            raise ValueError(tr("Podaj kwotę różną od zera."))
        with self.transaction():
            self._exists("savings_goals", goal_id)
            goal = self.execute("SELECT * FROM savings_goals WHERE id=?", (goal_id,)).fetchone()
            if goal["calculation_mode"] != "manual":
                raise ValueError(tr("Kwoty można dodawać tylko do celu ręcznego."))
            total = goal["allocated_minor"] + amount
            if not 0 <= total <= MAX_MINOR:
                raise ValueError(tr("Kwota po zmianie nie może być ujemna ani przekraczać limitu."))
            self.execute("UPDATE savings_goals SET allocated_minor=? WHERE id=?", (total, goal_id))

    def rate_records(self):
        return [
            dict(r)
            for r in self.execute("""SELECT c.id,c.code,c.symbol,COALESCE(r.mode,'api') AS mode,
            r.manual_rate,r.api_rate,r.quote_date,r.fetched_at,COALESCE(r.last_error,'') AS last_error
            FROM currencies c LEFT JOIN currency_rates r ON r.code=c.code ORDER BY c.code""")
        ]

    def save_rate_config(self, code, mode, manual_rate=None):
        if mode not in ("api", "manual"):
            raise ValueError(tr("Nieprawidłowy tryb kursu."))
        if not self.execute("SELECT 1 FROM currencies WHERE code=?", (code,)).fetchone():
            raise ValueError(tr("Najpierw dodaj wybraną walutę."))
        if code == "PLN":
            raise ValueError(tr("Kurs PLN jest zawsze równy 1."))
        manual = rate_value(manual_rate) if manual_rate not in (None, "") else None
        if mode == "manual" and manual is None:
            raise ValueError(tr("Podaj kurs ręczny."))
        with self.transaction():
            old = self.execute("SELECT mode FROM currency_rates WHERE code=?", (code,)).fetchone()
            self.execute(
                """INSERT INTO currency_rates(code,mode,manual_rate) VALUES(?,?,?)
                ON CONFLICT(code) DO UPDATE SET mode=excluded.mode,manual_rate=excluded.manual_rate""",
                (code, mode, manual),
            )
            if mode == "api" and (old is None or old["mode"] != "api"):
                self.execute("UPDATE exchange_settings SET last_attempt=NULL WHERE id=1")

    def exchange_config(self):
        return dict(self.execute("SELECT * FROM exchange_settings WHERE id=1").fetchone())

    def save_exchange_config(self, enabled, interval_hours):
        if (
            isinstance(interval_hours, bool)
            or not isinstance(interval_hours, int)
            or not 1 <= interval_hours <= 720
        ):
            raise ValueError(tr("Częstotliwość musi wynosić od 1 do 720 godzin."))
        with self.transaction():
            self.execute(
                "UPDATE exchange_settings SET enabled=?,interval_hours=? WHERE id=1",
                (int(bool(enabled)), interval_hours),
            )

    def store_quote(self, code, rate=None, quote_date=None, error=""):
        if not self.execute("SELECT 1 FROM currencies WHERE code=?", (code,)).fetchone():
            return
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO currency_rates(code) VALUES(?)", (code,))
            if rate is not None:
                self.execute(
                    "UPDATE currency_rates SET api_rate=?,quote_date=?,fetched_at=?,last_error='' WHERE code=?",
                    (
                        rate_value(rate),
                        iso_date(quote_date),
                        datetime.now(timezone.utc).isoformat(),
                        code,
                    ),
                )
                self.store_rate_history(code, [(quote_date, rate)])
            else:
                self.execute(
                    "UPDATE currency_rates SET last_error=? WHERE code=?", (str(error)[:1000], code)
                )

    def effective_rate(self, code):
        if code == "PLN":
            return Decimal(1), "base"
        record = next((r for r in self.rate_records() if r["code"] == code), None)
        if record is None:
            return None, "missing"
        if record["mode"] == "manual":
            return (
                (Decimal(record["manual_rate"]), "manual")
                if record["manual_rate"]
                else (None, "missing")
            )
        if (record["last_error"] or not record["api_rate"]) and record["manual_rate"]:
            return Decimal(record["manual_rate"]), "fallback"
        if record["api_rate"]:
            return Decimal(record["api_rate"]), "cached" if record["last_error"] else "api"
        return None, "missing"
