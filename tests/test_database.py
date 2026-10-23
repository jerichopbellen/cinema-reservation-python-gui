"""Stage 1 database tests.

Every test runs against its own temporary SQLite file; the real application
database is never opened. No GUI is created, so the suite runs headlessly.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import initialize_database
from database.connection import DEFAULT_DB_PATH, PROJECT_ROOT, connect, get_connection, write_transaction
from database.schema import REQUIRED_TABLES
from database.seed import SAMPLE_MOVIES, build_sample_showtimes
from utils.formatting import format_local_date, format_peso, format_showtime, truncate


class DatabaseTestCase(unittest.TestCase):
    """Creates and initializes a fresh temporary database for each test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "nested" / "test.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        initialize_database(self.db_path)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def add_user(self, username: str = "juan", full_name: str = "Juan Dela Cruz") -> int:
        cursor = self.conn.execute(
            "INSERT INTO users (full_name, username, password_hash, password_salt) "
            "VALUES (?, ?, 'hash', 'salt')",
            (full_name, username),
        )
        return cursor.lastrowid

    def showtime_ids(self) -> list[int]:
        return [row[0] for row in self.conn.execute("SELECT id FROM showtimes ORDER BY id")]

    def add_booking(self, user_id: int, showtime_id: int, reference: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO bookings (booking_reference, user_id, showtime_id, total_amount) "
            "VALUES (?, ?, ?, 35000)",
            (reference, user_id, showtime_id),
        )
        return cursor.lastrowid

    def add_seat(self, booking_id: int, showtime_id: int, row: str = "A", number: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO booked_seats (booking_id, showtime_id, seat_row, seat_number) "
            "VALUES (?, ?, ?, ?)",
            (booking_id, showtime_id, row, number),
        )


class InitializationTests(DatabaseTestCase):
    def test_creates_database_directory_and_all_tables(self) -> None:
        self.assertTrue(self.db_path.exists())
        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for table in REQUIRED_TABLES:
            self.assertIn(table, tables)

    def test_initializing_twice_does_not_fail_or_duplicate_seed(self) -> None:
        movies, showtimes = self.count("movies"), self.count("showtimes")
        initialize_database(self.db_path)
        initialize_database(self.db_path)
        self.assertEqual(self.count("movies"), movies)
        self.assertEqual(self.count("showtimes"), showtimes)

    def test_reinitializing_preserves_user_changes(self) -> None:
        self.conn.execute("UPDATE movies SET ticket_price = 99900 WHERE id = 1")
        self.conn.execute("UPDATE movies SET is_active = 0 WHERE id = 2")
        self.conn.commit()

        initialize_database(self.db_path)

        rows = self.conn.execute(
            "SELECT id, ticket_price, is_active FROM movies WHERE id IN (1, 2) ORDER BY id"
        ).fetchall()
        self.assertEqual(rows[0]["ticket_price"], 99900)
        self.assertEqual(rows[1]["is_active"], 0)

    def test_sample_movies_and_future_showtimes_exist(self) -> None:
        self.assertGreaterEqual(self.count("movies"), 6)
        self.assertEqual(self.count("movies"), len(SAMPLE_MOVIES))
        self.assertGreater(self.count("showtimes"), 0)

        today = dt.date.today().isoformat()
        past = self.conn.execute(
            "SELECT COUNT(*) FROM showtimes WHERE show_date <= ?", (today,)
        ).fetchone()[0]
        self.assertEqual(past, 0)

        without_showtimes = self.conn.execute(
            "SELECT COUNT(*) FROM movies m "
            "WHERE NOT EXISTS (SELECT 1 FROM showtimes s WHERE s.movie_id = m.id)"
        ).fetchone()[0]
        self.assertEqual(without_showtimes, 0)

    def test_seed_prices_are_integer_centavos(self) -> None:
        types = {row[0] for row in self.conn.execute("SELECT typeof(ticket_price) FROM movies")}
        self.assertEqual(types, {"integer"})

    def test_sample_schedule_never_double_books_an_auditorium(self) -> None:
        schedule = build_sample_showtimes(len(SAMPLE_MOVIES), dt.date(2030, 1, 1))
        slots = [(show_date, time, room) for _, show_date, time, room in schedule]
        self.assertEqual(len(slots), len(set(slots)))


class ConnectionTests(DatabaseTestCase):
    def test_foreign_keys_enabled_on_every_connection(self) -> None:
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with get_connection(self.db_path) as other:
            self.assertEqual(other.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_foreign_key_violation_is_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                "VALUES (9999, '2030-01-01', '10:00', 'Cinema 1')"
            )

    def test_get_connection_rolls_back_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with get_connection(self.db_path) as conn:
                conn.execute("UPDATE movies SET ticket_price = 1 WHERE id = 1")
                raise RuntimeError("boom")
        price = self.conn.execute("SELECT ticket_price FROM movies WHERE id = 1").fetchone()[0]
        self.assertNotEqual(price, 1)

    def test_write_transaction_enforces_foreign_keys(self) -> None:
        with write_transaction(self.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            with write_transaction(self.db_path) as conn:
                conn.execute("INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                             "VALUES (9999, '2030-01-01', '10:00', 'Cinema 1')")

    def test_write_transaction_rolls_back_every_statement_on_error(self) -> None:
        before = self.count("showtimes")
        with self.assertRaises(RuntimeError):
            with write_transaction(self.db_path) as conn:
                conn.execute("INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                             "VALUES (1, '2030-01-01', '10:00', 'Cinema 8')")
                conn.execute("UPDATE movies SET ticket_price = 1 WHERE id = 1")
                raise RuntimeError("fail after two writes")
        self.assertEqual(self.count("showtimes"), before)
        self.assertNotEqual(self.conn.execute("SELECT ticket_price FROM movies WHERE id = 1").fetchone()[0], 1)

    def test_default_path_is_resolved_from_project_not_cwd(self) -> None:
        self.assertTrue(DEFAULT_DB_PATH.is_absolute())
        self.assertEqual(DEFAULT_DB_PATH.parent.parent, PROJECT_ROOT)
        self.assertTrue((PROJECT_ROOT / "main.py").exists())


class ConstraintTests(DatabaseTestCase):
    def test_duplicate_username_rejected(self) -> None:
        self.add_user("maria")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_user("maria", "Another Maria")

    def test_username_uniqueness_is_case_insensitive(self) -> None:
        self.add_user("maria")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_user("MARIA")

    def test_duplicate_seat_for_same_showtime_rejected(self) -> None:
        showtime = self.showtime_ids()[0]
        first = self.add_booking(self.add_user("a"), showtime, "REF-1")
        second = self.add_booking(self.add_user("b"), showtime, "REF-2")
        self.add_seat(first, showtime, "C", 5)
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_seat(second, showtime, "C", 5)

    def test_same_seat_allowed_for_different_showtimes(self) -> None:
        show_a, show_b = self.showtime_ids()[:2]
        user = self.add_user()
        self.add_seat(self.add_booking(user, show_a, "REF-1"), show_a, "C", 5)
        self.add_seat(self.add_booking(user, show_b, "REF-2"), show_b, "C", 5)
        self.assertEqual(self.count("booked_seats"), 2)

    def test_released_seat_can_be_booked_again_and_history_is_kept(self) -> None:
        showtime = self.showtime_ids()[0]
        user = self.add_user()
        old = self.add_booking(user, showtime, "REF-OLD")
        self.add_seat(old, showtime, "D", 7)
        self.conn.execute("UPDATE bookings SET status = 'canceled' WHERE id = ?", (old,))
        self.conn.execute("UPDATE booked_seats SET is_released = 1 WHERE booking_id = ?", (old,))

        self.add_seat(self.add_booking(user, showtime, "REF-NEW"), showtime, "D", 7)
        self.assertEqual(self.count("booked_seats"), 2)

    def test_seat_showtime_must_match_its_booking(self) -> None:
        show_a, show_b = self.showtime_ids()[:2]
        booking = self.add_booking(self.add_user(), show_a, "REF-1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_seat(booking, show_b)

    def test_duplicate_booking_reference_rejected(self) -> None:
        showtime = self.showtime_ids()[0]
        user = self.add_user()
        self.add_booking(user, showtime, "REF-1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_booking(user, showtime, "REF-1")

    def test_invalid_movie_values_rejected(self) -> None:
        base = {
            "title": "Test Film", "genre": "Drama", "duration_minutes": 100,
            "age_rating": "G", "description": "Test.", "ticket_price": 30000,
        }
        invalid = {
            "negative price": {"ticket_price": -100},
            "fractional price": {"ticket_price": 350.5},
            "zero duration": {"duration_minutes": 0},
            "blank title": {"title": "   "},
            "missing genre": {"genre": None},
        }
        for label, override in invalid.items():
            with self.subTest(label):
                values = {**base, **override}
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "INSERT INTO movies (title, genre, duration_minutes, age_rating, "
                        "description, ticket_price) VALUES (:title, :genre, :duration_minutes, "
                        ":age_rating, :description, :ticket_price)",
                        values,
                    )

    def test_invalid_seat_values_rejected(self) -> None:
        showtime = self.showtime_ids()[0]
        booking = self.add_booking(self.add_user(), showtime, "REF-1")
        for row, number in (("A", 0), ("A", -3), ("a", 1), ("AA", 1), ("", 1)):
            with self.subTest(row=row, number=number):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.add_seat(booking, showtime, row, number)

    def test_invalid_showtime_values_rejected(self) -> None:
        for show_date, show_time in (
            ("2030-02-30", "10:00"),
            ("01/15/2030", "10:00"),
            ("2030-01-15", "25:00"),
            ("2030-01-15", "9:00"),
            ("2030-01-15", "10:00 PM"),
        ):
            with self.subTest(show_date=show_date, show_time=show_time):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                        "VALUES (1, ?, ?, 'Cinema 9')",
                        (show_date, show_time),
                    )

    def test_invalid_booking_values_rejected(self) -> None:
        showtime = self.showtime_ids()[0]
        user = self.add_user()
        for status, amount in (("pending", 100), ("confirmed", -1)):
            with self.subTest(status=status, amount=amount):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "INSERT INTO bookings (booking_reference, user_id, showtime_id, "
                        "total_amount, status) VALUES ('REF-X', ?, ?, ?, ?)",
                        (user, showtime, amount, status),
                    )

    def test_deleting_referenced_records_is_restricted(self) -> None:
        showtime = self.showtime_ids()[0]
        user = self.add_user()
        self.add_booking(user, showtime, "REF-1")
        statements = (
            ("DELETE FROM users WHERE id = ?", user),
            ("DELETE FROM showtimes WHERE id = ?", showtime),
            ("DELETE FROM movies WHERE id = (SELECT movie_id FROM showtimes WHERE id = ?)", showtime),
        )
        for sql, param in statements:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(sql, (param,))
        self.assertEqual(self.count("bookings"), 1)


class FormattingTests(unittest.TestCase):
    def test_format_peso(self) -> None:
        self.assertEqual(format_peso(35000), "₱350.00")
        self.assertEqual(format_peso(5), "₱0.05")
        self.assertEqual(format_peso(123456789), "₱1,234,567.89")
        self.assertEqual(format_peso(-1050), "-₱10.50")

    def test_format_showtime_and_truncate(self) -> None:
        self.assertEqual(format_showtime(dt.datetime(2030, 1, 5, 20, 15)), "Sat, Jan 5, 2030  ·  8:15 PM")
        self.assertEqual(truncate("Maria Clara", 20), "Maria Clara")
        self.assertEqual(truncate("Maria Clara de los Santos", 12), "Maria Clara…")
        self.assertEqual(len(truncate("x" * 100, 28)), 28)

    def test_format_local_date_converts_from_utc(self) -> None:
        stamp = "2026-10-23 23:30:00"
        expected = dt.datetime(2026, 10, 23, 23, 30, tzinfo=dt.timezone.utc).astimezone()
        self.assertEqual(format_local_date(stamp),
                         f"{expected:%B} {expected.day}, {expected.year}")


if __name__ == "__main__":
    unittest.main()
