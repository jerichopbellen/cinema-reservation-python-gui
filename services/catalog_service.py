"""Movie catalog and showtime queries.

Showtime dates and times are stored as local ``YYYY-MM-DD`` and ``HH:MM`` text.
A showtime is *bookable* only while it, and its movie, are active and its start
time is still in the future. This module has no Tkinter dependency.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection
from services.errors import UserFacingError

logger = logging.getLogger(__name__)

SHOWTIME_KEY_FORMAT = "%Y-%m-%d %H:%M"


class CatalogError(UserFacingError):
    """A movie or showtime cannot be shown or selected."""


class ShowtimeUnavailableError(CatalogError):
    """The showtime is missing, inactive, belongs to an inactive movie, or has started."""


@dataclass(frozen=True)
class Movie:
    id: int
    title: str
    genre: str
    duration_minutes: int
    age_rating: str
    description: str
    ticket_price: int  # centavos


@dataclass(frozen=True)
class Showtime:
    id: int
    movie_id: int
    starts_at: dt.datetime  # local, naive
    auditorium: str


_MOVIE_COLUMNS = ("m.id, m.title, m.genre, m.duration_minutes, m.age_rating, m.description, "
                  "m.ticket_price")


def _row_to_movie(row: sqlite3.Row) -> Movie:
    return Movie(id=row["id"], title=row["title"], genre=row["genre"],
                 duration_minutes=row["duration_minutes"], age_rating=row["age_rating"],
                 description=row["description"], ticket_price=row["ticket_price"])


def _parse_showtime(row: sqlite3.Row) -> Showtime | None:
    """Build a Showtime from a row, or return None (and log) if its date/time is malformed."""
    try:
        starts_at = dt.datetime.strptime(f"{row['show_date']} {row['show_time']}", SHOWTIME_KEY_FORMAT)
    except (TypeError, ValueError):
        logger.warning("Skipping showtime %s with malformed date/time", row["showtime_id"])
        return None
    return Showtime(id=row["showtime_id"], movie_id=row["movie_id"], starts_at=starts_at,
                    auditorium=row["auditorium"])


class CatalogService:
    """Read-only access to active movies and their upcoming showtimes."""

    def __init__(self, db_path: Path | str | None = None,
                 now: Callable[[], dt.datetime] = dt.datetime.now) -> None:
        self.db_path = db_path
        self._now = now

    def list_active_movies(self) -> list[Movie]:
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT {_MOVIE_COLUMNS} FROM movies m WHERE m.is_active = 1 ORDER BY m.title"
            ).fetchall()
        return [_row_to_movie(row) for row in rows]

    def get_active_movie(self, movie_id: int) -> Movie:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT {_MOVIE_COLUMNS} FROM movies m WHERE m.id = ? AND m.is_active = 1",
                (movie_id,),
            ).fetchone()
        if row is None:
            raise CatalogError("This movie is no longer available.")
        return _row_to_movie(row)

    def list_upcoming_showtimes(self, movie_id: int) -> list[Showtime]:
        """Active, not-yet-started showtimes for an active movie, earliest first."""
        now_key = self._now().strftime(SHOWTIME_KEY_FORMAT)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT s.id AS showtime_id, s.movie_id, s.show_date, s.show_time, s.auditorium
                FROM showtimes s
                JOIN movies m ON m.id = s.movie_id
                WHERE s.movie_id = ? AND s.is_active = 1 AND m.is_active = 1
                  AND s.show_date || ' ' || s.show_time > ?
                ORDER BY s.show_date, s.show_time, s.auditorium
                """,
                (movie_id, now_key),
            ).fetchall()
        showtimes = [_parse_showtime(row) for row in rows]
        return [showtime for showtime in showtimes if showtime is not None]

    def get_bookable_showtime(self, showtime_id: int) -> tuple[Movie, Showtime]:
        """Return the showtime and its movie, or raise :class:`ShowtimeUnavailableError`."""
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT {_MOVIE_COLUMNS}, m.is_active AS movie_active,
                       s.id AS showtime_id, s.movie_id, s.show_date, s.show_time, s.auditorium,
                       s.is_active AS showtime_active
                FROM showtimes s
                JOIN movies m ON m.id = s.movie_id
                WHERE s.id = ?
                """,
                (showtime_id,),
            ).fetchone()
        if row is None:
            raise ShowtimeUnavailableError("This showtime could not be found.")
        if not row["showtime_active"] or not row["movie_active"]:
            raise ShowtimeUnavailableError("This showtime is no longer available.")
        showtime = _parse_showtime(row)
        if showtime is None:
            raise ShowtimeUnavailableError("This showtime has invalid schedule data and cannot be booked.")
        if showtime.starts_at <= self._now():
            raise ShowtimeUnavailableError("This showtime has already started and can no longer be booked.")
        return _row_to_movie(row), showtime
