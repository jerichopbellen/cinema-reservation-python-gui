"""Add new fictional movies with upcoming showtimes to the Cinemalaya database.

Usage (from the project folder)::

    python seed_movies.py                    # 5 movies, 2 screenings a day for 3 days
    python seed_movies.py --movies 8 --days 5 --per-day 3
    python seed_movies.py --yes              # skip the confirmation prompt
    python seed_movies.py --db path\\to\\other.db

Each run adds movies whose titles and descriptions are not already in the
database, and showtimes that all start after the moment you run it (today's
remaining hours count). Showtimes never overlap each other or existing ones in
the same cinema, including the cleaning time between screenings. Nothing is
changed or deleted, and either everything is added or nothing is.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from database import initialize_database
from database.connection import write_transaction
from database.movie_generator import GenerationError, seed_generated
from utils.formatting import format_duration, format_peso, format_showtime


def _positive(maximum: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        if not text.isdigit() or not 1 <= int(text) <= maximum:
            raise argparse.ArgumentTypeError(f"must be a whole number from 1 to {maximum}")
        return int(text)
    return parse


def run(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
        out: TextIO = sys.stdout, now: Callable[[], dt.datetime] = dt.datetime.now,
        rng: random.Random | None = None) -> int:
    """Seed new movies and showtimes. Returns a process exit code (0 = added)."""
    parser = argparse.ArgumentParser(description="Add new movies with upcoming showtimes.")
    parser.add_argument("--movies", type=_positive(20), default=5, help="how many movies to add (default 5)")
    parser.add_argument("--days", type=_positive(14), default=3,
                        help="how many days of showtimes, starting today (default 3)")
    parser.add_argument("--per-day", type=_positive(4), default=2,
                        help="screenings per movie per day (default 2)")
    parser.add_argument("--yes", action="store_true", help="add without asking for confirmation")
    parser.add_argument("--db", type=Path, default=None,
                        help="database file (default: the app's data/cinema.db)")
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        print(message, file=out)

    total = args.movies * args.days * args.per_day
    try:
        db_path = initialize_database(args.db)
        if not args.yes:
            answer = input_fn(f"Add {args.movies} new movies and {total} showtimes to {db_path}? "
                              "Type 'yes' to confirm: ")
            if answer.strip().lower() != "yes":
                say("Cancelled. No changes were made.")
                return 1
        # The clock is read after confirming, so every showtime is after the moment of seeding.
        with write_transaction(db_path) as conn:
            movies, plan = seed_generated(conn, args.movies, args.per_day, args.days, now(),
                                          rng or random.Random())
    except (KeyboardInterrupt, EOFError):
        say("\nCancelled. No changes were made.")
        return 1
    except GenerationError as exc:
        say(f"Error: {exc} No changes were made.")
        return 2
    except (sqlite3.Error, OSError) as exc:
        say(f"Error: the database could not be updated ({exc}). No changes were made.")
        return 2

    for index, movie in enumerate(movies):
        say(f"\n{movie.title}  ·  {movie.genre}  ·  {movie.age_rating}  ·  "
            f"{format_duration(movie.duration_minutes)}  ·  {format_peso(movie.ticket_price)}")
        for show in plan:
            if show.movie_index == index:
                say(f"    {format_showtime(show.starts_at)}  ·  {show.auditorium}")
    say(f"\nAdded {len(movies)} movies and {len(plan)} showtimes.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ₱ and · on any console
    sys.exit(run())
