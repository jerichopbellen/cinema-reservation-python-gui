"""Tests for administrator showtime management. Temporary databases only; no windows."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from database.connection import DEFAULT_DB_PATH, connect
from services import auth_service
from services.auth_service import AuthorizationError, AuthService
from services.booking_service import BookingService
from services.catalog_service import CatalogService, ShowtimeUnavailableError
from services.movie_admin_service import MovieAdminService
from services.showtime_admin_service import (
    CLEANING_MINUTES,
    ShowtimeAdminError,
    ShowtimeAdminService,
    ShowtimeNotFoundError,
    ShowtimeValidationError,
)
from tests.helpers import START_CLOCK, FakeClock, create_seeded_database

PASSWORD = "popcorn123"
FREE_DAY = "2030-01-10"  # the seeded schedule only covers Jan 2–4, 2030


class ShowtimeAdminTestCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(auth_service, "PBKDF2_ITERATIONS", 1_000)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "showtimes.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        create_seeded_database(self.db_path)

        self.clock = FakeClock(START_CLOCK)
        self.auth = AuthService(self.db_path)
        self.catalog = CatalogService(self.db_path, now=self.clock)
        self.bookings = BookingService(self.db_path, self.catalog)
        self.movies = MovieAdminService(self.db_path, self.auth)
        self.showtimes = ShowtimeAdminService(self.db_path, self.auth, now=self.clock)
        self.admin = self.auth.create_admin("Ada Admin", "ada", PASSWORD, PASSWORD)
        self.customer = self.auth.register("Carlo Customer", "carlo", PASSWORD, PASSWORD)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

    def movie_id(self, title: str = "The Last Lighthouse Keeper") -> int:  # 118 minutes
        return self.conn.execute("SELECT id FROM movies WHERE title = ?", (title,)).fetchone()[0]

    def add(self, time: str, auditorium: str = "Cinema 1", date: str = FREE_DAY, title: str = "The Last Lighthouse Keeper"):
        return self.showtimes.add_showtime(self.admin.id, self.movie_id(title), date, time, auditorium)


class AddShowtimeTests(ShowtimeAdminTestCase):
    def test_added_showtime_is_listed_and_bookable_by_customers(self) -> None:
        showtime = self.add("19:30")
        self.assertEqual((showtime.starts_at, showtime.auditorium, showtime.is_active),
                         (dt.datetime(2030, 1, 10, 19, 30), "Cinema 1", True))
        self.assertEqual(showtime.ends_at, dt.datetime(2030, 1, 10, 21, 28))  # 118-minute film
        self.assertIn(showtime.id, [s.id for s in self.showtimes.list_showtimes(self.admin.id, self.movie_id())])
        self.assertIn(showtime.id, [s.id for s in self.catalog.list_upcoming_showtimes(self.movie_id())])
        booking = self.bookings.create_booking(self.customer.id, showtime.id, ["A1"])
        self.assertEqual(booking.status, "confirmed")

    def test_short_times_are_normalized(self) -> None:
        showtime = self.add("9:05")
        stored = self.conn.execute("SELECT show_time FROM showtimes WHERE id = ?", (showtime.id,)).fetchone()[0]
        self.assertEqual(stored, "09:05")

    def test_invalid_input_is_rejected(self) -> None:
        cases = {
            "blank date": ({"date": ""}, "show_date"),
            "slashes": ({"date": "2030/01/10"}, "show_date"),
            "day first": ({"date": "10-01-2030"}, "show_date"),
            "impossible date": ({"date": "2030-02-30"}, "show_date"),
            "blank time": ({"time": ""}, "show_time"),
            "hour 25": ({"time": "25:00"}, "show_time"),
            "minute 60": ({"time": "12:60"}, "show_time"),
            "12-hour text": ({"time": "7pm"}, "show_time"),
            "unknown cinema": ({"auditorium": "Cinema 9"}, "auditorium"),
            "blank cinema": ({"auditorium": ""}, "auditorium"),
            "in the past": ({"date": "2030-01-02", "time": "11:00"}, "show_time"),
            "right now": ({"date": "2030-01-02", "time": "12:00"}, "show_time"),
        }
        before = self.conn.execute("SELECT COUNT(*) FROM showtimes").fetchone()[0]
        for label, (overrides, field) in cases.items():
            values = {"time": "19:30", "auditorium": "Cinema 1", "date": FREE_DAY, **overrides}
            with self.subTest(label):
                with self.assertRaises(ShowtimeValidationError) as ctx:
                    self.add(values["time"], values["auditorium"], values["date"])
                self.assertEqual(ctx.exception.field, field)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM showtimes").fetchone()[0], before)

    def test_archived_or_missing_movies_cannot_get_showtimes(self) -> None:
        self.movies.remove_movie(self.admin.id, self.movie_id())  # has showtimes, so it is archived
        with self.assertRaises(ShowtimeAdminError):
            self.add("19:30")
        with self.assertRaises(ShowtimeAdminError):
            self.showtimes.add_showtime(self.admin.id, 9999, FREE_DAY, "19:30", "Cinema 1")


class OverlapTests(ShowtimeAdminTestCase):
    def test_same_cinema_overlap_is_rejected_including_cleaning(self) -> None:
        self.add("18:00")  # occupies Cinema 1 until 19:58 + 15 min cleaning = 20:13
        for time in ("18:00", "19:00", "20:12", "16:30"):  # 16:30 + 118 min runs into 18:00
            with self.subTest(time=time), self.assertRaises(ShowtimeValidationError) as ctx:
                self.add(time)
            self.assertIn("busy", str(ctx.exception))
        self.assertEqual(self.add("20:13").starts_at.time(), dt.time(20, 13))  # exactly after cleaning

    def test_cleaning_gap_constant_is_respected_before_an_existing_show(self) -> None:
        self.add("18:00")
        latest_start = dt.datetime(2030, 1, 10, 18, 0) - dt.timedelta(minutes=118 + CLEANING_MINUTES)
        self.add(latest_start.strftime("%H:%M"))  # 15:47 ends 17:45, cleaned by 18:00

    def test_other_cinemas_are_independent(self) -> None:
        self.add("18:00", "Cinema 1")
        self.assertEqual(self.add("18:00", "Cinema 2").auditorium, "Cinema 2")

    def test_overlap_across_midnight_is_rejected(self) -> None:
        self.add("23:30", title="Orbitfall")  # 141 minutes: runs past 01:51 on Jan 11
        with self.assertRaises(ShowtimeValidationError):
            self.add("01:00", date="2030-01-11")
        self.add("03:00", date="2030-01-11")

    def test_overlap_check_uses_seeded_shows_of_other_movies(self) -> None:
        # Seeded: Orbitfall in Cinema 1 on Jan 3 at 13:45 (141 minutes).
        with self.assertRaises(ShowtimeValidationError) as ctx:
            self.add("14:00", date="2030-01-03")
        self.assertIn("Orbitfall", str(ctx.exception))


class RemovalTests(ShowtimeAdminTestCase):
    def test_showtime_without_bookings_is_deleted(self) -> None:
        showtime = self.add("19:30")
        self.assertEqual(self.showtimes.remove_showtime(self.admin.id, showtime.id), "deleted")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM showtimes WHERE id = ?", (showtime.id,)).fetchone())

    def test_upcoming_showtime_with_confirmed_bookings_is_locked(self) -> None:
        showtime = self.add("19:30")
        booking = self.bookings.create_booking(self.customer.id, showtime.id, ["B1", "B2"])
        self.assertTrue(self.showtimes.list_showtimes(self.admin.id, self.movie_id())[-1].is_locked(self.clock()))
        with self.assertRaises(ShowtimeAdminError) as ctx:
            self.showtimes.remove_showtime(self.admin.id, showtime.id)
        self.assertIn("1 confirmed booking", str(ctx.exception))
        row = self.conn.execute("SELECT is_active FROM showtimes WHERE id = ?", (showtime.id,)).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(self.bookings.get_booking(self.customer.id, booking.id).status, "confirmed")

    def test_after_customers_cancel_it_is_deactivated_not_deleted(self) -> None:
        showtime = self.add("19:30")
        booking = self.bookings.create_booking(self.customer.id, showtime.id, ["B1"])
        self.bookings.cancel_booking(self.customer.id, booking.id)
        self.assertEqual(self.showtimes.remove_showtime(self.admin.id, showtime.id), "deactivated")
        self.assertEqual(self.bookings.get_booking(self.customer.id, booking.id).status, "canceled")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM booked_seats WHERE booking_id = ?",
                                           (booking.id,)).fetchone()[0], 1)

    def test_past_showtime_with_bookings_is_deactivated(self) -> None:
        showtime = self.catalog.list_upcoming_showtimes(self.movie_id())[0]
        booking = self.bookings.create_booking(self.customer.id, showtime.id, ["A1"])
        self.clock.moment = showtime.starts_at + dt.timedelta(hours=3)  # the screening is over
        self.assertEqual(self.showtimes.remove_showtime(self.admin.id, showtime.id), "deactivated")
        self.assertEqual(self.bookings.get_booking(self.customer.id, booking.id).status, "confirmed")

    def test_deactivated_showtimes_are_hidden_and_unbookable(self) -> None:
        showtime = self.add("19:30")
        self.bookings.cancel_booking(self.customer.id,
                                     self.bookings.create_booking(self.customer.id, showtime.id, ["A1"]).id)
        self.showtimes.remove_showtime(self.admin.id, showtime.id)
        self.assertNotIn(showtime.id, [s.id for s in self.catalog.list_upcoming_showtimes(self.movie_id())])
        with self.assertRaises(ShowtimeUnavailableError):
            self.bookings.create_booking(self.customer.id, showtime.id, ["A2"])

    def test_missing_showtime(self) -> None:
        with self.assertRaises(ShowtimeNotFoundError):
            self.showtimes.remove_showtime(self.admin.id, 9999)
        with self.assertRaises(ShowtimeNotFoundError):
            self.showtimes.restore_showtime(self.admin.id, 9999)


class RestoreTests(ShowtimeAdminTestCase):
    def deactivated(self, time: str = "19:30"):
        showtime = self.add(time)
        self.bookings.cancel_booking(self.customer.id,
                                     self.bookings.create_booking(self.customer.id, showtime.id, ["A1"]).id)
        self.showtimes.remove_showtime(self.admin.id, showtime.id)
        return showtime

    def test_restore_makes_it_bookable_again(self) -> None:
        showtime = self.deactivated()
        self.assertTrue(self.showtimes.restore_showtime(self.admin.id, showtime.id).is_active)
        self.assertEqual(self.bookings.create_booking(self.customer.id, showtime.id, ["A1"]).status, "confirmed")

    def test_inactive_showtimes_do_not_block_new_ones_but_restore_rechecks(self) -> None:
        old = self.deactivated("19:30")
        replacement = self.add("19:45")  # overlaps the inactive show, which is allowed
        with self.assertRaises(ShowtimeValidationError):
            self.showtimes.restore_showtime(self.admin.id, old.id)
        self.showtimes.remove_showtime(self.admin.id, replacement.id)  # no bookings: deleted
        self.assertTrue(self.showtimes.restore_showtime(self.admin.id, old.id).is_active)

    def test_exact_slot_of_an_inactive_showtime_explains_itself(self) -> None:
        self.deactivated("19:30")
        with self.assertRaises(ShowtimeValidationError) as ctx:
            self.add("19:30")
        self.assertIn("deactivated showtime", str(ctx.exception))

    def test_cannot_restore_active_past_or_archived(self) -> None:
        active = self.add("08:00")
        with self.assertRaises(ShowtimeAdminError):
            self.showtimes.restore_showtime(self.admin.id, active.id)
        showtime = self.deactivated()
        self.clock.moment = dt.datetime(2030, 1, 11)
        with self.assertRaises(ShowtimeAdminError):
            self.showtimes.restore_showtime(self.admin.id, showtime.id)
        self.clock.moment = START_CLOCK
        self.movies.remove_movie(self.admin.id, self.movie_id())
        with self.assertRaises(ShowtimeAdminError):
            self.showtimes.restore_showtime(self.admin.id, showtime.id)


class ConfirmedBookingListTests(ShowtimeAdminTestCase):
    def test_lists_confirmed_bookings_with_customers_seats_and_totals(self) -> None:
        showtime = self.add("19:30")
        other = self.auth.register("Bea Santos", "bea", PASSWORD, PASSWORD)
        first = self.bookings.create_booking(self.customer.id, showtime.id, ["C5", "A2", "A10"])
        second = self.bookings.create_booking(other.id, showtime.id, ["H1"])
        canceled = self.bookings.create_booking(other.id, showtime.id, ["D4"])
        self.bookings.cancel_booking(other.id, canceled.id)
        # A booking for a different showtime must not appear.
        elsewhere = self.add("08:00", "Cinema 2")
        self.bookings.create_booking(self.customer.id, elsewhere.id, ["B2"])

        report = self.showtimes.list_confirmed_bookings(self.admin.id, showtime.id)
        self.assertEqual(report.movie_title, "The Last Lighthouse Keeper")
        self.assertEqual([b.reference for b in report.bookings], [first.reference, second.reference])
        self.assertEqual([(b.customer_name, b.username) for b in report.bookings],
                         [("Carlo Customer", "carlo"), ("Bea Santos", "bea")])
        self.assertEqual(report.bookings[0].seat_labels, ("A2", "A10", "C5"))  # seat order, not string order
        self.assertEqual(report.bookings[0].ticket_count, 3)
        self.assertEqual(report.canceled_count, 1)
        self.assertEqual((report.seats_sold, report.capacity), (4, 80))
        self.assertEqual(report.revenue, first.total_amount + second.total_amount)

    def test_empty_showtime(self) -> None:
        report = self.showtimes.list_confirmed_bookings(self.admin.id, self.add("19:30").id)
        self.assertEqual((report.bookings, report.seats_sold, report.revenue, report.canceled_count),
                         ((), 0, 0, 0))

    def test_archived_movies_bookings_remain_viewable(self) -> None:
        showtime = self.catalog.list_upcoming_showtimes(self.movie_id())[0]
        booking = self.bookings.create_booking(self.customer.id, showtime.id, ["E5"])
        self.movies.remove_movie(self.admin.id, self.movie_id())  # archived (it has history)
        report = self.showtimes.list_confirmed_bookings(self.admin.id, showtime.id)
        self.assertEqual([b.reference for b in report.bookings], [booking.reference])

    def test_customers_and_missing_showtimes_are_refused(self) -> None:
        showtime = self.add("19:30")
        with self.assertRaises(AuthorizationError):
            self.showtimes.list_confirmed_bookings(self.customer.id, showtime.id)
        with self.assertRaises(ShowtimeNotFoundError):
            self.showtimes.list_confirmed_bookings(self.admin.id, 9999)


class AuthorizationTests(ShowtimeAdminTestCase):
    def test_customers_cannot_manage_showtimes(self) -> None:
        showtime = self.add("19:30")
        operations = {
            "list": lambda: self.showtimes.list_showtimes(self.customer.id, self.movie_id()),
            "add": lambda: self.showtimes.add_showtime(self.customer.id, self.movie_id(), FREE_DAY, "08:00", "Cinema 2"),
            "remove": lambda: self.showtimes.remove_showtime(self.customer.id, showtime.id),
            "restore": lambda: self.showtimes.restore_showtime(self.customer.id, showtime.id),
        }
        before = [tuple(r) for r in self.conn.execute("SELECT * FROM showtimes ORDER BY id")]
        for name, operation in operations.items():
            with self.subTest(name), self.assertRaises(AuthorizationError):
                operation()
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT * FROM showtimes ORDER BY id")], before)


if __name__ == "__main__":
    unittest.main()
