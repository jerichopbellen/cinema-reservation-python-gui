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


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a configured connection, creating the database directory if needed.

    The caller owns the returned connection and must close it. Prefer
    :func:`get_connection` unless you need manual lifetime control.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
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
