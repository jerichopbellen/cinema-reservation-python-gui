"""Stage 2 tests: password hashing, registration, login, profile, and session.

Each test uses its own temporary SQLite database; the real application
database is never opened. No Tkinter windows are created.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from database import initialize_database
from database.connection import DEFAULT_DB_PATH, PROJECT_ROOT, connect
from services import auth_service
from services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    User,
    UserNotFoundError,
    ValidationError,
    hash_password,
    verify_password,
)
from services.session import NotAuthenticatedError, Session

PASSWORD = "popcorn123"
FAST_ITERATIONS = 1_000


class AuthTestCase(unittest.TestCase):
    """Fresh temporary database per test, with a low PBKDF2 cost to keep tests fast."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "auth.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        initialize_database(self.db_path)

        patcher = mock.patch.object(auth_service, "PBKDF2_ITERATIONS", FAST_ITERATIONS)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.auth = AuthService(self.db_path)

    def register(self, username: str = "juan", full_name: str = "Juan Dela Cruz",
                 password: str = PASSWORD) -> User:
        return self.auth.register(full_name, username, password, password)

    def stored_row(self, user_id: int) -> sqlite3.Row:
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        finally:
            conn.close()


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_not_plaintext_and_verifies(self) -> None:
        encoded, salt = hash_password(PASSWORD, iterations=FAST_ITERATIONS)
        self.assertNotIn(PASSWORD, encoded)
        self.assertNotEqual(encoded, PASSWORD)
        self.assertTrue(encoded.startswith(f"pbkdf2_sha256${FAST_ITERATIONS}$"))
        self.assertTrue(verify_password(PASSWORD, encoded, salt))
        self.assertFalse(verify_password("popcorn124", encoded, salt))

    def test_same_password_gets_different_salt_and_hash(self) -> None:
        first = hash_password(PASSWORD, iterations=FAST_ITERATIONS)
        second = hash_password(PASSWORD, iterations=FAST_ITERATIONS)
        self.assertNotEqual(first[1], second[1])
        self.assertNotEqual(first[0], second[0])

    def test_default_iteration_count_is_used(self) -> None:
        encoded, _ = hash_password(PASSWORD)
        self.assertEqual(int(encoded.split("$")[1]), auth_service.PBKDF2_ITERATIONS)
        self.assertGreaterEqual(auth_service.PBKDF2_ITERATIONS, 600_000)

    def test_malformed_stored_hash_fails_safely(self) -> None:
        for encoded, salt in (("garbage", "00"), ("md5$1$abcd", "00"),
                              ("pbkdf2_sha256$x$abcd", "00"), ("pbkdf2_sha256$10$zz", "00")):
            with self.subTest(encoded=encoded):
                self.assertFalse(verify_password(PASSWORD, encoded, salt))

    def test_service_layer_does_not_import_tkinter(self) -> None:
        code = "import sys, services.auth_service, services.session; print('tkinter' in sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")


class RegistrationTests(AuthTestCase):
    def test_successful_registration_stores_trimmed_values_and_hash(self) -> None:
        user = self.auth.register("  Maria   Clara  ", "  maria.c ", PASSWORD, PASSWORD)
        self.assertEqual(user.full_name, "Maria Clara")
        self.assertEqual(user.username, "maria.c")

        row = self.stored_row(user.id)
        self.assertEqual(row["username"], "maria.c")
        self.assertNotEqual(row["password_hash"], PASSWORD)
        self.assertNotIn(PASSWORD, row["password_hash"])
        self.assertNotIn(PASSWORD, row["password_salt"])
        self.assertTrue(verify_password(PASSWORD, row["password_hash"], row["password_salt"]))

    def test_user_object_exposes_no_password_data(self) -> None:
        user = self.register()
        self.assertEqual(set(vars(user)), {"id", "full_name", "username", "created_at"})

    def test_duplicate_username_rejected_case_insensitively(self) -> None:
        self.register("juan")
        for duplicate in ("juan", "JUAN", " Juan "):
            with self.subTest(duplicate=duplicate):
                with self.assertRaises(ValidationError) as ctx:
                    self.register(duplicate, "Other Person")
                self.assertEqual(ctx.exception.field, "username")

    def test_different_users_get_different_salts(self) -> None:
        a = self.stored_row(self.register("alpha").id)
        b = self.stored_row(self.register("bravo").id)
        self.assertNotEqual(a["password_salt"], b["password_salt"])
        self.assertNotEqual(a["password_hash"], b["password_hash"])

    def test_invalid_registration_data_rejected(self) -> None:
        cases = {
            "blank name": (("   ", "juan", PASSWORD, PASSWORD), "full_name"),
            "long name": (("x" * 81, "juan", PASSWORD, PASSWORD), "full_name"),
            "blank username": (("Juan", "  ", PASSWORD, PASSWORD), "username"),
            "short username": (("Juan", "ju", PASSWORD, PASSWORD), "username"),
            "username with space": (("Juan", "juan dc", PASSWORD, PASSWORD), "username"),
            "username starts with digit": (("Juan", "1juan", PASSWORD, PASSWORD), "username"),
            "username with symbol": (("Juan", "juan!", PASSWORD, PASSWORD), "username"),
            "blank password": (("Juan", "juan", "", ""), "password"),
            "short password": (("Juan", "juan", "abc12", "abc12"), "password"),
            "no digit": (("Juan", "juan", "popcornonly", "popcornonly"), "password"),
            "no letter": (("Juan", "juan", "12345678", "12345678"), "password"),
            "mismatch": (("Juan", "juan", PASSWORD, "popcorn124"), "confirm_password"),
        }
        for label, (args, field) in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValidationError) as ctx:
                    self.auth.register(*args)
                self.assertEqual(ctx.exception.field, field)

        conn = connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        finally:
            conn.close()

    def test_registration_preserves_seeded_movies(self) -> None:
        conn = connect(self.db_path)
        try:
            before = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
            self.register()
            after = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(before, after)
        self.assertGreater(after, 0)


class LoginTests(AuthTestCase):
    def test_login_with_valid_credentials(self) -> None:
        registered = self.register("juan")
        self.assertEqual(self.auth.authenticate("juan", PASSWORD), registered)

    def test_login_ignores_username_case_and_whitespace(self) -> None:
        registered = self.register("juan")
        self.assertEqual(self.auth.authenticate("  JUAN ", PASSWORD).id, registered.id)

    def test_login_with_wrong_password_fails(self) -> None:
        self.register("juan")
        with self.assertRaises(InvalidCredentialsError):
            self.auth.authenticate("juan", "wrongpass1")

    def test_unknown_user_and_wrong_password_give_identical_message(self) -> None:
        self.register("juan")
        with self.assertRaises(InvalidCredentialsError) as wrong_password:
            self.auth.authenticate("juan", "wrongpass1")
        with self.assertRaises(InvalidCredentialsError) as unknown_user:
            self.auth.authenticate("nobody", "wrongpass1")
        self.assertEqual(str(wrong_password.exception), str(unknown_user.exception))

    def test_blank_credentials_fail(self) -> None:
        self.register("juan")
        for username, password in (("", PASSWORD), ("juan", ""), ("  ", "  ")):
            with self.subTest(username=username, password=password):
                with self.assertRaises(InvalidCredentialsError):
                    self.auth.authenticate(username, password)

    def test_password_is_case_sensitive(self) -> None:
        self.register("juan")
        with self.assertRaises(InvalidCredentialsError):
            self.auth.authenticate("juan", PASSWORD.upper())


class ProfileTests(AuthTestCase):
    def test_full_name_update_persists(self) -> None:
        user = self.register()
        updated = self.auth.update_full_name(user.id, "  Juan  P. Dela Cruz ")
        self.assertEqual(updated.full_name, "Juan P. Dela Cruz")
        self.assertEqual(self.stored_row(user.id)["full_name"], "Juan P. Dela Cruz")
        self.assertEqual(self.auth.get_user(user.id).full_name, "Juan P. Dela Cruz")

    def test_blank_full_name_update_rejected(self) -> None:
        user = self.register()
        with self.assertRaises(ValidationError):
            self.auth.update_full_name(user.id, "   ")
        self.assertEqual(self.stored_row(user.id)["full_name"], "Juan Dela Cruz")

    def test_change_password_requires_correct_current_password(self) -> None:
        user = self.register()
        before = self.stored_row(user.id)
        with self.assertRaises(ValidationError) as ctx:
            self.auth.change_password(user.id, "wrongpass1", "newpass456", "newpass456")
        self.assertEqual(ctx.exception.field, "current_password")
        after = self.stored_row(user.id)
        self.assertEqual(before["password_hash"], after["password_hash"])
        self.assertEqual(self.auth.authenticate("juan", PASSWORD).id, user.id)

    def test_change_password_validates_new_password(self) -> None:
        user = self.register()
        cases = (
            ("short1", "short1", "new_password"),
            ("newpass456", "newpass457", "confirm_password"),
            (PASSWORD, PASSWORD, "new_password"),
        )
        for new, confirm, field in cases:
            with self.subTest(new=new, confirm=confirm):
                with self.assertRaises(ValidationError) as ctx:
                    self.auth.change_password(user.id, PASSWORD, new, confirm)
                self.assertEqual(ctx.exception.field, field)

    def test_successful_password_change_invalidates_old_password(self) -> None:
        user = self.register()
        old_salt = self.stored_row(user.id)["password_salt"]

        self.auth.change_password(user.id, PASSWORD, "newpass456", "newpass456")

        self.assertNotEqual(self.stored_row(user.id)["password_salt"], old_salt)
        with self.assertRaises(InvalidCredentialsError):
            self.auth.authenticate("juan", PASSWORD)
        self.assertEqual(self.auth.authenticate("juan", "newpass456").id, user.id)

    def test_profile_operations_do_not_touch_other_users(self) -> None:
        alice = self.register("alice", "Alice Reyes", "alicepass1")
        bob = self.register("bob", "Bob Santos", "bobpass12")
        bob_before = dict(self.stored_row(bob.id))

        self.auth.update_full_name(alice.id, "Alice R. Reyes")
        self.auth.change_password(alice.id, "alicepass1", "alicepass2", "alicepass2")

        self.assertEqual(dict(self.stored_row(bob.id)), bob_before)
        self.assertEqual(self.auth.authenticate("bob", "bobpass12").full_name, "Bob Santos")

    def test_cannot_change_password_with_another_users_password(self) -> None:
        alice = self.register("alice", "Alice Reyes", "alicepass1")
        self.register("bob", "Bob Santos", "bobpass12")
        with self.assertRaises(ValidationError):
            self.auth.change_password(alice.id, "bobpass12", "hacked123", "hacked123")

    def test_operations_on_missing_user_raise(self) -> None:
        with self.assertRaises(UserNotFoundError):
            self.auth.get_user(999)
        with self.assertRaises(UserNotFoundError):
            self.auth.update_full_name(999, "Ghost")
        with self.assertRaises(UserNotFoundError):
            self.auth.change_password(999, PASSWORD, "newpass456", "newpass456")


class SessionTests(AuthTestCase):
    def test_login_update_and_logout(self) -> None:
        session = Session()
        self.assertFalse(session.is_authenticated)
        with self.assertRaises(NotAuthenticatedError):
            session.require_user()

        user = self.register()
        session.login(user)
        self.assertEqual(session.user_id, user.id)

        session.update_user(self.auth.update_full_name(user.id, "Juan Updated"))
        self.assertEqual(session.require_user().full_name, "Juan Updated")

        session.logout()
        self.assertIsNone(session.user)
        self.assertFalse(session.is_authenticated)

    def test_password_change_keeps_session(self) -> None:
        session = Session()
        user = self.register()
        session.login(user)
        self.auth.change_password(user.id, PASSWORD, "newpass456", "newpass456")
        self.assertEqual(session.require_user(), user)

    def test_session_cannot_be_switched_to_another_user_via_update(self) -> None:
        session = Session()
        session.login(self.register("alice"))
        with self.assertRaises(NotAuthenticatedError):
            session.update_user(self.register("bob"))
        self.assertEqual(session.require_user().username, "alice")


if __name__ == "__main__":
    unittest.main()
