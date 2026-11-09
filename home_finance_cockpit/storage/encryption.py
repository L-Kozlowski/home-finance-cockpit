"""SQLCipher connections; passwords live in memory, never in preferences."""

import sqlite3
from contextlib import closing
from functools import wraps
from pathlib import Path

from sqlcipher3 import dbapi2 as cipher

from home_finance_cockpit.localization import tr


class PasswordRequired(ValueError):
    pass


class InvalidPassword(ValueError):
    pass


def compatible_errors(method):
    """Keep the application's existing sqlite3 error handling effective."""

    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except cipher.Error as exc:
            error = getattr(sqlite3, type(exc).__name__, sqlite3.DatabaseError)
            raise error(str(exc)) from None

    return call


class CipherCursor(cipher.Cursor):
    execute = compatible_errors(cipher.Cursor.execute)
    executemany = compatible_errors(cipher.Cursor.executemany)
    executescript = compatible_errors(cipher.Cursor.executescript)
    fetchone = compatible_errors(cipher.Cursor.fetchone)
    fetchmany = compatible_errors(cipher.Cursor.fetchmany)
    fetchall = compatible_errors(cipher.Cursor.fetchall)
    __next__ = compatible_errors(cipher.Cursor.__next__)


class CipherConnection(cipher.Connection):
    @compatible_errors
    def cursor(self, factory=CipherCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql):
        return self.cursor().executescript(sql)

    commit = compatible_errors(cipher.Connection.commit)
    rollback = compatible_errors(cipher.Connection.rollback)
    backup = compatible_errors(cipher.Connection.backup)
    close = compatible_errors(cipher.Connection.close)


def requires_password(path):
    with Path(path).open("rb") as source:
        header = source.read(16)
    return bool(header) and header != b"SQLite format 3\x00"


def connect(path, password=None, *, readonly=False, use_cipher=False):
    filename = Path(path).resolve().as_uri() + "?mode=ro" if readonly else str(path)
    if password or use_cipher:
        connection = cipher.connect(filename, uri=readonly, factory=CipherConnection)
        try:
            if not connection.execute("PRAGMA cipher_version").fetchone():
                raise RuntimeError("SQLCipher is unavailable.")
            # Expected authentication failures are presented by the UI, not native debug logs.
            connection.execute("PRAGMA cipher_log_level=NONE")
            if password:
                connection.set_key(password)
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.row_factory = cipher.Row
        except BaseException:
            connection.close()
            raise
    else:
        connection = sqlite3.connect(filename, uri=readonly)
        connection.row_factory = sqlite3.Row
    return connection


def validate_password(password):
    if not isinstance(password, str) or "\x00" in password or not 8 <= len(password) <= 1024:
        raise ValueError(tr("Hasło musi mieć od 8 do 1024 znaków i nie może zawierać znaku NUL."))


def verify_file(path, password=None):
    with closing(connect(path, password, readonly=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(tr("Weryfikacja bazy nie powiodła się."))
        if password and connection.execute("PRAGMA cipher_integrity_check").fetchall():
            raise ValueError(tr("Weryfikacja szyfrowania nie powiodła się."))
        if password and (
            not requires_password(path)
            or str(connection.execute("PRAGMA cipher_status").fetchone()[0]) != "1"
        ):
            raise ValueError(tr("Weryfikacja szyfrowania nie powiodła się."))


def export(connection, destination, password):
    """Export directly to the target cipher, including schema version and sequence."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.execute(
        "ATTACH DATABASE ? AS secured_copy KEY ?", (str(destination), password or "")
    )
    try:
        connection.execute("SELECT sqlcipher_export('secured_copy')").fetchall()
        connection.execute(f"PRAGMA secured_copy.user_version={int(version)}")
    finally:
        connection.execute("DETACH DATABASE secured_copy")
