"""Administrator movie management: list, create, edit, archive, restore, delete.

Every operation re-checks the caller's role against the database through
:meth:`~services.auth_service.AuthService.require_admin`; the GUI only passes
the signed-in user's ID, never a role.

Removal is history-safe. A movie that has never had showtimes is deleted
outright. A movie with showtimes or bookings is *archived* instead
(``movies.is_active = 0``): it disappears from the customer catalog and can no
longer be booked, but its showtimes, bookings, and receipts are untouched.
Archiving is reversible with :meth:`MovieAdminService.restore_movie`.

Editing a movie never alters saved bookings: each booking stores its own total
and a snapshot of the movie title, so a price or title change only affects
future bookings. This module has no Tkinter dependency.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection, write_transaction
from services.auth_service import AuthService
from services.errors import UserFacingError

AGE_RATINGS = ("G", "PG", "R-13", "R-16", "R-18")
TITLE_MAX_LENGTH = 120
GENRE_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 600
DURATION_MAX_MINUTES = 600
PRICE_MAX_CENTAVOS = 10_000_00  # ₱10,000.00

# "350", "350.5", "1,250.00": digits with optional thousands commas and up to 2 decimals.
_PRICE_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")


class MovieAdminError(UserFacingError):
    """A movie management operation could not be completed."""


class MovieValidationError(MovieAdminError):
    """A form value is invalid. ``field`` names the offending form field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class MovieNotFoundError(MovieAdminError):
    def __init__(self) -> None:
        super().__init__("That movie no longer exists. The list has been refreshed.")


@dataclass(frozen=True)
class MovieDraft:
    """Validated movie fields, ready to store. ``ticket_price`` is integer centavos."""

    title: str
    genre: str
    duration_minutes: int
    age_rating: str
    description: str
    ticket_price: int


@dataclass(frozen=True)
class AdminMovie:
    id: int
    title: str
    genre: str
    duration_minutes: int
    age_rating: str
    description: str
    ticket_price: int
    is_active: bool
    showtime_count: int
    booking_count: int

    @property
    def can_delete(self) -> bool:
        """True when nothing references the movie, so deleting loses no history."""
        return self.showtime_count == 0 and self.booking_count == 0


# --- Validation ---------------------------------------------------------------

def _clean_text(value: str, field: str, label: str, max_length: int) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        raise MovieValidationError(field, f"Please enter a {label}.")
    if len(cleaned) > max_length:
        raise MovieValidationError(field, f"The {label} must be at most {max_length} characters.")
    return cleaned


def parse_duration(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        raise MovieValidationError("duration_minutes", "Please enter the running time in minutes.")
    if not cleaned.isdigit():
        raise MovieValidationError("duration_minutes", "Running time must be a whole number of minutes.")
    minutes = int(cleaned)
    if not 0 < minutes <= DURATION_MAX_MINUTES:
        raise MovieValidationError(
            "duration_minutes", f"Running time must be between 1 and {DURATION_MAX_MINUTES} minutes.")
    return minutes


def parse_price(text: str) -> int:
    """Parse a peso amount such as ``"₱1,250.50"`` into integer centavos without floats."""
    cleaned = (text or "").strip().replace("₱", "").replace("PHP", "").replace("Php", "").strip()
    if not cleaned:
        raise MovieValidationError("ticket_price", "Please enter the ticket price in pesos.")
    if cleaned.startswith("-"):
        raise MovieValidationError("ticket_price", "The ticket price cannot be negative.")
    match = _PRICE_PATTERN.fullmatch(cleaned)
    if match is None:
        raise MovieValidationError(
            "ticket_price", "Enter the price as a peso amount, for example 350 or 350.50.")
    pesos = int(match.group(1).replace(",", ""))
    cents = int((match.group(2) or "").ljust(2, "0"))
    centavos = pesos * 100 + cents
    if centavos > PRICE_MAX_CENTAVOS:
        raise MovieValidationError("ticket_price", "The ticket price must be at most ₱10,000.00.")
    return centavos


def validate_movie(title: str, genre: str, duration: str, age_rating: str, description: str,
                   price: str) -> MovieDraft:
    """Validate raw form text. Raises :class:`MovieValidationError` naming the bad field."""
    rating = (age_rating or "").strip().upper()
    if not rating:
        raise MovieValidationError("age_rating", "Please choose an age rating.")
    if rating not in AGE_RATINGS:
        raise MovieValidationError("age_rating", f"Choose one of: {', '.join(AGE_RATINGS)}.")
    return MovieDraft(
        title=_clean_text(title, "title", "title", TITLE_MAX_LENGTH),
        genre=_clean_text(genre, "genre", "genre", GENRE_MAX_LENGTH),
        duration_minutes=parse_duration(duration),
        age_rating=rating,
        description=_clean_text(description, "description", "description", DESCRIPTION_MAX_LENGTH),
        ticket_price=parse_price(price),
    )


# --- Service ------------------------------------------------------------------

_LIST_SQL = """
    SELECT m.id, m.title, m.genre, m.duration_minutes, m.age_rating, m.description,
           m.ticket_price, m.is_active,
           (SELECT COUNT(*) FROM showtimes s WHERE s.movie_id = m.id) AS showtime_count,
           (SELECT COUNT(*) FROM bookings b JOIN showtimes s ON s.id = b.showtime_id
             WHERE s.movie_id = m.id) AS booking_count
    FROM movies m
"""


def _row_to_movie(row: sqlite3.Row) -> AdminMovie:
    return AdminMovie(
        id=row["id"], title=row["title"], genre=row["genre"],
        duration_minutes=row["duration_minutes"], age_rating=row["age_rating"],
        description=row["description"], ticket_price=row["ticket_price"],
        is_active=bool(row["is_active"]), showtime_count=row["showtime_count"],
        booking_count=row["booking_count"],
    )


class MovieAdminService:
    """Movie management for administrators. Each method takes the acting user's ID."""

    def __init__(self, db_path: Path | str | None = None, auth: AuthService | None = None) -> None:
        self.db_path = db_path
        self.auth = auth or AuthService(db_path)

    def list_movies(self, admin_id: int) -> list[AdminMovie]:
        """All movies, active first, then alphabetically."""
        self.auth.require_admin(admin_id)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(f"{_LIST_SQL} ORDER BY m.is_active DESC, m.title COLLATE NOCASE").fetchall()
        return [_row_to_movie(row) for row in rows]

    def get_movie(self, admin_id: int, movie_id: int) -> AdminMovie:
        self.auth.require_admin(admin_id)
        with get_connection(self.db_path) as conn:
            row = conn.execute(f"{_LIST_SQL} WHERE m.id = ?", (movie_id,)).fetchone()
        if row is None:
            raise MovieNotFoundError()
        return _row_to_movie(row)

    def create_movie(self, admin_id: int, draft: MovieDraft) -> AdminMovie:
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            self._ensure_unique_title(conn, draft.title)
            cursor = conn.execute(
                "INSERT INTO movies (title, genre, duration_minutes, age_rating, description, "
                "ticket_price) VALUES (?, ?, ?, ?, ?, ?)",
                (draft.title, draft.genre, draft.duration_minutes, draft.age_rating,
                 draft.description, draft.ticket_price),
            )
            movie_id = cursor.lastrowid
        return self.get_movie(admin_id, movie_id)

    def update_movie(self, admin_id: int, movie_id: int, draft: MovieDraft) -> AdminMovie:
        """Save new details. The ID, showtimes, and all saved bookings are unchanged."""
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            if conn.execute("SELECT 1 FROM movies WHERE id = ?", (movie_id,)).fetchone() is None:
                raise MovieNotFoundError()
            self._ensure_unique_title(conn, draft.title, exclude_id=movie_id)
            conn.execute(
                "UPDATE movies SET title = ?, genre = ?, duration_minutes = ?, age_rating = ?, "
                "description = ?, ticket_price = ? WHERE id = ?",
                (draft.title, draft.genre, draft.duration_minutes, draft.age_rating,
                 draft.description, draft.ticket_price, movie_id),
            )
        return self.get_movie(admin_id, movie_id)

    def remove_movie(self, admin_id: int, movie_id: int) -> str:
        """Delete the movie if nothing references it, otherwise archive it.

        Returns ``"deleted"`` or ``"archived"``. The decision is made inside the
        same transaction as the change, so a showtime added concurrently can
        never be orphaned.
        """
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            row = conn.execute(f"{_LIST_SQL} WHERE m.id = ?", (movie_id,)).fetchone()
            if row is None:
                raise MovieNotFoundError()
            movie = _row_to_movie(row)
            if movie.can_delete:
                conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
                return "deleted"
            conn.execute("UPDATE movies SET is_active = 0 WHERE id = ?", (movie_id,))
            return "archived"

    def restore_movie(self, admin_id: int, movie_id: int) -> AdminMovie:
        """Make an archived movie visible and bookable again."""
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            updated = conn.execute("UPDATE movies SET is_active = 1 WHERE id = ?", (movie_id,)).rowcount
            if updated != 1:
                raise MovieNotFoundError()
        return self.get_movie(admin_id, movie_id)

    @staticmethod
    def _ensure_unique_title(conn: sqlite3.Connection, title: str, exclude_id: int | None = None) -> None:
        clash = conn.execute(
            "SELECT 1 FROM movies WHERE lower(title) = lower(?) AND id IS NOT ?",
            (title, exclude_id),
        ).fetchone()
        if clash:
            raise MovieValidationError("title", "A movie with this title already exists.")
