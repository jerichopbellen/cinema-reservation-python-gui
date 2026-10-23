"""Shared fixtures for tests that need a seeded database and a controllable clock."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from database.connection import get_connection
from database.schema import create_schema
from database.seed import seed_sample_data

SEED_DAY = dt.date(2030, 1, 1)          # sample showtimes run Jan 2–4, 2030
START_CLOCK = dt.datetime(2030, 1, 2, 12, 0)


class FakeClock:
    """A callable returning a settable "now", for services that accept ``now=``."""

    def __init__(self, moment: dt.datetime = START_CLOCK) -> None:
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment


def create_seeded_database(db_path: Path) -> None:
    """Create the schema and sample data in ``db_path``, with showtimes relative to SEED_DAY."""
    with get_connection(db_path) as conn:
        create_schema(conn)
        seed_sample_data(conn, today=SEED_DAY)
