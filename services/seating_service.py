"""Seat layout, availability, and in-memory seat selection.

The database is the source of truth for taken seats: a seat is unavailable for
a showtime when a ``booked_seats`` row for that showtime is not released and its
booking is not canceled. Selections live only in memory; nothing in this module
writes to the database.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection
from services.catalog_service import CatalogService, Movie, Showtime
from services.errors import UserFacingError

SEAT_ROWS = "ABCDEFGH"
SEATS_PER_ROW = 10
CANCELED_STATUS = "canceled"

_SEAT_LABEL = re.compile(r"([A-Z])(\d{1,2})")


class SeatSelectionError(UserFacingError):
    """A seat cannot be selected, or the selection cannot continue."""


class EmptySelectionError(SeatSelectionError):
    def __init__(self) -> None:
        super().__init__("Please select at least one seat to continue.")


class SeatsUnavailableError(SeatSelectionError):
    """Some selected seats were taken after the screen loaded."""

    def __init__(self, conflicts: frozenset[Seat], booked: frozenset[Seat]) -> None:
        labels = ", ".join(seat.label for seat in sorted(conflicts))
        verb = "is" if len(conflicts) == 1 else "are"
        super().__init__(
            f"Sorry, {labels} {verb} no longer available. Your selection has been updated."
        )
        self.conflicts = conflicts
        self.booked = booked


@dataclass(frozen=True, order=True)
class Seat:
    """A seat position. ``label`` (e.g. ``"A1"``) is the identifier used everywhere."""

    row: str
    number: int

    def __post_init__(self) -> None:
        if self.row not in SEAT_ROWS or not 1 <= self.number <= SEATS_PER_ROW:
            raise ValueError(f"Seat {self.row}{self.number} is outside the auditorium layout.")

    @property
    def label(self) -> str:
        return f"{self.row}{self.number}"

    @classmethod
    def parse(cls, label: str) -> Seat:
        match = _SEAT_LABEL.fullmatch(label.strip().upper())
        if match is None:
            raise ValueError(f"Invalid seat label: {label!r}")
        return cls(match.group(1), int(match.group(2)))


ALL_SEATS: tuple[Seat, ...] = tuple(
    Seat(row, number) for row in SEAT_ROWS for number in range(1, SEATS_PER_ROW + 1)
)


class SeatSelection:
    """Seats picked for one showtime, with totals computed in integer centavos.

    The ticket price comes from the database-loaded :class:`Movie`, never from the GUI.
    """

    def __init__(self, movie: Movie, showtime: Showtime) -> None:
        if movie.id != showtime.movie_id:
            raise ValueError("Showtime does not belong to the given movie.")
        self.movie = movie
        self.showtime = showtime
        self._seats: set[Seat] = set()

    @property
    def seats(self) -> tuple[Seat, ...]:
        return tuple(sorted(self._seats))

    @property
    def labels(self) -> list[str]:
        return [seat.label for seat in self.seats]

    @property
    def count(self) -> int:
        return len(self._seats)

    @property
    def price_per_ticket(self) -> int:
        return self.movie.ticket_price

    @property
    def total(self) -> int:
        return self.price_per_ticket * self.count

    def is_selected(self, seat: Seat) -> bool:
        return seat in self._seats

    def toggle(self, seat: Seat, unavailable: frozenset[Seat] | set[Seat]) -> bool:
        """Select or deselect ``seat``. Returns True if it is now selected."""
        if seat in self._seats:
            self._seats.remove(seat)
            return False
        if seat in unavailable:
            raise SeatSelectionError(f"Seat {seat.label} is already booked.")
        self._seats.add(seat)
        return True

    def discard(self, seats: frozenset[Seat] | set[Seat]) -> None:
        self._seats.difference_update(seats)

    def clear(self) -> None:
        self._seats.clear()

    def update_movie(self, movie: Movie) -> None:
        """Adopt freshly loaded movie data (e.g. a changed price) for the same movie."""
        if movie.id != self.movie.id:
            raise ValueError("Cannot switch the selection to a different movie.")
        self.movie = movie


@dataclass(frozen=True)
class PendingCheckout:
    """A validated, not-yet-booked selection handed to the checkout stage."""

    movie: Movie
    showtime: Showtime
    seats: tuple[Seat, ...]
    price_per_ticket: int
    total: int


def fetch_booked_seats(conn: sqlite3.Connection, showtime_id: int) -> frozenset[Seat]:
    """Seats held by non-canceled, non-released bookings for a showtime."""
    rows = conn.execute(
        """
        SELECT bs.seat_row, bs.seat_number
        FROM booked_seats bs
        JOIN bookings b ON b.id = bs.booking_id
        WHERE bs.showtime_id = ? AND bs.is_released = 0 AND b.status <> ?
        """,
        (showtime_id, CANCELED_STATUS),
    ).fetchall()
    seats = set()
    for row in rows:
        try:
            seats.add(Seat(row["seat_row"], row["seat_number"]))
        except ValueError:
            continue  # outside the current layout; cannot collide with a selectable seat
    return frozenset(seats)


class SeatingService:
    """Reads seat availability and validates selections. Never writes to the database."""

    def __init__(self, db_path: Path | str | None = None,
                 catalog: CatalogService | None = None) -> None:
        self.db_path = db_path
        self.catalog = catalog or CatalogService(db_path)

    def get_booked_seats(self, showtime_id: int) -> frozenset[Seat]:
        with get_connection(self.db_path) as conn:
            return fetch_booked_seats(conn, showtime_id)

    def open_showtime(self, showtime_id: int) -> tuple[Movie, Showtime, frozenset[Seat]]:
        """Validate the showtime is bookable and load its current availability."""
        movie, showtime = self.catalog.get_bookable_showtime(showtime_id)
        return movie, showtime, self.get_booked_seats(showtime.id)

    def prepare_checkout(self, selection: SeatSelection) -> PendingCheckout:
        """Recheck the showtime and every selected seat against the database.

        Raises :class:`EmptySelectionError`, :class:`SeatsUnavailableError`, or
        :class:`~services.catalog_service.ShowtimeUnavailableError`.
        """
        if selection.count == 0:
            raise EmptySelectionError()
        movie, showtime = self.catalog.get_bookable_showtime(selection.showtime.id)
        selection.update_movie(movie)

        booked = self.get_booked_seats(showtime.id)
        conflicts = frozenset(selection.seats) & booked
        if conflicts:
            selection.discard(conflicts)
            raise SeatsUnavailableError(conflicts, booked)

        return PendingCheckout(movie=movie, showtime=showtime, seats=selection.seats,
                               price_per_ticket=selection.price_per_ticket, total=selection.total)
