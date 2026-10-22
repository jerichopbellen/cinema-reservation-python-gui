"""Database package: connection handling, schema, and sample data."""

from __future__ import annotations

import logging
from pathlib import Path

from database.connection import DEFAULT_DB_PATH, connect, get_connection
from database.schema import create_schema
from database.seed import seed_sample_data

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_DB_PATH", "connect", "get_connection", "initialize_database"]


def initialize_database(db_path: Path | str | None = None) -> Path:
    """Create missing tables and seed sample data on first run.

    Safe to call on every launch: existing tables and records are left
    untouched. Returns the resolved database path.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    with get_connection(path) as conn:
        create_schema(conn)
        if seed_sample_data(conn):
            logger.info("Seeded sample movies and showtimes into %s", path)
    return path
