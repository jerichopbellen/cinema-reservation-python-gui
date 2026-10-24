"""Administrator showtime management: list, add, remove (or deactivate), restore,
and review each showtime's confirmed bookings.

Like movie management, every operation re-checks the caller's role in the
database through :meth:`~services.auth_service.AuthService.require_admin`.

Scheduling rules: a showtime must start in the future, belong to an active
movie, use a known auditorium, and not overlap another active showtime in the
same auditorium. A screening occupies its auditorium for the movie's running
time plus :data:`CLEANING_MINUTES`.

Removal rules: an upcoming showtime with confirmed bookings cannot be removed
(those customers must cancel first). Otherwise a showtime that has never had
a booking is deleted, and one with booking history (past or canceled) is
deactivated so that history is kept. This module has no Tkinter dependency.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection, write_transaction
from database.seed import AUDITORIUMS
from services.auth_service import AuthService
from services.catalog_service import SHOWTIME_KEY_FORMAT
from services.errors import UserFacingError
from services.seating_service import ALL_SEATS

CLEANING_MINUTES = 15
_TIME_PATTERN = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class ShowtimeAdminError(UserFacingError):
    """A showtime management operation could not be completed."""


class ShowtimeValidationError(ShowtimeAdminError):
    """A form value is invalid. ``field`` names the offending form field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class ShowtimeNotFoundError(ShowtimeAdminError):
    def __init__(self) -> None:
        super().__init__("That showtime no longer exists. The list has been refreshed.")


@dataclass(frozen=True)
class AdminShowtime:
    id: int
    movie_id: int
    starts_at: dt.datetime
    ends_at: dt.datetime  # running time only, without the cleaning gap
    auditorium: str
    is_active: bool
    booking_count: int     # every booking ever made, including canceled ones
    confirmed_count: int   # bookings still confirmed

    def has_started(self, now: dt.datetime) -> bool:
        return self.starts_at <= now

    def is_locked(self, now: dt.datetime) -> bool:
        """True while removal is blocked: upcoming with confirmed bookings."""
        return self.confirmed_count > 0 and not self.has_started(now)

    def removal_outcome(self) -> str:
        """What removing it would do (when not locked): ``"deleted"`` or ``"deactivated"``."""
        return "deleted" if self.booking_count == 0 else "deactivated"


@dataclass(frozen=True)
class ShowtimeBooking:
    """One confirmed booking for a showtime, as an administrator sees it."""

    id: int
    reference: str
    customer_name: str
    username: str
    seat_labels: tuple[str, ...]
    total_amount: int  # centavos
    created_at: str    # UTC "YYYY-MM-DD HH:MM:SS"

    @property
    def ticket_count(self) -> int:
        return len(self.seat_labels)


@dataclass(frozen=True)
class ShowtimeBookings:
    """A showtime's confirmed bookings plus the totals an administrator needs."""

    showtime: AdminShowtime
    movie_title: str
    bookings: tuple[ShowtimeBooking, ...]
    canceled_count: int
    capacity: int = len(ALL_SEATS)

    @property
    def seats_sold(self) -> int:
        return sum(booking.ticket_count for booking in self.bookings)

    @property
    def revenue(self) -> int:
        return sum(booking.total_amount for booking in self.bookings)


# --- Validation ---------------------------------------------------------------

def parse_show_date(text: str) -> dt.date:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ShowtimeValidationError("show_date", "Please enter the date as YYYY-MM-DD.")
    if not _DATE_PATTERN.fullmatch(cleaned):
        raise ShowtimeValidationError("show_date", "Enter the date as YYYY-MM-DD, for example 2026-11-05.")
    try:
        return dt.date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ShowtimeValidationError("show_date", f"{cleaned} is not a real calendar date.") from exc


def parse_show_time(text: str) -> dt.time:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ShowtimeValidationError("show_time", "Please enter the start time as HH:MM (24-hour).")
    match = _TIME_PATTERN.fullmatch(cleaned)
    if match is None:
        raise ShowtimeValidationError("show_time", "Enter a 24-hour time such as 09:30 or 19:45.")
    return dt.time(int(match.group(1)), int(match.group(2)))


def parse_auditorium(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned not in AUDITORIUMS:
        raise ShowtimeValidationError("auditorium", f"Choose one of: {', '.join(AUDITORIUMS)}.")
    return cleaned


# --- Service ------------------------------------------------------------------

_SELECT = """
    SELECT s.id, s.movie_id, s.show_date, s.show_time, s.auditorium, s.is_active,
           m.duration_minutes,
           (SELECT COUNT(*) FROM bookings b WHERE b.showtime_id = s.id) AS booking_count,
           (SELECT COUNT(*) FROM bookings b WHERE b.showtime_id = s.id
             AND b.status = 'confirmed') AS confirmed_count
    FROM showtimes s JOIN movies m ON m.id = s.movie_id
"""


def _row_to_showtime(row: sqlite3.Row) -> AdminShowtime:
    starts_at = dt.datetime.strptime(f"{row['show_date']} {row['show_time']}", SHOWTIME_KEY_FORMAT)
    return AdminShowtime(
        id=row["id"], movie_id=row["movie_id"], starts_at=starts_at,
        ends_at=starts_at + dt.timedelta(minutes=row["duration_minutes"]),
        auditorium=row["auditorium"], is_active=bool(row["is_active"]),
        booking_count=row["booking_count"], confirmed_count=row["confirmed_count"],
    )


class ShowtimeAdminService:
    """Showtime scheduling for administrators. Each method takes the acting user's ID."""

    def __init__(self, db_path: Path | str | None = None, auth: AuthService | None = None,
                 now: Callable[[], dt.datetime] = dt.datetime.now) -> None:
        self.db_path = db_path
        self.auth = auth or AuthService(db_path)
        self._now = now

    def list_showtimes(self, admin_id: int, movie_id: int) -> list[AdminShowtime]:
        """All showtimes for a movie, earliest first."""
        self.auth.require_admin(admin_id)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(f"{_SELECT} WHERE s.movie_id = ? ORDER BY s.show_date, s.show_time",
                                (movie_id,)).fetchall()
        return [_row_to_showtime(row) for row in rows]

    def add_showtime(self, admin_id: int, movie_id: int, show_date: str, show_time: str,
                     auditorium: str) -> AdminShowtime:
        """Schedule a screening after validating the slot. Raises ShowtimeValidationError."""
        self.auth.require_admin(admin_id)
        starts_at = dt.datetime.combine(parse_show_date(show_date), parse_show_time(show_time))
        auditorium = parse_auditorium(auditorium)
        if starts_at <= self._now():
            raise ShowtimeValidationError("show_time", "The showtime must be in the future.")

        with write_transaction(self.db_path) as conn:
            movie = conn.execute("SELECT is_active, duration_minutes FROM movies WHERE id = ?",
                                 (movie_id,)).fetchone()
            if movie is None:
                raise ShowtimeAdminError("That movie no longer exists.")
            if not movie["is_active"]:
                raise ShowtimeAdminError("This movie is archived. Restore it before adding showtimes.")
            self._ensure_auditorium_free(conn, auditorium, starts_at, movie["duration_minutes"])
            try:
                cursor = conn.execute(
                    "INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) VALUES (?, ?, ?, ?)",
                    (movie_id, starts_at.date().isoformat(), starts_at.strftime("%H:%M"), auditorium),
                )
            except sqlite3.IntegrityError as exc:
                if "UNIQUE" not in str(exc):
                    raise
                # Only an inactive showtime can hold the exact slot (active ones failed the overlap check).
                raise ShowtimeValidationError(
                    "show_time", f"{auditorium} has a deactivated showtime at exactly this time. Restore "
                                 "it instead, or choose a different start time.") from exc
            showtime_id = cursor.lastrowid
        return self._get(showtime_id)

    def remove_showtime(self, admin_id: int, showtime_id: int) -> str:
        """Delete or deactivate a showtime. Returns ``"deleted"`` or ``"deactivated"``.

        Refuses (``ShowtimeAdminError``) while an upcoming showtime has confirmed
        bookings. The check and the change happen in one transaction, so a booking
        made at the same moment cannot slip through.
        """
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE s.id = ?", (showtime_id,)).fetchone()
            if row is None:
                raise ShowtimeNotFoundError()
            showtime = _row_to_showtime(row)
            if showtime.is_locked(self._now()):
                count = showtime.confirmed_count
                raise ShowtimeAdminError(
                    f"This showtime has {count} confirmed booking{'s' if count != 1 else ''}, so it "
                    "cannot be removed until those customers cancel.")
            if showtime.removal_outcome() == "deleted":
                conn.execute("DELETE FROM showtimes WHERE id = ?", (showtime_id,))
                return "deleted"
            conn.execute("UPDATE showtimes SET is_active = 0 WHERE id = ?", (showtime_id,))
            return "deactivated"

    def restore_showtime(self, admin_id: int, showtime_id: int) -> AdminShowtime:
        """Reactivate a deactivated, still-upcoming showtime if its slot is free."""
        self.auth.require_admin(admin_id)
        with write_transaction(self.db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE s.id = ?", (showtime_id,)).fetchone()
            if row is None:
                raise ShowtimeNotFoundError()
            showtime = _row_to_showtime(row)
            if showtime.is_active:
                raise ShowtimeAdminError("This showtime is already active.")
            if showtime.has_started(self._now()):
                raise ShowtimeAdminError("This showtime has already started, so it cannot be restored.")
            movie_active = conn.execute("SELECT is_active FROM movies WHERE id = ?",
                                        (showtime.movie_id,)).fetchone()[0]
            if not movie_active:
                raise ShowtimeAdminError("This movie is archived. Restore it before restoring showtimes.")
            self._ensure_auditorium_free(conn, showtime.auditorium, showtime.starts_at,
                                         int((showtime.ends_at - showtime.starts_at).total_seconds() // 60),
                                         exclude_id=showtime.id)
            conn.execute("UPDATE showtimes SET is_active = 1 WHERE id = ?", (showtime_id,))
        return self._get(showtime_id)

    def list_confirmed_bookings(self, admin_id: int, showtime_id: int) -> ShowtimeBookings:
        """The showtime's confirmed bookings, earliest first, with their seats and customers.

        Canceled bookings are excluded (only counted), and released seats are never listed.
        """
        self.auth.require_admin(admin_id)
        with get_connection(self.db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE s.id = ?", (showtime_id,)).fetchone()
            if row is None:
                raise ShowtimeNotFoundError()
            showtime = _row_to_showtime(row)
            movie_title = conn.execute("SELECT title FROM movies WHERE id = ?",
                                       (showtime.movie_id,)).fetchone()[0]
            booking_rows = conn.execute(
                """
                SELECT b.id, b.booking_reference, b.total_amount, b.created_at,
                       u.full_name, u.username
                FROM bookings b JOIN users u ON u.id = b.user_id
                WHERE b.showtime_id = ? AND b.status = 'confirmed'
                ORDER BY b.created_at, b.id
                """,
                (showtime_id,),
            ).fetchall()
            seats: dict[int, list[tuple[str, int]]] = {r["id"]: [] for r in booking_rows}
            for seat in conn.execute(
                "SELECT bs.booking_id, bs.seat_row, bs.seat_number FROM booked_seats bs "
                "JOIN bookings b ON b.id = bs.booking_id "
                "WHERE bs.showtime_id = ? AND bs.is_released = 0 AND b.status = 'confirmed'",
                (showtime_id,),
            ):
                seats[seat["booking_id"]].append((seat["seat_row"], seat["seat_number"]))
        bookings = tuple(
            ShowtimeBooking(
                id=r["id"], reference=r["booking_reference"], customer_name=r["full_name"],
                username=r["username"],
                seat_labels=tuple(f"{row_}{number}" for row_, number in sorted(seats[r["id"]])),
                total_amount=r["total_amount"], created_at=r["created_at"],
            )
            for r in booking_rows
        )
        return ShowtimeBookings(showtime=showtime, movie_title=movie_title, bookings=bookings,
                                canceled_count=showtime.booking_count - showtime.confirmed_count)

    def _get(self, showtime_id: int) -> AdminShowtime:
        with get_connection(self.db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE s.id = ?", (showtime_id,)).fetchone()
        if row is None:
            raise ShowtimeNotFoundError()
        return _row_to_showtime(row)

    @staticmethod
    def _ensure_auditorium_free(conn: sqlite3.Connection, auditorium: str, starts_at: dt.datetime,
                                duration_minutes: int, exclude_id: int | None = None) -> None:
        """Reject a slot that overlaps another active showtime (plus cleaning) in the auditorium."""
        gap = dt.timedelta(minutes=CLEANING_MINUTES)
        new_end = starts_at + dt.timedelta(minutes=duration_minutes) + gap
        # Neighbouring days too, so screenings that cross midnight are caught.
        days = [(starts_at.date() + dt.timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
        rows = conn.execute(
            f"""
            SELECT s.show_date, s.show_time, m.duration_minutes, m.title
            FROM showtimes s JOIN movies m ON m.id = s.movie_id
            WHERE s.auditorium = ? AND s.is_active = 1 AND s.id IS NOT ?
              AND s.show_date IN ({', '.join('?' for _ in days)})
            """,
            (auditorium, exclude_id, *days),
        ).fetchall()
        for row in rows:
            other_start = dt.datetime.strptime(f"{row['show_date']} {row['show_time']}", SHOWTIME_KEY_FORMAT)
            other_end = other_start + dt.timedelta(minutes=row["duration_minutes"]) + gap
            if starts_at < other_end and other_start < new_end:
                raise ShowtimeValidationError(
                    "show_time",
                    f"{auditorium} is busy then: “{row['title']}” runs from "
                    f"{other_start:%H:%M} to {(other_end - gap):%H:%M}, plus {CLEANING_MINUTES} minutes "
                    "for cleaning. Choose another time or cinema.")
