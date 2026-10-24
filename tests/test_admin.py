"""Stage 6 tests: roles, the admin setup utility, and administrator movie management.

Every test uses a temporary SQLite database; the real application database is
never opened. No Tkinter windows are created.
"""

from __future__ import annotations

import inspect
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import create_admin
import promote_admin
from database import initialize_database
from database.connection import DEFAULT_DB_PATH, connect
from database.schema import ROLE_ADMIN, ROLE_CUSTOMER, apply_migrations, column_names, create_schema
from services import auth_service
from services.auth_service import AuthorizationError, AuthService
from services.booking_service import BookingService
from services.catalog_service import CatalogError, CatalogService, ShowtimeUnavailableError
from services.movie_admin_service import (
    MovieAdminService,
    MovieNotFoundError,
    MovieValidationError,
    parse_duration,
    parse_price,
    validate_movie,
)
from services.receipt_service import render_receipt
from services.seating_service import SeatingService
from tests.helpers import START_CLOCK, FakeClock, create_seeded_database

PASSWORD = "popcorn123"


def draft(**overrides: str):
    values = {"title": "Tide of Lanterns", "genre": "Drama", "duration": "104", "age_rating": "PG",
              "description": "Two sisters reopen their late father's seaside cinema.", "price": "320.50"}
    values.update(overrides)
    return validate_movie(values["title"], values["genre"], values["duration"], values["age_rating"],
                          values["description"], values["price"])


class FastHashing(unittest.TestCase):
    """Lower the PBKDF2 cost so account creation is quick in tests."""

    def setUp(self) -> None:
        patcher = mock.patch.object(auth_service, "PBKDF2_ITERATIONS", 1_000)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)
        self.db_path = self.tmp_dir / "admin.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())


class MigrationTests(FastHashing):
    def build_legacy_database(self) -> None:
        """A database as Stage 5 left it: no users.role and no bookings.movie_title."""
        conn = connect(self.db_path)
        try:
            create_schema(conn)
            self.assertNotIn("role", column_names(conn, "users"))
            conn.execute("INSERT INTO users (full_name, username, password_hash, password_salt) "
                         "VALUES ('Old Customer', 'oldie', 'pbkdf2_sha256$1000$abcd', '00ff')")
            conn.execute("INSERT INTO movies (title, genre, duration_minutes, age_rating, description, "
                         "ticket_price) VALUES ('Legacy Film', 'Drama', 90, 'PG', 'Old.', 30000)")
            conn.execute("INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) "
                         "VALUES (1, '2030-01-02', '10:30', 'Cinema 1')")
            conn.execute("INSERT INTO bookings (booking_reference, user_id, showtime_id, total_amount) "
                         "VALUES ('CR-OLDBOOKING', 1, 1, 60000)")
            conn.execute("INSERT INTO booked_seats (booking_id, showtime_id, seat_row, seat_number) "
                         "VALUES (1, 1, 'A', 1), (1, 1, 'A', 2)")
            conn.commit()
        finally:
            conn.close()

    def test_existing_users_become_customers_and_data_is_preserved(self) -> None:
        self.build_legacy_database()
        initialize_database(self.db_path)
        initialize_database(self.db_path)  # a second launch is a no-op

        conn = connect(self.db_path)
        try:
            user = conn.execute("SELECT * FROM users WHERE username = 'oldie'").fetchone()
            self.assertEqual(user["role"], ROLE_CUSTOMER)
            self.assertEqual((user["full_name"], user["password_hash"], user["password_salt"]),
                             ("Old Customer", "pbkdf2_sha256$1000$abcd", "00ff"))
            booking = conn.execute("SELECT * FROM bookings").fetchone()
            self.assertEqual((booking["total_amount"], booking["movie_title"]), (60000, "Legacy Film"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM booked_seats").fetchone()[0], 2)
            self.assertEqual(apply_migrations(conn), [])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            conn.close()

    def test_role_column_rejects_unknown_roles(self) -> None:
        initialize_database(self.db_path)
        conn = connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO users (full_name, username, password_hash, password_salt, role) "
                             "VALUES ('X', 'x', 'h', 's', 'superuser')")
        finally:
            conn.close()


class AdminSetupTests(FastHashing):
    def run_setup(self, answers: list[str], passwords: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        inputs, secrets = iter(answers), iter(passwords)
        code = create_admin.run(["--db", str(self.db_path)], input_fn=lambda _prompt: next(inputs),
                                getpass_fn=lambda _prompt: next(secrets), out=output)
        return code, output.getvalue()

    def test_setup_creates_admin_without_printing_password(self) -> None:
        code, output = self.run_setup(["Ada Admin", "ada", "yes"], [PASSWORD, PASSWORD])
        self.assertEqual(code, 0)
        self.assertNotIn(PASSWORD, output)
        user = AuthService(self.db_path).authenticate("ada", PASSWORD)
        self.assertEqual(user.role, ROLE_ADMIN)
        self.assertTrue(user.is_admin)
        conn = connect(self.db_path)
        try:
            stored = conn.execute("SELECT password_hash FROM users WHERE username = 'ada'").fetchone()[0]
        finally:
            conn.close()
        self.assertNotIn(PASSWORD, stored)

    def test_setup_requires_explicit_confirmation(self) -> None:
        code, output = self.run_setup(["Ada Admin", "ada", "no"], [PASSWORD, PASSWORD])
        self.assertEqual(code, 1)
        self.assertIn("No account was created", output)
        self.assertEqual(self.user_count(), 0)

    def test_setup_rejects_invalid_input_before_confirming(self) -> None:
        for answers, passwords in ((["Ada", "ada"], ["short", "short"]),
                                   (["Ada", "ada"], [PASSWORD, "different1"]),
                                   (["  ", "ada"], [PASSWORD, PASSWORD])):
            with self.subTest(answers=answers, passwords=passwords):
                code, output = self.run_setup(answers, passwords)
                self.assertEqual(code, 2)
                self.assertNotIn(PASSWORD, output)
        self.assertEqual(self.user_count(), 0)

    def test_setup_rejects_taken_username(self) -> None:
        initialize_database(self.db_path)
        AuthService(self.db_path).register("Existing", "ada", PASSWORD, PASSWORD)
        code, output = self.run_setup(["Ada Admin", "ADA", "yes"], [PASSWORD, PASSWORD])
        self.assertEqual(code, 2)
        self.assertIn("already taken", output)
        self.assertEqual(AuthService(self.db_path).authenticate("ada", PASSWORD).role, ROLE_CUSTOMER)

    def user_count(self) -> int:
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            conn.close()


class PromoteTests(FastHashing):
    def setUp(self) -> None:
        super().setUp()
        initialize_database(self.db_path)
        self.auth = AuthService(self.db_path)
        self.user = self.auth.register("Jericho Bellen", "jericho", PASSWORD, PASSWORD)

    def run_promote(self, args: list[str], answer: str = "yes") -> tuple[int, str]:
        output = io.StringIO()
        code = promote_admin.run([*args, "--db", str(self.db_path)],
                                 input_fn=lambda _prompt: answer, out=output)
        return code, output.getvalue()

    def stored(self) -> sqlite3.Row:
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT * FROM users WHERE id = ?", (self.user.id,)).fetchone()
        finally:
            conn.close()

    def test_promote_then_revoke(self) -> None:
        before = self.stored()
        code, output = self.run_promote(["JERICHO"])  # usernames match case-insensitively
        self.assertEqual(code, 0)
        self.assertIn("now an administrator", output)
        self.assertTrue(self.auth.authenticate("jericho", PASSWORD).is_admin)
        after = self.stored()
        self.assertEqual((after["full_name"], after["password_hash"], after["password_salt"], after["created_at"]),
                         (before["full_name"], before["password_hash"], before["password_salt"], before["created_at"]))
        MovieAdminService(self.db_path, self.auth).list_movies(self.user.id)  # admin access works

        code, output = self.run_promote(["jericho", "--revoke"])
        self.assertEqual(code, 0)
        self.assertEqual(self.stored()["role"], ROLE_CUSTOMER)
        with self.assertRaises(AuthorizationError):
            MovieAdminService(self.db_path, self.auth).list_movies(self.user.id)

    def test_requires_explicit_confirmation(self) -> None:
        code, output = self.run_promote(["jericho"], answer="no")
        self.assertEqual(code, 1)
        self.assertIn("No changes were made", output)
        self.assertEqual(self.stored()["role"], ROLE_CUSTOMER)

    def test_unknown_user_and_no_op_changes_are_rejected(self) -> None:
        code, output = self.run_promote(["nobody"])
        self.assertEqual(code, 2)
        self.assertIn("No account with the username 'nobody'", output)
        code, output = self.run_promote(["jericho", "--revoke"])  # already a customer
        self.assertEqual(code, 2)
        self.assertIn("already a customer", output)
        self.assertEqual(self.stored()["role"], ROLE_CUSTOMER)

    def test_service_rejects_bad_role_changes(self) -> None:
        with self.assertRaises(ValueError):
            self.auth.set_role("jericho", "superuser")
        with self.assertRaises(auth_service.UserNotFoundError):
            self.auth.set_role("nobody", ROLE_ADMIN)
        self.auth.set_role("jericho", ROLE_ADMIN)
        with self.assertRaises(auth_service.AuthError):
            self.auth.set_role("jericho", ROLE_ADMIN)


class AdminTestCase(FastHashing):
    def setUp(self) -> None:
        super().setUp()
        create_seeded_database(self.db_path)
        self.clock = FakeClock(START_CLOCK)
        self.auth = AuthService(self.db_path)
        self.catalog = CatalogService(self.db_path, now=self.clock)
        self.seating = SeatingService(self.db_path, self.catalog)
        self.bookings = BookingService(self.db_path, self.catalog)
        self.movies = MovieAdminService(self.db_path, self.auth)
        self.admin = self.auth.create_admin("Ada Admin", "ada", PASSWORD, PASSWORD)
        self.customer = self.auth.register("Carlo Customer", "carlo", PASSWORD, PASSWORD)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

    def movie_id(self, title: str = "The Last Lighthouse Keeper") -> int:
        return self.conn.execute("SELECT id FROM movies WHERE title = ?", (title,)).fetchone()[0]

    def count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class RoleTests(AdminTestCase):
    def test_public_registration_always_creates_customers(self) -> None:
        self.assertEqual(self.customer.role, ROLE_CUSTOMER)
        self.assertFalse(self.customer.is_admin)
        self.assertNotIn("role", inspect.signature(AuthService.register).parameters)
        self.assertEqual(self.auth.get_user(self.customer.id).role, ROLE_CUSTOMER)

    def test_require_admin_reads_the_role_from_the_database(self) -> None:
        self.assertEqual(self.auth.require_admin(self.admin.id).id, self.admin.id)
        with self.assertRaises(AuthorizationError):
            self.auth.require_admin(self.customer.id)

    def test_demoted_admin_loses_access_immediately(self) -> None:
        self.movies.list_movies(self.admin.id)
        self.conn.execute("UPDATE users SET role = ? WHERE id = ?", (ROLE_CUSTOMER, self.admin.id))
        self.conn.commit()
        with self.assertRaises(AuthorizationError):
            self.movies.list_movies(self.admin.id)


class CreateAndEditTests(AdminTestCase):
    def test_admin_can_create_movie_visible_to_customers(self) -> None:
        movie = self.movies.create_movie(self.admin.id, draft())
        self.assertEqual((movie.title, movie.ticket_price, movie.duration_minutes, movie.is_active),
                         ("Tide of Lanterns", 32050, 104, True))
        self.assertIn(movie.id, [m.id for m in self.movies.list_movies(self.admin.id)])
        catalog = {m.id: m for m in self.catalog.list_active_movies()}
        self.assertEqual(catalog[movie.id].ticket_price, 32050)

    def test_admin_can_edit_movie_and_keep_its_id_and_showtimes(self) -> None:
        movie_id = self.movie_id()
        showtimes_before = self.conn.execute(
            "SELECT id FROM showtimes WHERE movie_id = ? ORDER BY id", (movie_id,)).fetchall()
        updated = self.movies.update_movie(self.admin.id, movie_id, draft(
            title="The Last Lighthouse Keeper (Director's Cut)", genre="Drama", duration="131",
            age_rating="R-13", price="₱1,250"))
        self.assertEqual(updated.id, movie_id)
        self.assertEqual((updated.title, updated.duration_minutes, updated.age_rating, updated.ticket_price),
                         ("The Last Lighthouse Keeper (Director's Cut)", 131, "R-13", 125000))
        showtimes_after = self.conn.execute(
            "SELECT id FROM showtimes WHERE movie_id = ? ORDER BY id", (movie_id,)).fetchall()
        self.assertEqual([tuple(r) for r in showtimes_before], [tuple(r) for r in showtimes_after])
        self.assertEqual(self.catalog.get_active_movie(movie_id).title,
                         "The Last Lighthouse Keeper (Director's Cut)")

    def test_titles_must_be_unique_ignoring_case(self) -> None:
        with self.assertRaises(MovieValidationError) as ctx:
            self.movies.create_movie(self.admin.id, draft(title="neon monsoon"))
        self.assertEqual(ctx.exception.field, "title")
        with self.assertRaises(MovieValidationError):
            self.movies.update_movie(self.admin.id, self.movie_id(), draft(title="ORBITFALL"))
        # Re-saving a movie under its own title is fine.
        self.movies.update_movie(self.admin.id, self.movie_id("Orbitfall"), draft(title="Orbitfall"))

    def test_editing_a_missing_movie_fails_cleanly(self) -> None:
        with self.assertRaises(MovieNotFoundError):
            self.movies.update_movie(self.admin.id, 9999, draft())
        with self.assertRaises(MovieNotFoundError):
            self.movies.get_movie(self.admin.id, 9999)


class ValidationTests(unittest.TestCase):
    def test_invalid_movie_data_is_rejected(self) -> None:
        cases = {
            "blank title": ({"title": "   "}, "title"),
            "blank genre": ({"genre": ""}, "genre"),
            "blank rating": ({"age_rating": ""}, "age_rating"),
            "unknown rating": ({"age_rating": "PG-13"}, "age_rating"),
            "blank description": ({"description": "\n  "}, "description"),
            "zero duration": ({"duration": "0"}, "duration_minutes"),
            "negative duration": ({"duration": "-5"}, "duration_minutes"),
            "fractional duration": ({"duration": "90.5"}, "duration_minutes"),
            "text duration": ({"duration": "long"}, "duration_minutes"),
            "negative price": ({"price": "-1"}, "ticket_price"),
            "blank price": ({"price": ""}, "ticket_price"),
            "three decimals": ({"price": "350.505"}, "ticket_price"),
            "letters": ({"price": "three hundred"}, "ticket_price"),
            "bad commas": ({"price": "1,25"}, "ticket_price"),
            "too expensive": ({"price": "10000.01"}, "ticket_price"),
            "title too long": ({"title": "x" * 121}, "title"),
        }
        for label, (overrides, field) in cases.items():
            with self.subTest(label):
                with self.assertRaises(MovieValidationError) as ctx:
                    draft(**overrides)
                self.assertEqual(ctx.exception.field, field)

    def test_prices_become_integer_centavos(self) -> None:
        for text, expected in (("350", 35000), ("350.5", 35050), ("350.05", 35005), ("₱1,250.50", 125050),
                               (" 0 ", 0), ("PHP 99.99", 9999)):
            with self.subTest(text=text):
                self.assertEqual(parse_price(text), expected)
                self.assertIsInstance(parse_price(text), int)

    def test_text_is_trimmed_and_rating_normalized(self) -> None:
        movie = draft(title="  Tide   of Lanterns ", age_rating=" pg ")
        self.assertEqual((movie.title, movie.age_rating), ("Tide of Lanterns", "PG"))
        self.assertEqual(parse_duration(" 104 "), 104)


class CustomerAccessTests(AdminTestCase):
    def test_customers_cannot_use_any_admin_operation(self) -> None:
        movie_id = self.movie_id()
        before = [tuple(r) for r in self.conn.execute("SELECT * FROM movies ORDER BY id")]
        operations = {
            "list": lambda: self.movies.list_movies(self.customer.id),
            "get": lambda: self.movies.get_movie(self.customer.id, movie_id),
            "create": lambda: self.movies.create_movie(self.customer.id, draft()),
            "edit": lambda: self.movies.update_movie(self.customer.id, movie_id, draft()),
            "archive/delete": lambda: self.movies.remove_movie(self.customer.id, movie_id),
            "restore": lambda: self.movies.restore_movie(self.customer.id, movie_id),
        }
        for name, operation in operations.items():
            with self.subTest(name):
                with self.assertRaises(AuthorizationError):
                    operation()
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT * FROM movies ORDER BY id")], before)

    def test_unknown_user_ids_are_rejected(self) -> None:
        with self.assertRaises(auth_service.UserNotFoundError):
            self.movies.create_movie(9999, draft())


class RemovalTests(AdminTestCase):
    def book(self, title: str = "The Last Lighthouse Keeper", seats: tuple[str, ...] = ("C4", "C5")):
        showtime = self.catalog.list_upcoming_showtimes(self.movie_id(title))[0]
        return self.bookings.create_booking(self.customer.id, showtime.id, seats)

    def test_movie_without_history_is_deleted(self) -> None:
        movie = self.movies.create_movie(self.admin.id, draft())
        self.assertTrue(movie.can_delete)
        self.assertEqual(self.movies.remove_movie(self.admin.id, movie.id), "deleted")
        self.assertIsNone(self.conn.execute("SELECT 1 FROM movies WHERE id = ?", (movie.id,)).fetchone())

    def test_movie_with_bookings_is_archived_not_deleted(self) -> None:
        booking = self.book()
        movie_id = self.movie_id()
        counts = (self.count("showtimes"), self.count("bookings"), self.count("booked_seats"))
        self.assertEqual(self.movies.remove_movie(self.admin.id, movie_id), "archived")
        row = self.conn.execute("SELECT is_active FROM movies WHERE id = ?", (movie_id,)).fetchone()
        self.assertEqual(row[0], 0)
        self.assertEqual((self.count("showtimes"), self.count("bookings"), self.count("booked_seats")), counts)
        self.assertEqual(self.bookings.get_booking(self.customer.id, booking.id).status, "confirmed")

    def test_movie_with_only_showtimes_is_archived(self) -> None:
        movie_id = self.movie_id("Orbitfall")
        self.assertEqual(self.movies.get_movie(self.admin.id, movie_id).booking_count, 0)
        self.assertEqual(self.movies.remove_movie(self.admin.id, movie_id), "archived")
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM movies WHERE id = ?", (movie_id,)).fetchone())

    def test_archived_movies_leave_the_customer_catalog(self) -> None:
        movie_id = self.movie_id()
        self.movies.remove_movie(self.admin.id, movie_id)
        self.assertNotIn(movie_id, [m.id for m in self.catalog.list_active_movies()])
        self.assertEqual(self.catalog.list_upcoming_showtimes(movie_id), [])
        with self.assertRaises(CatalogError):
            self.catalog.get_active_movie(movie_id)
        self.assertIn(movie_id, [m.id for m in self.movies.list_movies(self.admin.id)])

    def test_archived_movies_cannot_be_booked_even_via_an_old_showtime(self) -> None:
        movie_id = self.movie_id()
        showtime = self.catalog.list_upcoming_showtimes(movie_id)[0]
        self.movies.remove_movie(self.admin.id, movie_id)
        with self.assertRaises(ShowtimeUnavailableError):
            self.seating.open_showtime(showtime.id)
        before = self.count("bookings")
        with self.assertRaises(ShowtimeUnavailableError):
            self.bookings.create_booking(self.customer.id, showtime.id, ["A1"])
        self.assertEqual(self.count("bookings"), before)

    def test_restore_makes_an_archived_movie_bookable_again(self) -> None:
        movie_id = self.movie_id()
        self.movies.remove_movie(self.admin.id, movie_id)
        self.assertTrue(self.movies.restore_movie(self.admin.id, movie_id).is_active)
        showtime = self.catalog.list_upcoming_showtimes(movie_id)[0]
        self.assertEqual(self.bookings.create_booking(self.customer.id, showtime.id, ["A1"]).status,
                         "confirmed")

    def test_bookings_and_receipts_survive_edits_and_archiving(self) -> None:
        booking = self.book()
        before = self.bookings.get_booking(self.customer.id, booking.id)
        receipt_before = render_receipt(before)

        movie_id = self.movie_id()
        self.movies.update_movie(self.admin.id, movie_id, draft(title="Renamed Film", price="999"))
        self.movies.remove_movie(self.admin.id, movie_id)
        after = self.bookings.get_booking(self.customer.id, booking.id)

        self.assertEqual((after.movie_title, after.total_amount, after.price_per_ticket, after.seat_labels,
                          after.reference, after.status),
                         (before.movie_title, before.total_amount, before.price_per_ticket,
                          before.seat_labels, before.reference, before.status))
        self.assertEqual(after.movie_title, "The Last Lighthouse Keeper")
        self.assertEqual(after.total_amount, 70000)
        receipt_after = render_receipt(after)
        self.assertIn("The Last Lighthouse Keeper", receipt_after)
        self.assertNotIn("Renamed Film", receipt_after)
        self.assertEqual(receipt_before.split("Generated")[0], receipt_after.split("Generated")[0])
        # Cancellation of the old booking still works on an archived movie's future showtime.
        self.assertEqual(self.bookings.cancel_booking(self.customer.id, booking.id).status, "canceled")

    def test_removing_a_missing_movie_fails_cleanly(self) -> None:
        with self.assertRaises(MovieNotFoundError):
            self.movies.remove_movie(self.admin.id, 9999)
        with self.assertRaises(MovieNotFoundError):
            self.movies.restore_movie(self.admin.id, 9999)


if __name__ == "__main__":
    unittest.main()
