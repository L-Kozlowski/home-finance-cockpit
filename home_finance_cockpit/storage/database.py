"""SQLite persistence, atomic schema migration and database constraints."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import uuid4

from home_finance_cockpit.domain.analysis_kinds import validate_analysis_kind
from home_finance_cockpit.domain.categories import RULE_COLUMNS
from home_finance_cockpit.domain.category_colors import validate_color
from home_finance_cockpit.domain.validation import (
    MAX_MINOR,
    currency_code,
    iso_date,
    money_minor,
    text,
)
from home_finance_cockpit.domain.wallet_icons import WALLET_ICONS, wallet_icon
from home_finance_cockpit.identity import APP_NAME
from home_finance_cockpit.localization import tr
from home_finance_cockpit.paths import PROJECT_ROOT, data_directory
from home_finance_cockpit.storage.encryption import (
    InvalidPassword,
    PasswordRequired,
    connect,
    export,
    requires_password,
    validate_password,
    verify_file,
)
from home_finance_cockpit.storage.finance_features import FinanceFeatures

ROOT = PROJECT_ROOT
DEFAULT_PATH = data_directory() / "home_finance_cockpit.db"
LEGACY_PATH = ROOT / "Database" / "home_finance_cockpit.db"
SCHEMA_VERSION = 12


class Database(FinanceFeatures):
    @classmethod
    def open_existing(cls, path, password=None):
        """Do not create a missing file or upgrade an unrelated SQLite database."""
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            raise ValueError(tr("Wybrany plik bazy nie istnieje."))
        encrypted = requires_password(target)
        if encrypted and not password:
            raise PasswordRequired(tr("Ta baza wymaga hasła."))
        with closing(connect(target, password if encrypted else None, readonly=True)) as source:
            try:
                source.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except sqlite3.DatabaseError:
                if encrypted:
                    raise InvalidPassword(
                        tr("Nieprawidłowe hasło lub uszkodzony plik bazy.")
                    ) from None
                raise
            tables = {
                r[0]
                for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if not r[0].startswith("sqlite_")
            }
            version = source.execute("PRAGMA user_version").fetchone()[0]
            expected = {"wallets", "transactions", "categories", "currencies", "imports", "rules"}
            legacy = {"wallets", "transactions", "categories", "currencies", "automatizations"}
            if version > SCHEMA_VERSION:
                raise ValueError(tr("Baza pochodzi z nowszej wersji programu."))
            if version in (8, 9, 10, 11, SCHEMA_VERSION):
                expected |= {"savings_goals", "currency_rates", "exchange_settings"}
                if version >= 12:
                    expected |= {"currency_rate_history", "currency_history_requests"}
                valid = tables == expected
            elif version in (1, 2, 3, 4, 5, 6, 7):
                valid = tables == expected
            else:
                valid = {"wallets", "transactions", "categories"} <= tables <= legacy
            if not valid:
                raise ValueError(
                    tr(
                        "To nie jest obsługiwana baza {v0}. Wybierz właściwy plik lub utwórz nową bazę.",
                        v0=APP_NAME,
                    )
                )
            if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError(tr("Wybrana baza jest uszkodzona. Otwórz kopię zapasową."))
        return cls(target, password=password if encrypted else None)

    @classmethod
    def create_new(cls, path, *, starter_language=None):
        """Reserve a new filename exclusively; never truncate an existing file."""
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError(
                tr("Plik już istnieje. Wybierz inną nazwę albo użyj opcji Otwórz bazę.")
            ) from None
        os.close(descriptor)
        database = None
        try:
            database = cls(target)
            if starter_language is not None:
                from home_finance_cockpit.services.starter_data import populate_starter_data

                populate_starter_data(database, starter_language)
            return database
        except Exception:
            if database is not None:
                database.close()
            target.unlink(missing_ok=True)
            raise

    def __init__(self, path=None, *, password=None, use_cipher=False):
        self.path = str(path if path is not None else DEFAULT_PATH)
        self._password = password
        self._use_cipher = bool(password) or use_cipher
        self._depth = 0
        self._deleted_items = []
        self._close_callbacks = []
        if self.path != ":memory:":
            target = Path(self.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path is None and not target.exists() and LEGACY_PATH.exists():
                # The original remains untouched, including if migration fails.
                with closing(
                    sqlite3.connect(LEGACY_PATH.as_uri() + "?mode=ro", uri=True)
                ) as source:
                    with closing(sqlite3.connect(target)) as destination:
                        source.backup(destination)
        if (
            self.path != ":memory:"
            and Path(self.path).exists()
            and requires_password(self.path)
            and not password
        ):
            raise PasswordRequired(tr("Ta baza wymaga hasła."))
        self.conn = connect(self.path, password, use_cipher=self._use_cipher)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        try:
            self._setup()
        except Exception:
            self.conn.close()
            raise

    def close(self):
        for callback in self._close_callbacks:
            callback()
        self._close_callbacks.clear()
        self.conn.close()
        self._password = None

    @property
    def is_encrypted(self):
        return bool(self._password)

    def verify_backup(self, path):
        verify_file(path, self._password)

    def memory_snapshot(self):
        """Decrypted previews stay entirely in RAM, never in a temporary file."""
        copy = Database(":memory:")
        try:
            if not self.is_encrypted:
                self.conn.backup(copy.conn)
            else:
                copy.conn.close()
                copy.conn = connect(":memory:", use_cipher=True)
                copy._use_cipher = True
                copy.conn.execute(
                    "ATTACH DATABASE ? AS original KEY ?", (self.path, self._password)
                )
                try:
                    copy.conn.execute("SELECT sqlcipher_export('main', 'original')").fetchall()
                    version = self.conn.execute("PRAGMA user_version").fetchone()[0]
                    copy.conn.execute(f"PRAGMA user_version={int(version)}")
                finally:
                    copy.conn.execute("DETACH DATABASE original")
                copy.conn.execute("PRAGMA foreign_keys=ON")
            return copy
        except BaseException:
            copy.close()
            raise

    def change_password(self, new_password, current_password=None):
        """Verified export and atomic replacement; keep the old file on failure."""
        if self.path == ":memory:":
            raise ValueError(tr("Zapisz bazę w pliku przed ustawieniem hasła."))
        if self.conn.in_transaction:
            raise ValueError(tr("Poczekaj na zakończenie zapisu do bazy."))
        if self.is_encrypted:
            import hmac

            if not isinstance(current_password, str) or not hmac.compare_digest(
                current_password.encode("utf-8"), self._password.encode("utf-8")
            ):
                raise InvalidPassword(tr("Nieprawidłowe aktualne hasło."))
        if new_password is not None:
            validate_password(new_password)
        target = Path(self.path).resolve()
        if target.is_symlink() or Path(self.path).is_symlink():
            raise ValueError(tr("Otwórz bezpośrednio plik bazy zamiast dowiązania."))
        temporary = target.with_name("." + target.name + "." + uuid4().hex + ".secure")
        old_password = self._password
        closed = False
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            # A rollback journal permits the export reader while preventing concurrent writes.
            mode = self.conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise ValueError(tr("Zamknij inne połączenia z bazą i spróbuj ponownie."))
            self.conn.execute("BEGIN IMMEDIATE")
            with closing(connect(target, old_password, use_cipher=True)) as source:
                export(source, temporary, new_password)
            verify_file(temporary, new_password)
            with temporary.open("r+b") as file:
                os.fsync(file.fileno())
            self.conn.rollback()
            self.conn.close()
            closed = True
            os.replace(temporary, target)
            self._password = new_password
            self._use_cipher = bool(new_password)
        finally:
            if closed:
                self.conn = connect(self.path, self._password, use_cipher=self._use_cipher)
                self.conn.execute("PRAGMA foreign_keys=ON")
                self.conn.execute("PRAGMA busy_timeout=5000")
            elif self.conn.in_transaction:
                self.conn.rollback()
            temporary.unlink(missing_ok=True)

    def backup(self, destination):
        target = Path(destination).resolve()
        if self.path != ":memory:" and target == Path(self.path).resolve():
            raise ValueError(tr("Kopia musi mieć inną ścieżkę niż aktywna baza."))
        if target.exists():
            raise ValueError(tr("Plik kopii już istnieje. Wybierz nową nazwę."))
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.is_encrypted:
            export(self.conn, target, self._password)
        else:
            with closing(sqlite3.connect(target)) as backup:
                self.conn.backup(backup)

    @contextmanager
    def transaction(self):
        """Nested operations use savepoints; no method commits its caller's work."""
        marker = f"unit_{self._depth}"
        self.conn.execute(f"SAVEPOINT {marker}")
        self._depth += 1
        try:
            yield
            self.conn.execute(f"RELEASE SAVEPOINT {marker}")
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {marker}")
            self.conn.execute(f"RELEASE SAVEPOINT {marker}")
            raise
        finally:
            self._depth -= 1

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def _setup(self):
        version = self.execute("PRAGMA user_version").fetchone()[0]
        if version == 11:
            if self.path != ":memory:":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self.backup(Path(self.path).parent / "backups" / f"before_v12_{stamp}.db")
            with self.transaction():
                self._create_rate_history_schema()
                self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version in (9, 10):
            if self.path != ":memory:":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self.backup(Path(self.path).parent / "backups" / f"before_v12_{stamp}.db")
            with self.transaction():
                self._upgrade_wallet_order()
                self._upgrade_category_icons()
                self._create_rate_history_schema()
                self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version == 8:
            if self.path != ":memory:":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self.backup(Path(self.path).parent / "backups" / f"before_v12_{stamp}.db")
            with self.transaction():
                self._upgrade_goals_schema()
                self._upgrade_wallet_order()
                self._upgrade_category_icons()
                self._create_rate_history_schema()
                self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version == 7:
            if self.path != ":memory:":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self.backup(Path(self.path).parent / "backups" / f"before_v12_{stamp}.db")
            with self.transaction():
                self._create_finance_schema()
                self._upgrade_wallet_order()
                self._upgrade_category_icons()
                self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        if version > SCHEMA_VERSION:
            raise ValueError(tr("Baza pochodzi z nowszej wersji programu."))
        if version in (1, 6):
            self._upgrade_v1()
            version = SCHEMA_VERSION
        if version in (2, 3, 4, 5):
            self._upgrade_features(version)
            version = SCHEMA_VERSION
        if version == SCHEMA_VERSION:
            if self.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(tr("Baza zawiera nieprawidłowe powiązania danych."))
            return
        tables = {r[0] for r in self.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = "wallets" in tables
        old = {}
        if legacy:
            if self.path != ":memory:":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self.backup(
                    Path(self.path).parent / "backups" / f"before_v{SCHEMA_VERSION}_{stamp}.db"
                )
            for name in ("wallets", "transactions", "categories", "currencies", "automatizations"):
                old[name] = (
                    [dict(r) for r in self.execute(f"SELECT * FROM {name}")]
                    if name in tables
                    else []
                )
        # Dropping child tables first is safe with foreign key enforcement enabled.
        with self.transaction():
            if legacy:
                for name in (
                    "automatizations",
                    "transactions",
                    "wallets",
                    "categories",
                    "currencies",
                ):
                    if name in tables:
                        self.execute(f"DROP TABLE {name}")
            self._create_schema()
            if legacy:
                self._copy_legacy(old)
            self.execute("INSERT OR IGNORE INTO currencies(code,symbol) VALUES ('PLN','zł')")
            self.execute("INSERT OR IGNORE INTO categories(name,is_default) VALUES ('Ogólne',1)")
            if self.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(tr("Migracja przerwana: nieprawidłowe powiązania w starej bazie."))
            self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _upgrade_v1(self, *, backup=True):
        if backup and self.path != ":memory:":
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.backup(Path(self.path).parent / "backups" / f"before_v{SCHEMA_VERSION}_{stamp}.db")
        order = ("currencies", "categories", "wallets", "imports", "rules", "transactions")
        with self.transaction():
            saved = {
                table: [dict(r) for r in self.execute(f"SELECT * FROM {table}")] for table in order
            }
            for table in reversed(order):
                if table == "categories" and saved[table] and "parent_id" in saved[table][0]:
                    # SQLite RESTRICT also applies to DROP TABLE on a self-referencing tree.
                    while self.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
                        deleted = self.execute(
                            "DELETE FROM categories WHERE id NOT IN (SELECT parent_id FROM categories WHERE parent_id IS NOT NULL)"
                        ).rowcount
                        if not deleted:
                            raise ValueError(tr("Migracja przerwana: cykl w drzewie kategorii."))
                self.execute(f"DROP TABLE {table}")
            self._create_schema()
            for table in order:
                rows = saved[table]
                if table == "categories":
                    pending, rows, inserted = list(rows), [], set()
                    while pending:
                        ready = [
                            r
                            for r in pending
                            if r.get("parent_id") is None or r["parent_id"] in inserted
                        ]
                        if not ready:
                            raise ValueError(
                                tr("Migracja przerwana: nieprawidłowe drzewo kategorii.")
                            )
                        for row in ready:
                            rows.append(row)
                            inserted.add(row["id"])
                            pending.remove(row)
                for row in rows:
                    columns = ",".join('"' + key.replace('"', '""') + '"' for key in row)
                    marks = ",".join("?" for _ in row)
                    self.execute(
                        f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values())
                    )
            if self.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(tr("Migracja kategorii przerwana: nieprawidłowe powiązania."))
            self.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _upgrade_features(self, version):
        if self.path != ":memory:":
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.backup(Path(self.path).parent / "backups" / f"before_v{SCHEMA_VERSION}_{stamp}.db")
        with self.transaction():
            if version == 2:
                self.execute(
                    "ALTER TABLE transactions ADD COLUMN include_in_reports INTEGER NOT NULL DEFAULT 1 CHECK(include_in_reports IN(0,1))"
                )
            if version < 4:
                choices = ",".join("'" + key + "'" for key in WALLET_ICONS)
                self.execute(
                    f"ALTER TABLE wallets ADD COLUMN icon_name TEXT NOT NULL DEFAULT 'wallet' CHECK(icon_name IN({choices}))"
                )
            if version < 5:
                self.execute(
                    "ALTER TABLE categories ADD COLUMN color TEXT DEFAULT NULL CHECK(color IS NULL OR (parent_id IS NULL AND length(color)=7 AND substr(color,1,1)='#' AND substr(color,2) NOT GLOB '*[^0-9A-Fa-f]*'))"
                )
            self.execute(
                "ALTER TABLE transactions ADD COLUMN analysis_kind TEXT NOT NULL DEFAULT 'standard' CHECK(analysis_kind IN('standard','salary','refund','reimbursement','transfer') AND (analysis_kind IN('standard','transfer') OR amount_minor>0))"
            )
            self._upgrade_v1(backup=False)

    def _create_schema(self):
        statements = [
            """CREATE TABLE currencies(
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK(length(code)=3 AND code=upper(code)),
                symbol TEXT NOT NULL CHECK(length(trim(symbol))>0))""",
            """CREATE TABLE categories(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(name))>0),
                parent_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
                icon_name TEXT NOT NULL DEFAULT 'tag',
                is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN(0,1)),
                color TEXT DEFAULT NULL CHECK(color IS NULL OR (parent_id IS NULL AND length(color)=7 AND substr(color,1,1)='#' AND substr(color,2) NOT GLOB '*[^0-9A-Fa-f]*')),
                CHECK(parent_id IS NULL OR (parent_id!=id AND is_default=0)))""",
            "CREATE UNIQUE INDEX root_category_name ON categories(name) WHERE parent_id IS NULL",
            "CREATE UNIQUE INDEX child_category_name ON categories(parent_id,name) WHERE parent_id IS NOT NULL",
            "CREATE UNIQUE INDEX one_default_category ON categories(is_default) WHERE is_default=1",
            """CREATE TRIGGER category_depth_insert BEFORE INSERT ON categories WHEN NEW.parent_id IS NOT NULL
                BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM categories WHERE id=NEW.parent_id AND (parent_id IS NOT NULL OR is_default=1))
                THEN RAISE(ABORT,'Only two category levels are supported') END; END""",
            """CREATE TRIGGER category_depth_update BEFORE UPDATE OF parent_id ON categories WHEN NEW.parent_id IS NOT NULL
                BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM categories WHERE id=NEW.parent_id AND (parent_id IS NOT NULL OR is_default=1))
                OR EXISTS(SELECT 1 FROM categories WHERE parent_id=NEW.id)
                THEN RAISE(ABORT,'Only two category levels are supported') END; END""",
            f"""CREATE TABLE wallets(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name))>0),
                opening_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(opening_minor)='integer' AND abs(opening_minor)<={MAX_MINOR}),
                currency TEXT NOT NULL REFERENCES currencies(code) ON UPDATE CASCADE ON DELETE RESTRICT,
                icon_name TEXT NOT NULL DEFAULT 'wallet' CHECK(icon_name IN({",".join(repr(key) for key in WALLET_ICONS)})),
                sort_order INTEGER NOT NULL DEFAULT 0 CHECK(typeof(sort_order)='integer' AND sort_order>=0),
                opening_date TEXT NOT NULL CHECK(length(opening_date)=10 AND date(opening_date,'+0 days') IS NOT NULL AND date(opening_date,'+0 days')=opening_date))""",
            """CREATE TABLE imports(
                id INTEGER PRIMARY KEY, wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
                file_name TEXT NOT NULL, file_hash TEXT NOT NULL, mapping_json TEXT NOT NULL,
                imported_at TEXT NOT NULL, row_count INTEGER NOT NULL CHECK(row_count>=0),
                UNIQUE(wallet_id,file_hash))""",
            """CREATE TABLE rules(
                id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
                column_name TEXT NOT NULL CHECK(length(trim(column_name))>0),
                pattern TEXT NOT NULL CHECK(length(trim(pattern))>0),
                mode TEXT NOT NULL DEFAULT 'literal' CHECK(mode IN('literal','not_contains','like','exact','starts_with')),
                conditions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(conditions_json) AND json_type(conditions_json)='array'),
                UNIQUE(column_name,pattern,mode,conditions_json))""",
            f"""CREATE TABLE transactions(
                id INTEGER PRIMARY KEY, wallet_id INTEGER NOT NULL REFERENCES wallets(id) ON DELETE RESTRICT,
                amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor!=0 AND abs(amount_minor)<={MAX_MINOR}),
                include_in_reports INTEGER NOT NULL DEFAULT 1 CHECK(include_in_reports IN(0,1)),
                analysis_kind TEXT NOT NULL DEFAULT 'standard' CHECK(analysis_kind IN('standard','salary','refund','reimbursement','transfer') AND (analysis_kind IN('standard','transfer') OR amount_minor>0)),
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
                description TEXT NOT NULL DEFAULT '', from_to TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL CHECK(length(date)=10 AND date(date,'+0 days') IS NOT NULL AND date(date,'+0 days')=date),
                category_source TEXT NOT NULL DEFAULT 'manual' CHECK(category_source IN('manual','unassigned','rule','bank')),
                matched_rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
                category_conflict INTEGER NOT NULL DEFAULT 0 CHECK(category_conflict IN(0,1)),
                import_id INTEGER REFERENCES imports(id) ON DELETE RESTRICT,
                source_line INTEGER, raw_json TEXT, external_id TEXT,
                UNIQUE(import_id,source_line))""",
            "CREATE INDEX tx_wallet_date ON transactions(wallet_id,date)",
            "CREATE UNIQUE INDEX tx_external_id ON transactions(wallet_id,external_id) WHERE external_id IS NOT NULL",
        ]
        for sql in statements:
            self.execute(sql)
        self._create_finance_schema()

    def _copy_legacy(self, old):
        """Normalize the old sign convention by its explicit income/expense type."""

        def convert(value):
            number = Decimal(str(value))
            if not number.is_finite() or abs(number * 100) > MAX_MINOR:
                raise ValueError(tr("Migracja: nieprawidłowa kwota w starej bazie."))
            return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        for row in old["currencies"]:
            self.execute(
                "INSERT INTO currencies(id,code,symbol) VALUES (?,?,?)",
                (row["id"], currency_code(row["code"]), text(row["symbol"], "Symbol")),
            )
        for row in old["wallets"]:
            code = currency_code(row.get("currency") or "PLN")
            self.execute("INSERT OR IGNORE INTO currencies(code,symbol) VALUES (?,?)", (code, code))
        for row in old["categories"]:
            name = text(row["name"], "Kategoria", limit=100)
            self.execute(
                "INSERT INTO categories(id,name,is_default) VALUES (?,?,?)",
                (row["id"], name, int(name.casefold() == "Ogólne".casefold())),
            )
        self.execute("INSERT OR IGNORE INTO categories(name,is_default) VALUES ('Ogólne',1)")
        default = self.default_category_id()
        for row in old["wallets"]:
            dates = [
                iso_date(t["date"]) for t in old["transactions"] if t["wallet_id"] == row["id"]
            ]
            opening_date = min(dates) if dates else iso_date(row["created_at"])
            self.execute(
                "INSERT INTO wallets(id,name,opening_minor,currency,opening_date) VALUES (?,?,?,?,?)",
                (
                    row["id"],
                    text(row["name"], "Portfel", limit=100),
                    convert(row["opening_balance"]),
                    currency_code(row.get("currency") or "PLN"),
                    opening_date,
                ),
            )
        for row in old["transactions"]:
            amount = abs(convert(row["amount"]))
            if row["type"] not in ("income", "expense") or not amount:
                raise ValueError(
                    tr(
                        "Migracja: nieprawidłowa transakcja {v0}. Oryginalna baza pozostaje zachowana.",
                        v0=row["id"],
                    )
                )
            amount *= 1 if row["type"] == "income" else -1
            self.execute(
                """INSERT INTO transactions(id,wallet_id,amount_minor,category_id,description,from_to,date,category_source)
                            VALUES (?,?,?,?,?,?,?,?)""",
                (
                    row["id"],
                    row["wallet_id"],
                    amount,
                    row["category_id"],
                    text(row.get("description"), required=False, limit=5000),
                    text(row.get("from_to"), required=False, limit=500),
                    iso_date(row["date"]),
                    "unassigned" if row["category_id"] == default else "manual",
                ),
            )
        seen = set()
        for row in old["automatizations"]:
            column = row["column_name"]
            pattern = text(row["pattern"], "Reguła")
            if column not in ("description", "from_to"):
                raise ValueError(tr("Migracja: nieobsługiwane pole reguły {v0}.", v0=column))
            key = (column, pattern)
            if key in seen:
                raise ValueError(
                    tr("Migracja: powtórzone reguły. Usuń duplikaty w kopii starej bazy.")
                )
            seen.add(key)
            self.execute(
                "INSERT INTO rules(id,category_id,column_name,pattern,mode) VALUES (?,?,?,?,'like')",
                (row["id"], row["category_id"], column, pattern),
            )

    def default_category_id(self):
        return self.execute("SELECT id FROM categories WHERE is_default=1").fetchone()[0]

    def _upgrade_wallet_order(self):
        if "sort_order" in {row["name"] for row in self.execute("PRAGMA table_info(wallets)")}:
            return
        self.execute(
            "ALTER TABLE wallets ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 CHECK(typeof(sort_order)='integer' AND sort_order>=0)"
        )
        for position, row in enumerate(
            self.execute("SELECT id FROM wallets ORDER BY name,id").fetchall()
        ):
            self.execute("UPDATE wallets SET sort_order=? WHERE id=?", (position, row["id"]))

    def wallets(self):
        return self.execute("SELECT * FROM wallets ORDER BY sort_order,name,id").fetchall()

    def move_wallet(self, wallet_id, direction):
        if direction not in (-1, 1):
            raise ValueError("Invalid wallet movement direction")
        with self.transaction():
            ids = [row["id"] for row in self.wallets()]
            if wallet_id not in ids:
                raise ValueError(tr("Wybrany portfel nie istnieje."))
            current = ids.index(wallet_id)
            destination = current + direction
            if not 0 <= destination < len(ids):
                return
            ids[current], ids[destination] = ids[destination], ids[current]
            for position, identifier in enumerate(ids):
                self.execute("UPDATE wallets SET sort_order=? WHERE id=?", (position, identifier))

    def wallet_balances(self):
        """One snapshot for the wallet table and currency totals, in integer cents."""
        return self.execute("""SELECT w.*, w.opening_minor + COALESCE(SUM(t.amount_minor),0) AS balance,
            COUNT(t.id) AS transaction_count,MAX(t.date) AS last_transaction
            FROM wallets w LEFT JOIN transactions t ON t.wallet_id=w.id
            GROUP BY w.id ORDER BY w.sort_order,w.name,w.id""").fetchall()

    def wallet(self, wallet_id):
        row = self.execute("SELECT * FROM wallets WHERE id=?", (wallet_id,)).fetchone()
        if row is None:
            raise ValueError(tr("Wybrany portfel nie istnieje."))
        return row

    def save_wallet(
        self, name, opening_balance, currency, opening_date, wallet_id=None, *, icon_name=None
    ):
        name = text(name, "Nazwa portfela", limit=100)
        amount = money_minor(opening_balance)
        code = currency_code(currency)
        opening_date = iso_date(opening_date)
        if icon_name is not None:
            wallet_icon(icon_name)
        if not self.execute("SELECT 1 FROM currencies WHERE code=?", (code,)).fetchone():
            raise ValueError(tr("Najpierw dodaj wybraną walutę."))
        with self.transaction():
            if wallet_id is None:
                return self.execute(
                    "INSERT INTO wallets(name,opening_minor,currency,opening_date,icon_name,sort_order) VALUES (?,?,?,?,?,(SELECT COALESCE(MAX(sort_order),-1)+1 FROM wallets))",
                    (name, amount, code, opening_date, icon_name or "wallet"),
                ).lastrowid
            old = self.wallet(wallet_id)
            history = self.execute(
                "SELECT min(date) FROM transactions WHERE wallet_id=?", (wallet_id,)
            ).fetchone()[0]
            if old["currency"] != code and (
                history
                or self.execute("SELECT 1 FROM imports WHERE wallet_id=?", (wallet_id,)).fetchone()
                or self.execute(
                    "SELECT 1 FROM savings_goals WHERE wallet_id=?", (wallet_id,)
                ).fetchone()
            ):
                raise ValueError(
                    tr(
                        "Nie można zmienić waluty portfela z historią lub celami oszczędnościowymi. Utwórz osobny portfel."
                    )
                )
            if history and opening_date > history:
                raise ValueError(
                    tr("Data salda początkowego nie może być późniejsza niż pierwsza transakcja.")
                )
            self.execute(
                "UPDATE wallets SET name=?,opening_minor=?,currency=?,opening_date=?,icon_name=? WHERE id=?",
                (name, amount, code, opening_date, icon_name or old["icon_name"], wallet_id),
            )
            return wallet_id

    def categories(self):
        return self.execute(
            """SELECT c.*,p.name AS parent_name,COALESCE(p.color,c.color) AS effective_color,
            CASE WHEN c.is_default=1 THEN ? WHEN p.id IS NULL THEN c.name ELSE p.name || ' / ' || c.name END AS display_name
            FROM categories c LEFT JOIN categories p ON p.id=c.parent_id
            ORDER BY COALESCE(p.name,c.name),c.parent_id IS NOT NULL,c.name""",
            (tr("Ogólne"),),
        ).fetchall()

    def category(self, category_id):
        for row in self.categories():
            if row["id"] == category_id:
                return row
        raise ValueError(tr("Kategoria nie istnieje."))

    def find_category(self, name, parent_id=None):
        return next(
            (
                c
                for c in self.categories()
                if c["parent_id"] == parent_id and c["name"].casefold() == name.casefold()
            ),
            None,
        )

    def _upgrade_category_icons(self):
        if "icon_name" not in {r["name"] for r in self.execute("PRAGMA table_info(categories)")}:
            self.execute("ALTER TABLE categories ADD COLUMN icon_name TEXT NOT NULL DEFAULT 'tag'")

    def save_category(self, name, category_id=None, parent_id=None, *, color=..., icon_name=None):
        if category_id is not None and self.category(category_id)["is_default"]:
            name = "Ogólne"
        from home_finance_cockpit.domain.category_icons import category_icon

        if icon_name is not None:
            category_icon(icon_name)
        name = text(name, "Kategoria", limit=100)
        if color is not Ellipsis:
            color = validate_color(color)
            if parent_id is not None and color is not None:
                raise ValueError(
                    tr("Kolor ustaw przy kategorii. Podkategorie dziedziczą jej kolor.")
                )
        with self.transaction():
            if parent_id is not None:
                parent = self.category(parent_id)
                if (
                    parent["parent_id"] is not None
                    or parent["is_default"]
                    or parent_id == category_id
                ):
                    raise ValueError(tr("Podkategoria musi należeć do zwykłej kategorii."))
            duplicate = self.find_category(name, parent_id)
            if duplicate is not None and duplicate["id"] != category_id:
                raise ValueError(tr("Taka kategoria już istnieje w tej grupie."))
            if category_id is None:
                return self.execute(
                    "INSERT INTO categories(name,parent_id,color,icon_name) VALUES (?,?,?,?)",
                    (name, parent_id, None if color is Ellipsis else color, icon_name or "tag"),
                ).lastrowid
            self._exists("categories", category_id)
            if parent_id is not None and (
                self.category(category_id)["is_default"]
                or self.execute(
                    "SELECT 1 FROM categories WHERE parent_id=?", (category_id,)
                ).fetchone()
            ):
                raise ValueError(
                    tr(
                        "Kategoria domyślna lub zawierająca podkategorie musi pozostać kategorią nadrzędną."
                    )
                )
            selected_color = self.category(category_id)["color"] if color is Ellipsis else color
            self.execute(
                "UPDATE categories SET name=?,parent_id=?,color=? WHERE id=?",
                (name, parent_id, selected_color if parent_id is None else None, category_id),
            )
            if icon_name is not None:
                self.execute(
                    "UPDATE categories SET icon_name=? WHERE id=?", (icon_name, category_id)
                )
            return category_id

    def set_category_color(self, category_id, color):
        color = validate_color(color)
        with self.transaction():
            if self.category(category_id)["parent_id"] is not None:
                raise ValueError(tr("Kolor ustaw przy kategorii."))
            self.execute("UPDATE categories SET color=? WHERE id=?", (color, category_id))

    def currencies(self):
        return self.execute("SELECT * FROM currencies ORDER BY code").fetchall()

    def save_currency(self, code, symbol, currency_id=None):
        code = currency_code(code)
        symbol = text(symbol, "Symbol", limit=100)
        with self.transaction():
            if currency_id is None:
                return self.execute(
                    "INSERT INTO currencies(code,symbol) VALUES (?,?)", (code, symbol)
                ).lastrowid
            self._exists("currencies", currency_id)
            old_code = self.execute(
                "SELECT code FROM currencies WHERE id=?", (currency_id,)
            ).fetchone()[0]
            if old_code != code and (
                self.execute("SELECT 1 FROM wallets WHERE currency=?", (old_code,)).fetchone()
                or self.execute(
                    "SELECT 1 FROM savings_goals WHERE currency=?", (old_code,)
                ).fetchone()
            ):
                raise ValueError(
                    tr(
                        "Nie można zmienić kodu waluty używanej przez portfele lub cele oszczędnościowe. Dodaj osobną walutę."
                    )
                )
            self.execute(
                "UPDATE currencies SET code=?,symbol=? WHERE id=?", (code, symbol, currency_id)
            )
            if old_code != code:
                self.execute("DELETE FROM currency_rate_history WHERE code=?", (code,))
                self.execute("DELETE FROM currency_history_requests WHERE code=?", (code,))
                self.execute(
                    "UPDATE currency_rates SET mode='api',manual_rate=NULL,api_rate=NULL,quote_date=NULL,fetched_at=NULL,last_error='' WHERE code=?",
                    (code,),
                )
                self.execute("UPDATE exchange_settings SET last_attempt=NULL WHERE id=1")
            return currency_id

    def _exists(self, table, record_id):
        if table not in (
            "categories",
            "currencies",
            "rules",
            "transactions",
            "wallets",
            "savings_goals",
        ):
            raise ValueError(tr("Nieobsługiwany rodzaj danych."))
        if not self.execute(f"SELECT 1 FROM {table} WHERE id=?", (record_id,)).fetchone():
            raise ValueError(tr("Rekord już nie istnieje. Odśwież widok."))

    def delete(self, table, ids):
        if table not in (
            "categories",
            "currencies",
            "rules",
            "transactions",
            "wallets",
            "savings_goals",
        ):
            raise ValueError(tr("Nieobsługiwany rodzaj danych."))
        ids = list(ids)
        rows, links, rate_rows, history_rows, request_rows = [], [], [], [], []
        remember = self._depth == 0
        with self.transaction():
            for record_id in ids:
                self._exists(table, record_id)
                rows.append(
                    dict(self.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone())
                )
                if table == "currencies":
                    rate_rows.extend(
                        dict(r)
                        for r in self.execute(
                            "SELECT * FROM currency_rates WHERE code=?", (rows[-1]["code"],)
                        )
                    )
                    history_rows.extend(
                        dict(r)
                        for r in self.execute(
                            "SELECT * FROM currency_rate_history WHERE code=?", (rows[-1]["code"],)
                        )
                    )
                    request_rows.extend(
                        dict(r)
                        for r in self.execute(
                            "SELECT * FROM currency_history_requests WHERE code=?",
                            (rows[-1]["code"],),
                        )
                    )
                if table == "rules":
                    links.extend(
                        dict(r)
                        for r in self.execute(
                            "SELECT * FROM transactions WHERE matched_rule_id=?", (record_id,)
                        )
                    )
                if table == "categories" and record_id == self.default_category_id():
                    raise ValueError(tr("Nie można usunąć domyślnej kategorii."))
                self.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))
        if remember and rows:
            self._remember_deletion(
                [(table, rows)]
                + ([("currency_rates", rate_rows)] if rate_rows else [])
                + ([("currency_rate_history", history_rows)] if history_rows else [])
                + ([("currency_history_requests", request_rows)] if request_rows else []),
                links,
            )

    def delete_category_tree(self, category_id):
        """Remove a category hierarchy and reassign its transactions atomically."""
        self._exists("categories", category_id)
        if category_id == self.default_category_id():
            raise ValueError(tr("Nie można usunąć domyślnej kategorii."))
        categories = [
            dict(c)
            for c in self.categories()
            if c["id"] == category_id or c["parent_id"] == category_id
        ]
        categories.sort(key=lambda c: c["parent_id"] is not None)
        identifiers = [c["id"] for c in categories]
        placeholders = ",".join("?" for _ in identifiers)
        remember = self._depth == 0
        with self.transaction():
            stored = [
                dict(r)
                for r in self.execute(
                    f"SELECT * FROM categories WHERE id IN ({placeholders}) ORDER BY parent_id,id",
                    identifiers,
                )
            ]
            rules = [
                dict(r)
                for r in self.execute(
                    f"SELECT * FROM rules WHERE category_id IN ({placeholders})", identifiers
                )
            ]
            links = [
                dict(r)
                for r in self.execute(
                    f"SELECT * FROM transactions WHERE category_id IN ({placeholders}) OR matched_rule_id IN (SELECT id FROM rules WHERE category_id IN ({placeholders}))",
                    identifiers + identifiers,
                )
            ]
            self.execute(
                f"UPDATE transactions SET category_id=?,category_source='unassigned',matched_rule_id=NULL,category_conflict=0 WHERE category_id IN ({placeholders})",
                [self.default_category_id(), *identifiers],
            )
            self.execute(f"DELETE FROM rules WHERE category_id IN ({placeholders})", identifiers)
            for identifier in reversed(identifiers):
                self.execute("DELETE FROM categories WHERE id=?", (identifier,))
        if remember:
            self._remember_deletion([("categories", stored), ("rules", rules)], links)

    def _remember_deletion(self, groups, links=()):
        self._deleted_items.append((groups, list(links)))
        self._deleted_items = self._deleted_items[-20:]

    def can_undo_delete(self):
        return bool(self._deleted_items)

    def undo_delete(self):
        if not self._deleted_items:
            raise ValueError(tr("Nie ma usunięcia do cofnięcia w tej sesji."))
        groups, links = self._deleted_items[-1]
        with self.transaction():
            for table, rows in groups:
                for row in rows:
                    exists = (
                        self.execute(
                            "SELECT 1 FROM currency_rate_history WHERE code=? AND quote_date=? AND source=?",
                            (row["code"], row["quote_date"], row["source"]),
                        ).fetchone()
                        if table == "currency_rate_history"
                        else self.execute(
                            f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)
                        ).fetchone()
                    )
                    if exists:
                        raise ValueError(
                            tr(
                                "Nie można cofnąć: identyfikator został użyty przez nowy wpis. Żadne dane nie zostały nadpisane."
                            )
                        )
                    columns = list(row)
                    self.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        tuple(row[c] for c in columns),
                    )
            for row in links:
                current = self.execute(
                    "SELECT * FROM transactions WHERE id=?", (row["id"],)
                ).fetchone()
                expected = dict(row, matched_rule_id=None)
                reassigned = dict(
                    row,
                    category_id=self.default_category_id(),
                    category_source="unassigned",
                    matched_rule_id=None,
                    category_conflict=0,
                )
                if current is not None and dict(current) == reassigned:
                    self.execute(
                        "UPDATE transactions SET category_id=?,category_source=?,matched_rule_id=?,category_conflict=? WHERE id=?",
                        (
                            row["category_id"],
                            row["category_source"],
                            row["matched_rule_id"],
                            row["category_conflict"],
                            row["id"],
                        ),
                    )
                    continue
                if current is not None and dict(current) == expected:
                    self.execute(
                        "UPDATE transactions SET matched_rule_id=? WHERE id=?",
                        (row["matched_rule_id"], row["id"]),
                    )
        self._deleted_items.pop()
        return sum(len(rows) for _, rows in groups)

    def transactions(self, wallet_id=None, *, transaction_id=None):
        sql = """SELECT t.*,w.name AS wallet,w.currency,w.icon_name AS wallet_icon,
                 COALESCE(p.color,c.color) AS category_color,COALESCE(p.id,c.id) AS root_category_id,
                 c.is_default AS is_uncategorized,CASE WHEN c.is_default=1 THEN ? ELSE COALESCE(p.name,c.name) END AS category,
                 CASE WHEN p.id IS NULL THEN '' ELSE c.name END AS subcategory
                 FROM transactions t JOIN wallets w ON w.id=t.wallet_id JOIN categories c ON c.id=t.category_id
                 LEFT JOIN categories p ON p.id=c.parent_id"""
        params = [tr("Ogólne")]
        conditions = []
        if wallet_id is not None:
            conditions.append("t.wallet_id=?")
            params.append(wallet_id)
        if transaction_id is not None:
            conditions.append("t.id=?")
            params.append(transaction_id)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return self.execute(sql + " ORDER BY t.date DESC,t.id DESC", params).fetchall()

    def import_history(self):
        return self.execute("""SELECT i.*,w.name AS wallet,COUNT(t.id) AS current_count FROM imports i
            JOIN wallets w ON w.id=i.wallet_id LEFT JOIN transactions t ON t.import_id=i.id
            GROUP BY i.id ORDER BY i.id DESC""").fetchall()

    def delete_import_transactions(self, import_id, *, expected_count=None):
        """Atomically delete linked transactions and their import history record."""
        remember = self._depth == 0
        with self.transaction():
            if not self.execute("SELECT 1 FROM imports WHERE id=?", (import_id,)).fetchone():
                raise ValueError(tr("Wybrany import już nie istnieje. Odśwież historię."))
            count = self.execute(
                "SELECT COUNT(*) FROM transactions WHERE import_id=?", (import_id,)
            ).fetchone()[0]
            if expected_count is not None and count != expected_count:
                raise ValueError(
                    tr("Liczba transakcji importu zmieniła się. Odśwież historię i ponów usuwanie.")
                )
            history = dict(
                self.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
            )
            rows = [
                dict(r)
                for r in self.execute("SELECT * FROM transactions WHERE import_id=?", (import_id,))
            ]
            deleted = self.execute(
                "DELETE FROM transactions WHERE import_id=?", (import_id,)
            ).rowcount
            self.execute("DELETE FROM imports WHERE id=?", (import_id,))
        if remember:
            self._remember_deletion([("imports", [history]), ("transactions", rows)])
        return deleted

    def set_classification_details(self, transaction_id, rule_id, conflict):
        self.execute(
            "UPDATE transactions SET matched_rule_id=?,category_conflict=? WHERE id=?",
            (rule_id, int(conflict), transaction_id),
        )

    def set_report_inclusion(self, transaction_id, included):
        if not isinstance(included, bool):
            raise ValueError(tr("Wybór udziału w raportach musi być wartością tak/nie."))
        with self.transaction():
            self._exists("transactions", transaction_id)
            self.execute(
                "UPDATE transactions SET include_in_reports=? WHERE id=?",
                (int(included), transaction_id),
            )

    def set_analysis_kind(self, transaction_id, kind):
        with self.transaction():
            self._exists("transactions", transaction_id)
            amount = self.execute(
                "SELECT amount_minor FROM transactions WHERE id=?", (transaction_id,)
            ).fetchone()[0]
            validate_analysis_kind(kind, amount)
            self.execute(
                "UPDATE transactions SET analysis_kind=? WHERE id=?", (kind, transaction_id)
            )

    def save_transaction(
        self,
        wallet_id,
        amount,
        category_id,
        description,
        date_value,
        from_to="",
        transaction_id=None,
        *,
        source="manual",
        import_id=None,
        source_line=None,
        raw_json=None,
        external_id=None,
        analysis_kind=None,
    ):
        wallet = self.wallet(wallet_id)
        minor = money_minor(amount)
        if not minor:
            raise ValueError(tr("Kwota transakcji nie może być zerowa."))
        if analysis_kind is None:
            old_kind = (
                self.execute(
                    "SELECT analysis_kind FROM transactions WHERE id=?", (transaction_id,)
                ).fetchone()
                if transaction_id is not None
                else None
            )
            analysis_kind = old_kind[0] if old_kind else "standard"
        validate_analysis_kind(analysis_kind, minor)
        day = iso_date(date_value)
        if day < wallet["opening_date"]:
            raise ValueError(
                tr("Transakcja jest wcześniejsza niż saldo początkowe portfela. Popraw datę salda.")
            )
        self._exists("categories", category_id)
        description = text(description, "Opis", required=False, limit=5000)
        from_to = text(from_to, "Kontrahent", required=False)
        if source not in ("manual", "unassigned", "rule", "bank"):
            raise ValueError(tr("Nieprawidłowe źródło kategorii."))
        with self.transaction():
            if transaction_id is None:
                return self.execute(
                    """INSERT INTO transactions(wallet_id,amount_minor,category_id,description,date,from_to,
                    category_source,import_id,source_line,raw_json,external_id,analysis_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        wallet_id,
                        minor,
                        category_id,
                        description,
                        day,
                        from_to,
                        source,
                        import_id,
                        source_line,
                        raw_json,
                        external_id,
                        analysis_kind,
                    ),
                ).lastrowid
            self._exists("transactions", transaction_id)
            old = self.execute(
                "SELECT wallet_id FROM transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            if self.wallet(old["wallet_id"])["currency"] != wallet["currency"]:
                raise ValueError(
                    tr(
                        "Przenoszenie transakcji między różnymi walutami wymaga osobnej operacji wymiany."
                    )
                )
            self.execute(
                """UPDATE transactions SET wallet_id=?,amount_minor=?,category_id=?,description=?,date=?,from_to=?,
                         category_source=?,matched_rule_id=NULL,category_conflict=0,analysis_kind=? WHERE id=?""",
                (
                    wallet_id,
                    minor,
                    category_id,
                    description,
                    day,
                    from_to,
                    source,
                    analysis_kind,
                    transaction_id,
                ),
            )
            return transaction_id

    def relocate_transactions(self, transaction_ids, wallet_id, *, copy=False):
        """Move a selection atomically; copies are independent of import deletion."""
        identifiers = list(dict.fromkeys(transaction_ids))
        if not identifiers:
            raise ValueError(tr("Zaznacz transakcje."))
        with self.transaction():
            target = self.wallet(wallet_id)
            rows = []
            for identifier in identifiers:
                row = self.execute(
                    "SELECT * FROM transactions WHERE id=?", (identifier,)
                ).fetchone()
                if row is None:
                    raise ValueError(tr("Transakcja już nie istnieje. Odśwież listę."))
                if self.wallet(row["wallet_id"])["currency"] != target["currency"]:
                    raise ValueError(
                        tr(
                            "Przenoszenie transakcji między różnymi walutami wymaga osobnej operacji wymiany."
                        )
                    )
                if row["date"] < target["opening_date"]:
                    raise ValueError(
                        tr(
                            "Transakcja jest wcześniejsza niż saldo początkowe portfela. Popraw datę salda."
                        )
                    )
                rows.append(row)
            result = []
            for row in rows:
                if copy:
                    columns = [
                        key
                        for key in row.keys()
                        if key not in ("id", "wallet_id", "import_id", "source_line", "external_id")
                    ]
                    result.append(
                        self.execute(
                            f"INSERT INTO transactions(wallet_id,{','.join(columns)}) VALUES ({','.join('?' for _ in range(len(columns) + 1))})",
                            [wallet_id, *(row[key] for key in columns)],
                        ).lastrowid
                    )
                else:
                    if (
                        row["external_id"] is not None
                        and self.execute(
                            "SELECT 1 FROM transactions WHERE wallet_id=? AND external_id=? AND id<>?",
                            (wallet_id, row["external_id"], row["id"]),
                        ).fetchone()
                    ):
                        raise ValueError(
                            tr("Portfel docelowy zawiera już transakcję z tym samym ID z banku.")
                        )
                    self.execute(
                        "UPDATE transactions SET wallet_id=? WHERE id=?", (wallet_id, row["id"])
                    )
                    result.append(row["id"])
            return result

    def move_import(self, import_id, wallet_id):
        """Move an import and every surviving linked transaction in one commit."""
        with self.transaction():
            record = self.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
            if record is None:
                raise ValueError(tr("Wybrany import już nie istnieje. Odśwież historię."))
            target = self.wallet(wallet_id)
            if self.wallet(record["wallet_id"])["currency"] != target["currency"]:
                raise ValueError(
                    tr(
                        "Przenoszenie transakcji między różnymi walutami wymaga osobnej operacji wymiany."
                    )
                )
            if self.execute(
                "SELECT 1 FROM imports WHERE wallet_id=? AND file_hash=? AND id<>?",
                (wallet_id, record["file_hash"], import_id),
            ).fetchone():
                raise ValueError(tr("Ten plik został już zaimportowany do portfela docelowego."))
            identifiers = [
                r[0]
                for r in self.execute("SELECT id FROM transactions WHERE import_id=?", (import_id,))
            ]
            if identifiers:
                self.relocate_transactions(identifiers, wallet_id)
            self.execute("UPDATE imports SET wallet_id=? WHERE id=?", (wallet_id, import_id))
            return len(identifiers)

    def rules(self):
        return self.execute("""SELECT r.*,COALESCE(p.name,c.name) AS category,
            CASE WHEN p.id IS NULL THEN '' ELSE c.name END AS subcategory
            FROM rules r JOIN categories c ON c.id=r.category_id LEFT JOIN categories p ON p.id=c.parent_id ORDER BY r.id""").fetchall()

    def rule_columns(self):
        return dict(RULE_COLUMNS)

    def save_rule(
        self, category_id, column_name, pattern, mode="literal", rule_id=None, *, conditions=None
    ):
        self._exists("categories", category_id)
        if category_id == self.default_category_id():
            raise ValueError(tr("Reguła musi przypisywać kategorię inną niż domyślna."))
        from home_finance_cockpit.domain.categories import rule_conditions, validate_conditions

        if conditions is None and rule_id is not None:
            self._exists("rules", rule_id)
            conditions = json.loads(
                self.execute("SELECT conditions_json FROM rules WHERE id=?", (rule_id,)).fetchone()[
                    0
                ]
            )
        if conditions is not None and not isinstance(conditions, list):
            raise ValueError(tr("Warunki reguły muszą być listą."))
        checked = validate_conditions(
            [dict(column_name=column_name, mode=mode, pattern=pattern)] + (conditions or [])
        )
        pattern = checked[0]["pattern"]
        extras = sorted(
            checked[1:], key=lambda c: (c["column_name"], c["mode"], c["pattern"].casefold())
        )
        encoded = json.dumps(extras, ensure_ascii=False, sort_keys=True)

        def signature(items):
            return sorted((c["column_name"], c["mode"], c["pattern"].casefold()) for c in items)

        for rule in self.rules():
            if rule["id"] != rule_id and signature(rule_conditions(rule)) == signature(checked):
                raise ValueError(tr("Taka reguła już istnieje."))
        with self.transaction():
            if rule_id is None:
                return self.execute(
                    "INSERT INTO rules(category_id,column_name,pattern,mode,conditions_json) VALUES (?,?,?,?,?)",
                    (category_id, column_name, pattern, mode, encoded),
                ).lastrowid
            self._exists("rules", rule_id)
            self.execute(
                "UPDATE rules SET category_id=?,column_name=?,pattern=?,mode=?,conditions_json=? WHERE id=?",
                (category_id, column_name, pattern, mode, encoded, rule_id),
            )
            return rule_id
