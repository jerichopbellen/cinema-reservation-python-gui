"""Stage 3 tests: movie catalog, showtimes, seat availability, and seat selection.

Each test uses its own temporary SQLite database seeded relative to a fixed
date, with a controllable clock, so "past" and "upcoming" are deterministic.
The real application database is never opened, and no Tkinter windows are created.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.connection import DEFAULT_DB_PATH, connect, get_connection
from database.schema import create_schema
from database.seed import SAMPLE_MOVIES, seed_sample_data
from services.auth_service import User
from services.catalog_service import CatalogError, CatalogService, ShowtimeUnavailableError
from services.seating_service import (
    ALL_SEATS,
    EmptySelectionError,
    Seat,
    SeatingService,
    SeatSelection,
    SeatSelectionError,
    SeatsUnavailableError,
)
from services.session import Session
from utils.formatting import format_duration, format_show_date, format_show_time

SEED_DAY = dt.date(2030, 1, 1)          # sample showtimes run Jan 2–4, 2030
START_CLOCK = dt.datetime(2030, 1, 2, 12, 0)


class FakeClock:
    def __init__(self, moment: dt.datetime) -> None:
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "catalog.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        with get_connection(self.db_path) as conn:
            create_schema(conn)
            seed_sample_data(conn, today=SEED_DAY)

        self.clock = FakeClock(START_CLOCK)
        self.catalog = CatalogService(self.db_path, now=self.clock)
        self.seating = SeatingService(self.db_path, self.catalog)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

    # --- helpers --------------------------------------------------------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def movie_id(self, title: str = "The Last Lighthouse Keeper") -> int:
        return self.conn.execute("SELECT id FROM movies WHERE title = ?", (title,)).fetchone()[0]

    def upcoming(self, movie_id: int | None = None):
        return self.catalog.list_upcoming_showtimes(movie_id or self.movie_id())

    def book(self, showtime_id: int, seats: list[str], status: str = "confirmed",
             released: int = 0) -> int:
        """Insert a booking directly (Stage 4 will own real booking creation)."""
        user_row = self.conn.execute("SELECT id FROM users WHERE username = 'tester'").fetchone()
        user_id = user_row[0] if user_row else self.execute(
            "INSERT INTO users (full_name, username, password_hash, password_salt) "
            "VALUES ('Tester', 'tester', 'h', 's')").lastrowid
        reference = f"REF-{self.count('bookings') + 1}"
        booking_id = self.execute(
            "INSERT INTO bookings (booking_reference, user_id, showtime_id, total_amount, status) "
            "VALUES (?, ?, ?, 0, ?)", (reference, user_id, showtime_id, status)).lastrowid
        for label in seats:
            seat = Seat.parse(label)
            self.execute(
                "INSERT INTO booked_seats (booking_id, showtime_id, seat_row, seat_number, is_released) "
                "VALUES (?, ?, ?, ?, ?)", (booking_id, showtime_id, seat.row, seat.number, released))
        return booking_id

    def new_selection(self, showtime_id: int | None = None) -> SeatSelection:
        showtime_id = showtime_id or self.upcoming()[0].id
        movie, showtime, _booked = self.seating.open_showtime(showtime_id)
        return SeatSelection(movie, showtime)


class MovieCatalogTests(CatalogTestCase):
    def test_lists_active_movies_from_database(self) -> None:
        movies = self.catalog.list_active_movies()
        self.assertEqual(len(movies), len(SAMPLE_MOVIES))
        self.assertEqual([m.title for m in movies], sorted(m["title"] for m in SAMPLE_MOVIES))
        lighthouse = next(m for m in movies if m.title == "The Last Lighthouse Keeper")
        self.assertEqual((lighthouse.genre, lighthouse.duration_minutes, lighthouse.age_rating,
                          lighthouse.ticket_price), ("Drama", 118, "PG", 35000))
        self.assertTrue(lighthouse.description)

    def test_inactive_movies_are_excluded(self) -> None:
        hidden = self.movie_id("Orbitfall")
        self.execute("UPDATE movies SET is_active = 0 WHERE id = ?", (hidden,))
        titles = [m.title for m in self.catalog.list_active_movies()]
        self.assertNotIn("Orbitfall", titles)
        self.assertEqual(len(titles), len(SAMPLE_MOVIES) - 1)
        with self.assertRaises(CatalogError):
            self.catalog.get_active_movie(hidden)
        self.assertEqual(self.catalog.list_upcoming_showtimes(hidden), [])

    def test_empty_catalog_returns_empty_list(self) -> None:
        self.execute("UPDATE movies SET is_active = 0")
        self.assertEqual(self.catalog.list_active_movies(), [])

    def test_missing_movie_raises(self) -> None:
        with self.assertRaises(CatalogError):
            self.catalog.get_active_movie(9999)


class ShowtimeTests(CatalogTestCase):
    def test_upcoming_showtimes_are_chronological(self) -> None:
        movie_id = self.movie_id()
        # Inserted last, but earliest upcoming: must still sort first.
        self.execute("INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                     "VALUES (?, '2030-01-02', '12:30', 'Cinema 9')", (movie_id,))
        starts = [s.starts_at for s in self.upcoming(movie_id)]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(starts[0], dt.datetime(2030, 1, 2, 12, 30))

    def test_past_showtimes_are_excluded(self) -> None:
        showtimes = self.upcoming()
        self.assertTrue(all(s.starts_at > START_CLOCK for s in showtimes))
        # The Jan 2 10:30 screening has passed; 17:00 the same day has not.
        self.assertNotIn(dt.datetime(2030, 1, 2, 10, 30), [s.starts_at for s in showtimes])
        self.assertIn(dt.datetime(2030, 1, 2, 17, 0), [s.starts_at for s in showtimes])

    def test_inactive_showtimes_are_excluded(self) -> None:
        first = self.upcoming()[0]
        self.execute("UPDATE showtimes SET is_active = 0 WHERE id = ?", (first.id,))
        self.assertNotIn(first.id, [s.id for s in self.upcoming()])

    def test_no_upcoming_showtimes_after_schedule_ends(self) -> None:
        self.clock.moment = dt.datetime(2030, 2, 1)
        self.assertEqual(self.upcoming(), [])

    def test_past_inactive_and_missing_showtimes_cannot_be_selected(self) -> None:
        past_id = self.conn.execute(
            "SELECT id FROM showtimes WHERE movie_id = ? AND show_date = '2030-01-02' "
            "AND show_time = '10:30'", (self.movie_id(),)).fetchone()[0]
        upcoming = self.upcoming()
        inactive_id = upcoming[0].id
        self.execute("UPDATE showtimes SET is_active = 0 WHERE id = ?", (inactive_id,))
        inactive_movie_showtime = upcoming[1].id
        for showtime_id in (past_id, inactive_id, 9999):
            with self.subTest(showtime_id=showtime_id):
                with self.assertRaises(ShowtimeUnavailableError):
                    self.catalog.get_bookable_showtime(showtime_id)

        self.execute("UPDATE movies SET is_active = 0 WHERE id = ?", (self.movie_id(),))
        with self.assertRaises(ShowtimeUnavailableError):
            self.catalog.get_bookable_showtime(inactive_movie_showtime)

    def test_showtime_becomes_unselectable_once_started(self) -> None:
        showtime = self.upcoming()[0]
        movie, loaded = self.catalog.get_bookable_showtime(showtime.id)
        self.assertEqual(loaded, showtime)
        self.clock.moment = showtime.starts_at
        with self.assertRaises(ShowtimeUnavailableError):
            self.catalog.get_bookable_showtime(showtime.id)


class SeatAvailabilityTests(CatalogTestCase):
    def test_layout_has_eight_rows_of_ten(self) -> None:
        self.assertEqual(len(ALL_SEATS), 80)
        self.assertEqual(ALL_SEATS[0].label, "A1")
        self.assertEqual(ALL_SEATS[-1].label, "H10")
        self.assertEqual(Seat.parse(" b7 "), Seat("B", 7))
        for bad in ("I1", "A0", "A11", "1A", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Seat.parse(bad)

    def test_booked_seats_identified_for_showtime(self) -> None:
        showtime = self.upcoming()[0]
        self.book(showtime.id, ["A1", "C5"])
        self.assertEqual(self.seating.get_booked_seats(showtime.id),
                         frozenset({Seat("A", 1), Seat("C", 5)}))

    def test_seat_booked_for_one_showtime_is_free_for_another(self) -> None:
        first, second = self.upcoming()[:2]
        self.book(first.id, ["D4"])
        self.assertIn(Seat("D", 4), self.seating.get_booked_seats(first.id))
        self.assertNotIn(Seat("D", 4), self.seating.get_booked_seats(second.id))
        selection = self.new_selection(second.id)
        selection.toggle(Seat("D", 4), self.seating.get_booked_seats(second.id))
        self.assertEqual(selection.labels, ["D4"])

    def test_canceled_or_released_seats_do_not_block(self) -> None:
        showtime = self.upcoming()[0]
        self.book(showtime.id, ["E1"], status="canceled", released=1)
        self.book(showtime.id, ["E2"], status="canceled", released=0)  # status alone suffices
        self.book(showtime.id, ["E3"], status="confirmed", released=1)
        self.book(showtime.id, ["E4"])
        self.assertEqual(self.seating.get_booked_seats(showtime.id), frozenset({Seat("E", 4)}))

    def test_booked_seat_cannot_be_selected(self) -> None:
        showtime = self.upcoming()[0]
        self.book(showtime.id, ["B2"])
        movie, loaded, booked = self.seating.open_showtime(showtime.id)
        selection = SeatSelection(movie, loaded)
        with self.assertRaises(SeatSelectionError):
            selection.toggle(Seat("B", 2), booked)
        self.assertEqual(selection.count, 0)


class SelectionPricingTests(CatalogTestCase):
    def test_multiple_seats_total(self) -> None:
        selection = self.new_selection()
        for label in ("A1", "A2", "A3"):
            selection.toggle(Seat.parse(label), frozenset())
        self.assertEqual(selection.count, 3)
        self.assertEqual(selection.price_per_ticket, 35000)
        self.assertEqual(selection.total, 105000)
        self.assertIsInstance(selection.total, int)

    def test_deselecting_updates_total(self) -> None:
        selection = self.new_selection()
        for label in ("A1", "A2", "A3"):
            selection.toggle(Seat.parse(label), frozenset())
        self.assertFalse(selection.toggle(Seat("A", 2), frozenset()))
        self.assertEqual(selection.labels, ["A1", "A3"])
        self.assertEqual(selection.total, 70000)

    def test_clear_resets_total(self) -> None:
        selection = self.new_selection()
        selection.toggle(Seat("H", 10), frozenset())
        selection.clear()
        self.assertEqual((selection.count, selection.total, selection.labels), (0, 0, []))

    def test_labels_are_sorted_consistently(self) -> None:
        selection = self.new_selection()
        for label in ("C10", "A2", "C2", "A10"):
            selection.toggle(Seat.parse(label), frozenset())
        self.assertEqual(selection.labels, ["A2", "A10", "C2", "C10"])

    def test_selection_rejects_mismatched_movie(self) -> None:
        movie, _ = self.catalog.get_bookable_showtime(self.upcoming()[0].id)
        other = self.upcoming(self.movie_id("Orbitfall"))[0]
        with self.assertRaises(ValueError):
            SeatSelection(movie, other)


class CheckoutPreparationTests(CatalogTestCase):
    def test_cannot_continue_without_seats(self) -> None:
        with self.assertRaises(EmptySelectionError):
            self.seating.prepare_checkout(self.new_selection())

    def test_successful_checkout_preparation(self) -> None:
        selection = self.new_selection()
        selection.toggle(Seat("F", 6), frozenset())
        selection.toggle(Seat("F", 7), frozenset())
        checkout = self.seating.prepare_checkout(selection)
        self.assertEqual([s.label for s in checkout.seats], ["F6", "F7"])
        self.assertEqual((checkout.price_per_ticket, checkout.total), (35000, 70000))
        self.assertEqual(checkout.showtime.id, selection.showtime.id)

    def test_availability_is_rechecked_before_continuing(self) -> None:
        selection = self.new_selection()
        booked_at_load = self.seating.get_booked_seats(selection.showtime.id)
        selection.toggle(Seat("A", 1), booked_at_load)
        selection.toggle(Seat("A", 2), booked_at_load)

        self.book(selection.showtime.id, ["A1"])  # someone else books A1 meanwhile

        with self.assertRaises(SeatsUnavailableError) as ctx:
            self.seating.prepare_checkout(selection)
        self.assertEqual(ctx.exception.conflicts, frozenset({Seat("A", 1)}))
        self.assertIn(Seat("A", 1), ctx.exception.booked)
        self.assertIn("A1", str(ctx.exception))
        self.assertEqual(selection.labels, ["A2"])
        self.assertEqual(selection.total, 35000)

    def test_price_comes_from_database_at_checkout(self) -> None:
        selection = self.new_selection()
        selection.toggle(Seat("A", 1), frozenset())
        selection.toggle(Seat("A", 2), frozenset())
        self.execute("UPDATE movies SET ticket_price = 40000 WHERE id = ?", (selection.movie.id,))
        checkout = self.seating.prepare_checkout(selection)
        self.assertEqual((checkout.price_per_ticket, checkout.total), (40000, 80000))

    def test_checkout_rejected_once_showtime_has_started(self) -> None:
        selection = self.new_selection()
        selection.toggle(Seat("A", 1), frozenset())
        self.clock.moment = selection.showtime.starts_at + dt.timedelta(minutes=1)
        with self.assertRaises(ShowtimeUnavailableError):
            self.seating.prepare_checkout(selection)

    def test_services_never_create_bookings(self) -> None:
        before = (self.count("bookings"), self.count("booked_seats"))
        self.catalog.list_active_movies()
        for showtime in self.upcoming():
            self.seating.open_showtime(showtime.id)
        selection = self.new_selection()
        for seat in ALL_SEATS[:5]:
            selection.toggle(seat, frozenset())
        selection.toggle(ALL_SEATS[0], frozenset())
        self.seating.prepare_checkout(selection)
        selection.clear()
        with self.assertRaises(EmptySelectionError):
            self.seating.prepare_checkout(selection)
        self.assertEqual((self.count("bookings"), self.count("booked_seats")), before)
        self.assertEqual(before, (0, 0))


class SessionBookingStateTests(CatalogTestCase):
    def test_logout_and_login_clear_selection_state(self) -> None:
        session = Session()
        user = User(id=1, full_name="Juan", username="juan", created_at="2030-01-01 00:00:00")
        session.login(user)
        selection = self.new_selection()
        selection.toggle(Seat("A", 1), frozenset())
        session.seat_selection = selection
        session.pending_checkout = self.seating.prepare_checkout(selection)

        session.logout()
        self.assertIsNone(session.seat_selection)
        self.assertIsNone(session.pending_checkout)

        session.seat_selection = selection
        session.login(user)
        self.assertIsNone(session.seat_selection)


class DisplayFormattingTests(unittest.TestCase):
    def test_duration_date_and_time_formats(self) -> None:
        self.assertEqual(format_duration(118), "1h 58m")
        self.assertEqual(format_duration(120), "2h")
        self.assertEqual(format_duration(45), "45m")
        self.assertEqual(format_show_date(dt.date(2030, 1, 5)), "Sat, Jan 5, 2030")
        self.assertEqual(format_show_time(dt.time(0, 5)), "12:05 AM")
        self.assertEqual(format_show_time(dt.time(12, 0)), "12:00 PM")
        self.assertEqual(format_show_time(dt.time(20, 15)), "8:15 PM")


if __name__ == "__main__":
    unittest.main()
