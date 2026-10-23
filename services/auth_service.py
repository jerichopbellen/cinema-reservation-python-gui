"""User registration, authentication, and profile management.

This module has no Tkinter dependency so it can be tested headlessly.

Passwords are hashed with PBKDF2-HMAC-SHA256 and a per-user random salt. The
``password_hash`` column stores a self-describing string
``pbkdf2_sha256$<iterations>$<hex digest>`` so the iteration count can be raised
in the future without breaking existing accounts; ``password_salt`` stores the
salt as hex. Plaintext passwords are never stored or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from database.connection import get_connection
from services.errors import UserFacingError

HASH_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16

USERNAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.]{2,19}")
FULL_NAME_MAX_LENGTH = 80
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

USERNAME_RULES = "3–20 characters using letters, numbers, underscores, or periods, starting with a letter."
PASSWORD_RULES = f"At least {PASSWORD_MIN_LENGTH} characters, including at least one letter and one number."
INVALID_CREDENTIALS_MESSAGE = "Incorrect username or password."


class AuthError(UserFacingError):
    """Base class for authentication and profile errors."""


class ValidationError(AuthError):
    """Input failed validation. ``field`` names the offending form field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class InvalidCredentialsError(AuthError):
    """Login or current-password check failed. The message never says which part was wrong."""

    def __init__(self) -> None:
        super().__init__(INVALID_CREDENTIALS_MESSAGE)


class UserNotFoundError(AuthError):
    """The session refers to a user that no longer exists."""


@dataclass(frozen=True)
class User:
    """Public user data. Deliberately excludes password hash and salt."""

    id: int
    full_name: str
    username: str
    created_at: str


# --- Password hashing ---------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None,
                  iterations: int | None = None) -> tuple[str, str]:
    """Hash ``password`` and return ``(encoded_hash, salt_hex)`` for storage."""
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    iterations = iterations if iterations is not None else PBKDF2_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_ALGORITHM}${iterations}${digest.hex()}", salt.hex()


def verify_password(password: str, encoded_hash: str, salt_hex: str) -> bool:
    """Return True if ``password`` matches the stored hash, using a constant-time compare."""
    try:
        algorithm, iterations_text, expected_hex = encoded_hash.split("$")
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False
    if algorithm != HASH_ALGORITHM or iterations <= 0:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


# --- Validation ---------------------------------------------------------------

def clean_full_name(full_name: str) -> str:
    """Trim and collapse whitespace; reject blank or overly long names."""
    cleaned = " ".join((full_name or "").split())
    if not cleaned:
        raise ValidationError("full_name", "Please enter your full name.")
    if len(cleaned) > FULL_NAME_MAX_LENGTH:
        raise ValidationError("full_name", f"Full name must be at most {FULL_NAME_MAX_LENGTH} characters.")
    return cleaned


def clean_username(username: str) -> str:
    """Trim the username and check it against :data:`USERNAME_PATTERN`."""
    cleaned = (username or "").strip()
    if not cleaned:
        raise ValidationError("username", "Please enter a username.")
    if not USERNAME_PATTERN.fullmatch(cleaned):
        raise ValidationError("username", f"Usernames must be {USERNAME_RULES}")
    return cleaned


def validate_new_password(password: str, confirm_password: str, field: str = "password") -> None:
    """Check password strength rules and that the confirmation matches."""
    if not password:
        raise ValidationError(field, "Please enter a password.")
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(
            field, f"Password must be {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} characters long."
        )
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise ValidationError(field, "Password must include at least one letter and one number.")
    if password != confirm_password:
        raise ValidationError("confirm_password", "Passwords do not match.")


# --- Service ------------------------------------------------------------------

def _row_to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], full_name=row["full_name"], username=row["username"],
                created_at=row["created_at"])


class AuthService:
    """Account operations backed by the ``users`` table."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = db_path

    def register(self, full_name: str, username: str, password: str, confirm_password: str) -> User:
        """Create an account. Raises :class:`ValidationError` on bad input or a taken username."""
        full_name = clean_full_name(full_name)
        username = clean_username(username)
        validate_new_password(password, confirm_password)

        with get_connection(self.db_path) as conn:
            # The username column is COLLATE NOCASE, so this check is case-insensitive.
            if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ValidationError("username", "That username is already taken.")

        password_hash, password_salt = hash_password(password)
        with get_connection(self.db_path) as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO users (full_name, username, password_hash, password_salt) "
                    "VALUES (?, ?, ?, ?)",
                    (full_name, username, password_hash, password_salt),
                )
            except sqlite3.IntegrityError as exc:
                # Another registration may have claimed the name since the check above.
                if "users.username" in str(exc):
                    raise ValidationError("username", "That username is already taken.") from exc
                raise
            row = conn.execute(
                "SELECT id, full_name, username, created_at FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _row_to_user(row)

    def authenticate(self, username: str, password: str) -> User:
        """Return the user for valid credentials, else raise :class:`InvalidCredentialsError`."""
        username = (username or "").strip()
        if not username or not password:
            raise InvalidCredentialsError()

        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, full_name, username, created_at, password_hash, password_salt "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        if row is None:
            # Spend comparable time hashing so response time does not reveal unknown usernames.
            hash_password(password)
            raise InvalidCredentialsError()
        if not verify_password(password, row["password_hash"], row["password_salt"]):
            raise InvalidCredentialsError()
        return _row_to_user(row)

    def get_user(self, user_id: int) -> User:
        """Load a user by ID or raise :class:`UserNotFoundError`."""
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, full_name, username, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise UserNotFoundError("Your account could not be found. Please log in again.")
        return _row_to_user(row)

    def update_full_name(self, user_id: int, full_name: str) -> User:
        """Change the user's full name and return the updated user."""
        full_name = clean_full_name(full_name)
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
            if cursor.rowcount != 1:
                raise UserNotFoundError("Your account could not be found. Please log in again.")
        return self.get_user(user_id)

    def change_password(self, user_id: int, current_password: str, new_password: str,
                        confirm_password: str) -> None:
        """Replace the password after verifying the current one. A fresh salt is generated."""
        if not current_password:
            raise ValidationError("current_password", "Please enter your current password.")
        validate_new_password(new_password, confirm_password, field="new_password")
        if new_password == current_password:
            raise ValidationError("new_password", "New password must be different from the current one.")

        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                raise UserNotFoundError("Your account could not be found. Please log in again.")
            if not verify_password(current_password, row["password_hash"], row["password_salt"]):
                raise ValidationError("current_password", "Current password is incorrect.")

            password_hash, password_salt = hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (password_hash, password_salt, user_id),
            )
