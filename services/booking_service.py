"""Booking creation, history, and cancellation.

All writes happen inside :func:`~database.connection.write_transaction`
(``BEGIN IMMEDIATE``), so availability checks and inserts are atomic with
respect to other connections and processes. The partial unique index
``ux_booked_seats_active_seat`` is the final guard against double booking:
even if two writers raced past the availability check, only one could commit
a given active seat.

Statuses stored in ``bookings.status`` are ``confirmed`` and ``canceled``.
"Completed" (a confirmed booking whose showtime has started) is derived when
displaying history and is never written back to the database.

Price per ticket is not stored separately; every seat in a booking is sold at
the same price, so it is derived exactly as ``total_amount // ticket_count``.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection, write_transaction
from services.catalog_service import SHOWTIME_KEY_FORMAT, CatalogService
from services.errors import UserFacingError
from services.seating_service import CANCELED_STATUS, Seat, fetch_booked_seats

logger = logging.getLogger(__name__)

STATUS_CONFIRMED = "confirmed"
STATUS_CANCELED = CANCELED_STATUS
DISPLAY_UPCOMING = "Upcoming"
DISPLAY_COMPLETED = "Completed"
DISPLAY_CANCELED = "Canceled"

REFERENCE_PREFIX = "CR"
# Crockford-style alphabet without look-alike characters (0/O, 1/I/L).
REFERENCE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
REFERENCE_LENGTH = 10   # 31**10 ≈ 8 × 10^14 possible references
REFERENCE_ATTEMPTS = 5

# SQLite's message when ux_booked_seats_active_seat rejects an insert.
SEAT_UNIQUE_VIOLATION = "UNIQUE constraint failed: booked_seats.showtime_id"


class BookingError(UserFacingError):
    """A booking could not be created, found, or changed."""


class BookingNotFoundError(BookingError):
    def __init__(self) -> None:
        super().__init__("That booking could not be found.")


class SeatConflictError(BookingError):
    """Another booking holds one or more of the requested seats."""

    def __init__(self, seats: Iterable[Seat] = ()) -> None:
        self.seats = frozenset(seats)
        if self.seats:
            taken = ", ".join(seat.label for seat in sorted(self.seats))
            verb = "was" if len(self.seats) == 1 else "were"
            detail = f"{taken} {verb} just booked by someone else."
        else:
            detail = "One or more of your seats were just booked by someone else."
        super().__init__(f"{detail} Please go back, refresh the seat map, and choose available seats.")


class BookingBusyError(BookingError):
    def __init__(self) -> None:
        super().__init__("The booking system is busy right now. Please try again in a moment.")


class CancellationError(BookingError):
    """The booking exists but cannot be canceled."""


@dataclass(frozen=True)
class BookingDetails:
    """A saved booking as read back from the database."""

    id: int
    reference: str
    user_id: int
    customer_name: str
    movie_title: str
    starts_at: dt.datetime
    auditorium: str
    seat_labels: tuple[str, ...]
    total_amount: int  # centavos
    status: str
    created_at: str  # UTC "YYYY-MM-DD HH:MM:SS"

    @property
    def ticket_count(self) -> int:
        return len(self.seat_labels)

    @property
    def price_per_ticket(self) -> int:
        return self.total_amount // self.ticket_count if self.ticket_count else 0

    @property
    def is_canceled(self) -> bool:
        return self.status == STATUS_CANCELED

    def has_started(self, now: dt.datetime) -> bool:
        return self.starts_at <= now

    def can_cancel(self, now: dt.datetime) -> bool:
        return self.status == STATUS_CONFIRMED and not self.has_started(now)

    def display_status(self, now: dt.datetime) -> str:
        if self.is_canceled:
            return DISPLAY_CANCELED
        return DISPLAY_COMPLETED if self.has_started(now) else DISPLAY_UPCOMING


def generate_booking_reference() -> str:
    """Return a random reference such as ``CR-7KQ2MX9TPA``."""
    body = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
    return f"{REFERENCE_PREFIX}-{body}"


def parse_seat_selection(seats: Iterable[Seat | str]) -> tuple[Seat, ...]:
    """Validate seat identifiers against the layout and reject duplicates."""
    parsed: list[Seat] = []
    for seat in seats:
        if isinstance(seat, Seat):
            parsed.append(seat)
            continue
        try:
            parsed.append(Seat.parse(str(seat)))
        except ValueError as exc:
            raise BookingError(f"{seat!r} is not a valid seat.") from exc
    if not parsed:
        raise BookingError("Please select at least one seat.")
    duplicates = sorted({seat for seat in parsed if parsed.count(seat) > 1})
    if duplicates:
        labels = ", ".join(seat.label for seat in duplicates)
        raise BookingError(f"Seat {labels} was selected more than once.")
    return tuple(sorted(parsed))


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


_BOOKING_SELECT = """
    SELECT b.id, b.booking_reference, b.user_id, b.total_amount, b.status, b.created_at,
           u.full_name, m.title, s.show_date, s.show_time, s.auditorium
    FROM bookings b
    JOIN users u ON u.id = b.user_id
    JOIN showtimes s ON s.id = b.showtime_id
    JOIN movies m ON m.id = s.movie_id
"""


class BookingService:
    """Creates, reads, and cancels bookings. Every read is scoped to one user."""

    def __init__(self, db_path: Path | str | None = None,
                 catalog: CatalogService | None = None, lock_timeout: float = 5.0) -> None:
        self.db_path = db_path
        self.catalog = catalog or CatalogService(db_path)
        self.lock_timeout = lock_timeout

    # --- Creating -------------------------------------------------------------

    def create_booking(self, user_id: int, showtime_id: int,
                       seats: Iterable[Seat | str]) -> BookingDetails:
        """Atomically book ``seats`` for ``user_id`` and return the committed booking.

        Raises :class:`BookingError` subclasses (including :class:`SeatConflictError`
        and :class:`BookingBusyError`) or
        :class:`~services.catalog_service.ShowtimeUnavailableError`.
        """
        requested = parse_seat_selection(seats)
        try:
            with write_transaction(self.db_path, timeout=self.lock_timeout) as conn:
                if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                    raise BookingError("Your account could not be found. Please log in again.")

                movie, showtime = self.catalog.load_bookable_showtime(conn, showtime_id)
                taken = fetch_booked_seats(conn, showtime.id) & set(requested)
                if taken:
                    raise SeatConflictError(taken)

                total = movie.ticket_price * len(requested)
                booking_id = self._insert_booking(conn, user_id, showtime.id, total)
                try:
                    conn.executemany(
                        "INSERT INTO booked_seats (booking_id, showtime_id, seat_row, seat_number) "
                        "VALUES (?, ?, ?, ?)",
                        [(booking_id, showtime.id, seat.row, seat.number) for seat in requested],
                    )
                except sqlite3.IntegrityError as exc:
                    if SEAT_UNIQUE_VIOLATION not in str(exc):
                        raise
                    # The unique index caught a seat claimed by another committed booking.
                    raise SeatConflictError() from exc
        except sqlite3.OperationalError as exc:
            if _is_lock_error(exc):
                raise BookingBusyError() from exc
            raise

        # Only reached after COMMIT succeeded.
        logger.info("Booking %s committed for user %s", booking_id, user_id)
        return self.get_booking(user_id, booking_id)

    @staticmethod
    def _insert_booking(conn: sqlite3.Connection, user_id: int, showtime_id: int, total: int) -> int:
        for _ in range(REFERENCE_ATTEMPTS):
            reference = generate_booking_reference()
            try:
                cursor = conn.execute(
                    "INSERT INTO bookings (booking_reference, user_id, showtime_id, total_amount, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (reference, user_id, showtime_id, total, STATUS_CONFIRMED),
                )
                return cursor.lastrowid
            except sqlite3.IntegrityError as exc:
                if "booking_reference" not in str(exc):
                    raise
                logger.warning("Booking reference collision; generating a new one")
        raise BookingError("A booking reference could not be generated. Please try again.")

    # --- Reading --------------------------------------------------------------

    def get_booking(self, user_id: int, booking_id: int) -> BookingDetails:
        """Load one of ``user_id``'s bookings. Other users' bookings are reported as not found."""
        with get_connection(self.db_path) as conn:
            bookings = self._load(conn, "WHERE b.id = ? AND b.user_id = ?", (booking_id, user_id))
        if not bookings:
            raise BookingNotFoundError()
        return bookings[0]

    def list_bookings(self, user_id: int) -> list[BookingDetails]:
        """All of the user's bookings: upcoming confirmed ones first (soonest first),
        then completed and canceled ones (most recent showtime first)."""
        with get_connection(self.db_path) as conn:
            bookings = self._load(conn, "WHERE b.user_id = ?", (user_id,))
        now = self.catalog.now()
        upcoming = sorted((b for b in bookings if b.can_cancel(now)), key=lambda b: (b.starts_at, b.id))
        others = sorted((b for b in bookings if not b.can_cancel(now)),
                        key=lambda b: (b.starts_at, b.id), reverse=True)
        return upcoming + others

    @staticmethod
    def _load(conn: sqlite3.Connection, where: str, params: tuple) -> list[BookingDetails]:
        rows = conn.execute(f"{_BOOKING_SELECT} {where}", params).fetchall()
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        placeholders = ", ".join("?" for _ in ids)
        seats: dict[int, list[tuple[str, int]]] = {booking_id: [] for booking_id in ids}
        for seat in conn.execute(
            f"SELECT booking_id, seat_row, seat_number FROM booked_seats "
            f"WHERE booking_id IN ({placeholders})", ids,
        ):
            seats[seat["booking_id"]].append((seat["seat_row"], seat["seat_number"]))

        bookings = []
        for row in rows:
            try:
                starts_at = dt.datetime.strptime(f"{row['show_date']} {row['show_time']}",
                                                 SHOWTIME_KEY_FORMAT)
            except ValueError:
                logger.warning("Booking %s has a showtime with malformed date/time", row["id"])
                starts_at = dt.datetime.min
            bookings.append(BookingDetails(
                id=row["id"], reference=row["booking_reference"], user_id=row["user_id"],
                customer_name=row["full_name"], movie_title=row["title"], starts_at=starts_at,
                auditorium=row["auditorium"],
                seat_labels=tuple(f"{r}{n}" for r, n in sorted(seats[row["id"]])),
                total_amount=row["total_amount"], status=row["status"], created_at=row["created_at"],
            ))
        return bookings

    # --- Canceling ------------------------------------------------------------

    def cancel_booking(self, user_id: int, booking_id: int) -> BookingDetails:
        """Cancel a confirmed, not-yet-started booking and release its seats atomically."""
        now_key = self.catalog.now().strftime(SHOWTIME_KEY_FORMAT)
        try:
            with write_transaction(self.db_path, timeout=self.lock_timeout) as conn:
                row = conn.execute(
                    "SELECT b.status, s.show_date || ' ' || s.show_time AS starts "
                    "FROM bookings b JOIN showtimes s ON s.id = b.showtime_id "
                    "WHERE b.id = ? AND b.user_id = ?",
                    (booking_id, user_id),
                ).fetchone()
                if row is None:
                    raise BookingNotFoundError()
                if row["status"] == STATUS_CANCELED:
                    raise CancellationError("This booking has already been canceled.")
                if row["status"] != STATUS_CONFIRMED:
                    raise CancellationError("This booking cannot be canceled.")
                if row["starts"] <= now_key:
                    raise CancellationError(
                        "This showtime has already started, so the booking can no longer be canceled.")

                # The status guard makes a concurrent second cancellation a no-op.
                updated = conn.execute(
                    "UPDATE bookings SET status = ? WHERE id = ? AND user_id = ? AND status = ?",
                    (STATUS_CANCELED, booking_id, user_id, STATUS_CONFIRMED),
                ).rowcount
                if updated != 1:
                    raise CancellationError("This booking has already been canceled.")
                conn.execute("UPDATE booked_seats SET is_released = 1 WHERE booking_id = ?", (booking_id,))
        except sqlite3.OperationalError as exc:
            if _is_lock_error(exc):
                raise BookingBusyError() from exc
            raise

        logger.info("Booking %s canceled by user %s", booking_id, user_id)
        return self.get_booking(user_id, booking_id)
