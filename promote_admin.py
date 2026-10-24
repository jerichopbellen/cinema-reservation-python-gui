"""Promote an existing Cinemalaya account to administrator, or revoke it.

Usage (from the project folder)::

    python promote_admin.py USERNAME            # make USERNAME an administrator
    python promote_admin.py USERNAME --revoke   # make USERNAME a customer again
    python promote_admin.py USERNAME --db path\\to\\other.db

Nothing changes until you type ``yes`` to confirm. Like ``create_admin.py``,
this is a local administrative tool: anyone who can run it can already edit
the database file directly, so it does not ask for a password. The change
takes effect on the user's next action in the app, because the app re-checks
roles in the database every time.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from database import initialize_database
from database.schema import ROLE_ADMIN, ROLE_CUSTOMER
from services.auth_service import AuthError, AuthService


def run(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
        out: TextIO = sys.stdout) -> int:
    """Interactive role change. Returns a process exit code (0 = changed)."""
    parser = argparse.ArgumentParser(description="Promote a Cinemalaya account to administrator.")
    parser.add_argument("username", help="the account to change")
    parser.add_argument("--revoke", action="store_true",
                        help="remove administrator access instead (make the account a customer)")
    parser.add_argument("--db", type=Path, default=None,
                        help="database file (default: the app's data/cinema.db)")
    args = parser.parse_args(argv)
    new_role = ROLE_CUSTOMER if args.revoke else ROLE_ADMIN
    action = "Revoke administrator access from" if args.revoke else "Promote to administrator:"

    def say(message: str) -> None:
        print(message, file=out)

    try:
        db_path = initialize_database(args.db)
        service = AuthService(db_path)
        user = service.find_user(args.username)
        say(f"Account: {user.full_name} (@{user.username}), currently {user.role}")
        if user.role == new_role:
            say(f"Nothing to do: @{user.username} is already {'an administrator' if new_role == ROLE_ADMIN else 'a customer'}.")
            return 2
        answer = input_fn(f"{action} @{user.username}? Type 'yes' to confirm: ")
        if answer.strip().lower() != "yes":
            say("Cancelled. No changes were made.")
            return 1
        updated = service.set_role(user.username, new_role)
    except (KeyboardInterrupt, EOFError):
        say("\nCancelled. No changes were made.")
        return 1
    except AuthError as exc:
        say(f"Error: {exc} No changes were made.")
        return 2
    except (sqlite3.Error, OSError) as exc:
        say(f"Error: the database could not be updated ({exc}). No changes were made.")
        return 2

    if updated.is_admin:
        say(f"@{updated.username} is now an administrator. They will see Manage Movies after their "
            "next action in the app (or after logging in).")
    else:
        say(f"@{updated.username} is now a customer and can no longer manage movies.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
