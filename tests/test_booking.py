"""Stage 4 tests: transactional booking, references, history, cancellation, receipts.

Each test uses its own temporary SQLite database seeded around a fixed date,
with a controllable clock. The real application database and the real
receipts folder are never written. No Tkinter windows are created.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from database.connection import DEFAULT_DB_PATH, PROJECT_ROOT, connect, get_connection
from services import booking_service
from services.booking_service import (
    DISPLAY_CANCELED,
    DISPLAY_COMPLETED,
    DISPLAY_UPCOMING,
    BookingBusyError,
    BookingError,
    BookingNotFoundError,
    BookingService,
    CancellationError,
    SeatConflictError,
)
from services.catalog_service import CatalogService, ShowtimeUnavailableError
from services.receipt_service import (
    RECEIPT_WIDTH,
    RECEIPTS_DIR,
    receipt_filename,
    render_receipt,
    save_receipt,
)
from services.seating_service import Seat, SeatingService
from tests.helpers import START_CLOCK, FakeClock, create_seeded_database
from utils.formatting import format_local_datetime, format_show_date, format_show_time

REFERENCE_PATTERN = re.compile(r"CR-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{10}")


class BookingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)
        self.db_path = self.tmp_dir / "booking.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        create_seeded_database(self.db_path)

        self.clock = FakeClock(START_CLOCK)
        self.catalog = CatalogService(self.db_path, now=self.clock)
        self.seating = SeatingService(self.db_path, self.catalog)
        self.bookings = BookingService(self.db_path, self.catalog)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

        self.alice = self.add_user("alice", "Alice Reyes")
        self.bob = self.add_user("bob", "Bob Santos")
        movie_id = self.conn.execute(
            "SELECT id FROM movies WHERE title = 'The Last Lighthouse Keeper'").fetchone()[0]
        self.showtimes = self.catalog.list_upcoming_showtimes(movie_id)
        self.show = self.showtimes[0]
        self.other_show = self.showtimes[1]

    # --- helpers --------------------------------------------------------------

    def add_user(self, username: str, full_name: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO users (full_name, username, password_hash, password_salt) "
            "VALUES (?, ?, 'h', 's')", (full_name, username))
        self.conn.commit()
        return cursor.lastrowid

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def counts(self) -> tuple[int, int]:
        return self.count("bookings"), self.count("booked_seats")

    def seat_rows(self, booking_id: int) -> list[tuple[str, int, int]]:
        return [tuple(row) for row in self.conn.execute(
            "SELECT seat_row, seat_number, is_released FROM booked_seats WHERE booking_id = ? "
            "ORDER BY seat_row, seat_number", (booking_id,))]

    def status(self, booking_id: int) -> str:
        return self.conn.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()[0]


class CreateBookingTests(BookingTestCase):
    def test_valid_booking_persists_after_commit(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C4"])
        with get_connection(self.db_path) as fresh:  # a separate connection sees committed data
            row = fresh.execute("SELECT * FROM bookings WHERE id = ?", (booking.id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual((row["user_id"], row["showtime_id"], row["status"]),
                         (self.alice, self.show.id, "confirmed"))
        self.assertEqual(booking.customer_name, "Alice Reyes")
        self.assertEqual(booking.movie_title, "The Last Lighthouse Keeper")
        self.assertEqual(booking.starts_at, self.show.starts_at)
        self.assertEqual(booking.auditorium, self.show.auditorium)

    def test_multiple_seats_saved(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B3", "A1", Seat("A", 2)])
        self.assertEqual(booking.seat_labels, ("A1", "A2", "B3"))
        self.assertEqual(self.seat_rows(booking.id), [("A", 1, 0), ("A", 2, 0), ("B", 3, 0)])
        self.assertEqual(self.seating.get_booked_seats(self.show.id),
                         frozenset({Seat("A", 1), Seat("A", 2), Seat("B", 3)}))

    def test_total_uses_authoritative_database_price(self) -> None:
        self.conn.execute("UPDATE movies SET ticket_price = 41250 WHERE id = ?", (self.show.movie_id,))
        self.conn.commit()
        booking = self.bookings.create_booking(self.alice, self.show.id, ["A1", "A2", "A3"])
        stored = self.conn.execute("SELECT total_amount FROM bookings WHERE id = ?",
                                   (booking.id,)).fetchone()[0]
        self.assertEqual(stored, 123750)
        self.assertEqual((booking.total_amount, booking.price_per_ticket, booking.ticket_count),
                         (123750, 41250, 3))

    def test_duplicate_seats_in_one_selection_rejected(self) -> None:
        for seats in (["A1", "A1"], ["A1", " a1 "], [Seat("B", 2), "B2"]):
            with self.subTest(seats=seats), self.assertRaises(BookingError):
                self.bookings.create_booking(self.alice, self.show.id, seats)
        self.assertEqual(self.counts(), (0, 0))

    def test_invalid_seats_and_empty_selection_rejected(self) -> None:
        for seats in (["I1"], ["A0"], ["A11"], ["seat"], []):
            with self.subTest(seats=seats), self.assertRaises(BookingError):
                self.bookings.create_booking(self.alice, self.show.id, seats)
        self.assertEqual(self.counts(), (0, 0))

    def test_already_booked_seat_rejected(self) -> None:
        self.bookings.create_booking(self.alice, self.show.id, ["D5"])
        before = self.counts()
        with self.assertRaises(SeatConflictError) as ctx:
            self.bookings.create_booking(self.bob, self.show.id, ["D4", "D5"])
        self.assertEqual(ctx.exception.seats, frozenset({Seat("D", 5)}))
        self.assertIn("D5", str(ctx.exception))
        self.assertEqual(self.counts(), before)

    def test_same_seat_allowed_for_different_showtime(self) -> None:
        first = self.bookings.create_booking(self.alice, self.show.id, ["E5"])
        second = self.bookings.create_booking(self.bob, self.other_show.id, ["E5"])
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(self.count("booked_seats"), 2)

    def test_failed_multi_seat_booking_rolls_back_completely(self) -> None:
        self.bookings.create_booking(self.alice, self.show.id, ["A1"])
        before = self.counts()
        # Skip the in-transaction pre-check so the unique index itself must stop the insert
        # after A2 has already been written in the same transaction.
        with mock.patch.object(booking_service, "fetch_booked_seats", return_value=frozenset()):
            with self.assertRaises(SeatConflictError):
                self.bookings.create_booking(self.bob, self.show.id, ["A2", "A1"])
        self.assertEqual(self.counts(), before)
        self.assertNotIn(Seat("A", 2), self.seating.get_booked_seats(self.show.id))

    def test_failed_attempts_leave_no_orphaned_seat_records(self) -> None:
        self.bookings.create_booking(self.alice, self.show.id, ["F1"])
        attempts = (
            lambda: self.bookings.create_booking(self.bob, self.show.id, ["F2", "F1"]),
            lambda: self.bookings.create_booking(self.bob, 9999, ["F3"]),
            lambda: self.bookings.create_booking(9999, self.show.id, ["F4"]),
        )
        for attempt in attempts:
            with self.assertRaises(Exception):
                attempt()
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM booked_seats bs LEFT JOIN bookings b ON b.id = bs.booking_id "
            "WHERE b.id IS NULL").fetchone()[0]
        self.assertEqual(orphans, 0)
        self.assertEqual(self.counts(), (1, 1))

    def test_invalid_or_inactive_showtimes_cannot_be_booked(self) -> None:
        past_id = self.conn.execute(
            "SELECT id FROM showtimes WHERE movie_id = ? AND show_date = '2030-01-02' "
            "AND show_time = '10:30'", (self.show.movie_id,)).fetchone()[0]
        self.conn.execute("UPDATE showtimes SET is_active = 0 WHERE id = ?", (self.other_show.id,))
        self.conn.commit()
        for showtime_id in (9999, past_id, self.other_show.id):
            with self.subTest(showtime_id=showtime_id), self.assertRaises(ShowtimeUnavailableError):
                self.bookings.create_booking(self.alice, showtime_id, ["A1"])

        self.conn.execute("UPDATE movies SET is_active = 0 WHERE id = ?", (self.show.movie_id,))
        self.conn.commit()
        with self.assertRaises(ShowtimeUnavailableError):
            self.bookings.create_booking(self.alice, self.show.id, ["A1"])
        self.assertEqual(self.counts(), (0, 0))

    def test_unknown_user_cannot_book(self) -> None:
        with self.assertRaises(BookingError):
            self.bookings.create_booking(9999, self.show.id, ["A1"])
        self.assertEqual(self.counts(), (0, 0))


class BookingReferenceTests(BookingTestCase):
    def test_references_are_unique_random_and_persisted(self) -> None:
        bookings = [self.bookings.create_booking(self.alice, self.show.id, [f"G{n}"]) for n in range(1, 6)]
        references = [b.reference for b in bookings]
        self.assertEqual(len(set(references)), 5)
        for booking in bookings:
            self.assertRegex(booking.reference, REFERENCE_PATTERN)
            stored = self.conn.execute("SELECT booking_reference FROM bookings WHERE id = ?",
                                       (booking.id,)).fetchone()[0]
            self.assertEqual(stored, booking.reference)

    def test_reference_collision_is_retried(self) -> None:
        existing = self.bookings.create_booking(self.alice, self.show.id, ["A1"]).reference
        with mock.patch.object(booking_service, "generate_booking_reference",
                               side_effect=[existing, "CR-NEWREF2345"]),                 self.assertLogs(booking_service.logger, "WARNING"):
            booking = self.bookings.create_booking(self.bob, self.show.id, ["A2"])
        self.assertEqual(booking.reference, "CR-NEWREF2345")

    def test_persistent_collisions_fail_without_partial_rows(self) -> None:
        existing = self.bookings.create_booking(self.alice, self.show.id, ["A1"]).reference
        before = self.counts()
        with mock.patch.object(booking_service, "generate_booking_reference", return_value=existing),                 self.assertLogs(booking_service.logger, "WARNING"):
            with self.assertRaises(BookingError):
                self.bookings.create_booking(self.bob, self.show.id, ["A2"])
        self.assertEqual(self.counts(), before)


class ConcurrencyTests(BookingTestCase):
    def test_locked_database_reports_busy_and_commits_nothing(self) -> None:
        holder = connect(self.db_path)
        holder.isolation_level = None
        holder.execute("BEGIN IMMEDIATE")  # another process holds the write lock
        try:
            impatient = BookingService(self.db_path, self.catalog, lock_timeout=0.05)
            with self.assertRaises(BookingBusyError):
                impatient.create_booking(self.alice, self.show.id, ["H1"])
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(self.counts(), (0, 0))
        self.bookings.create_booking(self.alice, self.show.id, ["H1"])  # works once released

    def test_competing_bookings_for_same_seat_only_one_commits(self) -> None:
        users = [self.add_user(f"racer{n}", f"Racer {n}") for n in range(6)]
        barrier = threading.Barrier(len(users))
        outcomes: list[object] = []
        lock = threading.Lock()

        def attempt(user_id: int) -> None:
            service = BookingService(self.db_path, self.catalog)  # own connections per call
            barrier.wait()
            try:
                result: object = service.create_booking(user_id, self.show.id, ["E7", "E8"])
            except (SeatConflictError, BookingBusyError) as exc:
                result = exc
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=attempt, args=(user,)) for user in users]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successes = [o for o in outcomes if not isinstance(o, Exception)]
        self.assertEqual(len(outcomes), len(users))
        self.assertEqual(len(successes), 1)
        active = self.conn.execute(
            "SELECT COUNT(*) FROM booked_seats WHERE showtime_id = ? AND is_released = 0 "
            "AND seat_row = 'E' AND seat_number IN (7, 8)", (self.show.id,)).fetchone()[0]
        self.assertEqual(active, 2)
        self.assertEqual(self.count("bookings"), 1)

    def test_database_index_rejects_duplicate_from_separate_connection(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C1"])
        other = connect(self.db_path)
        try:
            other.execute("INSERT INTO bookings (booking_reference, user_id, showtime_id, total_amount) "
                          "VALUES ('CR-MANUAL2345', ?, ?, 0)", (self.bob, self.show.id))
            booking_id = other.execute("SELECT last_insert_rowid()").fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                other.execute("INSERT INTO booked_seats (booking_id, showtime_id, seat_row, seat_number) "
                              "VALUES (?, ?, 'C', 1)", (booking_id, self.show.id))
            other.rollback()
        finally:
            other.close()
        self.assertEqual(self.seat_rows(booking.id), [("C", 1, 0)])


class HistoryTests(BookingTestCase):
    def test_users_only_see_their_own_bookings(self) -> None:
        mine = self.bookings.create_booking(self.alice, self.show.id, ["A1"])
        theirs = self.bookings.create_booking(self.bob, self.show.id, ["A2"])
        self.assertEqual([b.id for b in self.bookings.list_bookings(self.alice)], [mine.id])
        self.assertEqual([b.id for b in self.bookings.list_bookings(self.bob)], [theirs.id])
        with self.assertRaises(BookingNotFoundError):
            self.bookings.get_booking(self.bob, mine.id)
        with self.assertRaises(BookingNotFoundError):
            self.bookings.get_booking(self.alice, 9999)

    def test_history_orders_upcoming_first_then_past_and_canceled(self) -> None:
        later = self.bookings.create_booking(self.alice, self.showtimes[3].id, ["A1"])
        sooner = self.bookings.create_booking(self.alice, self.showtimes[1].id, ["A1"])
        first = self.bookings.create_booking(self.alice, self.showtimes[0].id, ["A1"])
        canceled = self.bookings.create_booking(self.alice, self.showtimes[2].id, ["A1"])
        self.bookings.cancel_booking(self.alice, canceled.id)

        self.clock.moment = self.showtimes[0].starts_at + dt.timedelta(minutes=5)  # first has started
        history = self.bookings.list_bookings(self.alice)
        self.assertEqual([b.id for b in history], [sooner.id, later.id, canceled.id, first.id])
        now = self.clock()
        self.assertEqual([b.display_status(now) for b in history],
                         [DISPLAY_UPCOMING, DISPLAY_UPCOMING, DISPLAY_CANCELED, DISPLAY_COMPLETED])
        self.assertEqual(self.status(first.id), "confirmed")  # "completed" is derived, not stored

    def test_empty_history(self) -> None:
        self.assertEqual(self.bookings.list_bookings(self.alice), [])


class CancellationTests(BookingTestCase):
    def test_cancellation_preserves_history_and_releases_seats(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1", "B2"])
        canceled = self.bookings.cancel_booking(self.alice, booking.id)

        self.assertEqual(canceled.status, "canceled")
        self.assertEqual(canceled.reference, booking.reference)
        self.assertEqual(canceled.seat_labels, booking.seat_labels)
        self.assertEqual(canceled.total_amount, booking.total_amount)
        self.assertEqual(self.seat_rows(booking.id), [("B", 1, 1), ("B", 2, 1)])
        self.assertEqual([b.id for b in self.bookings.list_bookings(self.alice)], [booking.id])
        self.assertEqual(self.seating.get_booked_seats(self.show.id), frozenset())
        self.assertFalse(canceled.can_cancel(self.clock()))

    def test_canceled_seats_can_be_booked_again(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1"])
        self.bookings.cancel_booking(self.alice, booking.id)
        rebooked = self.bookings.create_booking(self.bob, self.show.id, ["B1"])
        self.assertEqual(rebooked.status, "confirmed")
        rows = self.conn.execute(
            "SELECT is_released FROM booked_seats WHERE showtime_id = ? AND seat_row = 'B' "
            "AND seat_number = 1 ORDER BY id", (self.show.id,)).fetchall()
        self.assertEqual([r[0] for r in rows], [1, 0])

    def test_cannot_cancel_twice(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1"])
        self.bookings.cancel_booking(self.alice, booking.id)
        with self.assertRaises(CancellationError):
            self.bookings.cancel_booking(self.alice, booking.id)

    def test_cannot_cancel_another_users_booking(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1"])
        with self.assertRaises(BookingNotFoundError):
            self.bookings.cancel_booking(self.bob, booking.id)
        self.assertEqual(self.status(booking.id), "confirmed")
        self.assertEqual(self.seat_rows(booking.id), [("B", 1, 0)])

    def test_cannot_cancel_after_showtime_started(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1"])
        self.clock.moment = self.show.starts_at
        with self.assertRaises(CancellationError):
            self.bookings.cancel_booking(self.alice, booking.id)
        self.assertEqual(self.status(booking.id), "confirmed")
        self.assertEqual(self.seat_rows(booking.id), [("B", 1, 0)])

    def test_cancellation_from_another_session_is_not_repeated(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["B1"])
        # Another app instance (separate service and connections) cancels first.
        other = BookingService(self.db_path, self.catalog)
        other.cancel_booking(self.alice, booking.id)
        with self.assertRaises(CancellationError):
            self.bookings.cancel_booking(self.alice, booking.id)
        self.assertEqual(self.seat_rows(booking.id), [("B", 1, 1)])


class ReceiptTests(BookingTestCase):
    def test_receipt_matches_saved_booking(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C2", "C3"])
        saved = self.bookings.get_booking(self.alice, booking.id)
        text = render_receipt(saved, generated_at=dt.datetime(2030, 1, 2, 12, 30))
        for expected in ("CINEROJO", saved.reference, "Alice Reyes", "The Last Lighthouse Keeper",
                         format_show_date(saved.starts_at.date()), format_show_time(saved.starts_at),
                         format_local_datetime(saved.created_at),
                         saved.auditorium, "C2, C3", "Tickets           2",
                         "₱350.00", "₱700.00", "CONFIRMED", "Booked on"):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_canceled_receipt_shows_canceled_status(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C2"])
        canceled = self.bookings.cancel_booking(self.alice, booking.id)
        text = render_receipt(canceled)
        self.assertIn("CANCELED", text)
        self.assertNotIn("CONFIRMED", text)

    def test_save_receipt_writes_file(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C2"])
        generated = dt.datetime(2030, 1, 2, 12, 30)
        target = self.tmp_dir / "copies" / receipt_filename(booking.reference)
        path = save_receipt(booking, target, generated_at=generated)
        self.assertEqual(path, target)
        self.assertEqual(path.read_text(encoding="utf-8"), render_receipt(booking, generated))

    def test_save_receipt_reports_write_errors(self) -> None:
        booking = self.bookings.create_booking(self.alice, self.show.id, ["C2"])
        with self.assertRaises(OSError):
            save_receipt(booking, self.tmp_dir)  # a directory, not a file

    def test_long_values_wrap_within_receipt_width(self) -> None:
        self.conn.execute("UPDATE movies SET title = ? WHERE id = ?",
                          ("The Extraordinarily Long Chronicles of the Last Lighthouse Keeper", self.show.movie_id))
        self.conn.execute("UPDATE users SET full_name = ? WHERE id = ?",
                          ("Maria Clara Gonzales de los Santos y Reyes", self.alice))
        self.conn.commit()
        seats = [f"{row}{n}" for row in "AB" for n in range(1, 11)]
        booking = self.bookings.create_booking(self.alice, self.show.id, seats)
        text = render_receipt(booking)
        self.assertTrue(all(len(line) <= RECEIPT_WIDTH for line in text.splitlines()))
        flattened = " ".join(line.strip() for line in text.splitlines())
        self.assertIn("Extraordinarily Long Chronicles of the Last Lighthouse Keeper", flattened)
        self.assertIn("Gonzales de los Santos y Reyes", flattened)
        self.assertIn("B9, B10", flattened)

    def test_receipt_filename_is_safe_and_directory_is_project_relative(self) -> None:
        self.assertEqual(receipt_filename("CR-ABCDE23456"), "receipt_CR-ABCDE23456.txt")
        self.assertEqual(receipt_filename("../../evil\\name"), "receipt_evilname.txt")
        self.assertEqual(RECEIPTS_DIR, PROJECT_ROOT / "receipts")


if __name__ == "__main__":
    unittest.main()
