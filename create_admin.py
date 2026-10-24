"""Create a Cinemalaya administrator account from the command line.

Usage (from the project folder)::

    python create_admin.py
    python create_admin.py --db path\\to\\other.db

The password is read with hidden input and is never printed, logged, or stored
in plaintext; it is hashed by the same service the app uses. Nothing is
created until you type ``yes`` to confirm. There is no way to create an
administrator from the app's own registration screen.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from database import initialize_database
from services.auth_service import (
    PASSWORD_RULES,
    AuthError,
    AuthService,
    clean_full_name,
    clean_username,
    validate_new_password,
)


def run(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
        getpass_fn: Callable[[str], str] = getpass.getpass, out: TextIO = sys.stdout) -> int:
    """Interactive setup. Returns a process exit code (0 = created)."""
    parser = argparse.ArgumentParser(description="Create a Cinemalaya administrator account.")
    parser.add_argument("--db", type=Path, default=None,
                        help="database file (default: the app's data/cinema.db)")
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        print(message, file=out)

    try:
        db_path = initialize_database(args.db)
        say(f"Creating an administrator account in {db_path}")
        say(f"Password rules: {PASSWORD_RULES}")
        full_name = clean_full_name(input_fn("Full name: "))
        username = clean_username(input_fn("Username: "))
        password = getpass_fn("Password (hidden): ")
        confirm_password = getpass_fn("Confirm password (hidden): ")
        validate_new_password(password, confirm_password)

        answer = input_fn(f"Create administrator account '{username}'? Type 'yes' to confirm: ")
        if answer.strip().lower() != "yes":
            say("Cancelled. No account was created.")
            return 1
        user = AuthService(db_path).create_admin(full_name, username, password, confirm_password)
    except (KeyboardInterrupt, EOFError):
        say("\nCancelled. No account was created.")
        return 1
    except AuthError as exc:
        say(f"Error: {exc} No account was created.")
        return 2
    except (sqlite3.Error, OSError) as exc:
        say(f"Error: the database could not be updated ({exc}). No account was created.")
        return 2

    say(f"Administrator '{user.username}' created. Log in to the app to manage movies.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
