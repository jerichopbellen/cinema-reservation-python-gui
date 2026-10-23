"""SQLite connection helpers.

Every connection opened through this module has foreign-key enforcement
turned on and returns rows as ``sqlite3.Row`` objects. The default database
location is resolved relative to this package, so the application behaves the
same no matter which working directory it is launched from.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "cinema.db"
DEFAULT_TIMEOUT_SECONDS = 5.0


def connect(db_path: Path | str | None = None,
            timeout: float = DEFAULT_TIMEOUT_SECONDS) -> sqlite3.Connection:
    """Open a configured connection, creating the database directory if needed.

    ``timeout`` is how long a write waits for another connection's lock before
    raising ``sqlite3.OperationalError``. The caller owns the returned
    connection and must close it. Prefer :func:`get_connection` or
    :func:`write_transaction` unless you need manual lifetime control.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        conn.close()
        raise
    return conn


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a connection that commits on success, rolls back on error, and always closes."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def write_transaction(db_path: Path | str | None = None,
                      timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside an explicit ``BEGIN IMMEDIATE`` transaction.

    The write lock is taken up front, so reads made inside the block cannot be
    invalidated by another writer before this transaction commits. Everything
    is committed together on success and rolled back on any exception.
    """
    conn = connect(db_path, timeout=timeout)
    conn.isolation_level = None  # manage BEGIN/COMMIT explicitly
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
