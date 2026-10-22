"""Print a read-only summary of the application database.

Usage (from the project folder)::

    python -m database.inspect_db
    python -m database.inspect_db path\\to\\other.db
"""

from __future__ import annotations

import sys
from pathlib import Path

from database.connection import DEFAULT_DB_PATH, connect
from database.schema import REQUIRED_TABLES
from utils.formatting import format_peso


def main(argv: list[str]) -> int:
    # The peso sign is not representable in some legacy Windows code pages.
    sys.stdout.reconfigure(encoding="utf-8")
    db_path = Path(argv[0]) if argv else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"No database found at {db_path}. Run 'python main.py' once to create it.")
        return 1

    conn = connect(db_path)
    try:
        print(f"Database: {db_path}\n")
        for table in REQUIRED_TABLES:
            # Table names come from a fixed constant, not user input.
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<13} {count:>4} rows")

        print("\nMovies:")
        for movie in conn.execute(
            "SELECT id, title, genre, duration_minutes, age_rating, ticket_price, is_active "
            "FROM movies ORDER BY id"
        ):
            print(
                f"  [{movie['id']}] {movie['title']} | {movie['genre']} | "
                f"{movie['duration_minutes']} min | {movie['age_rating']} | "
                f"{format_peso(movie['ticket_price'])} | active={movie['is_active']}"
            )

        print("\nShowtimes:")
        for show in conn.execute(
            "SELECT s.id, s.show_date, s.show_time, s.auditorium, m.title "
            "FROM showtimes s JOIN movies m ON m.id = s.movie_id "
            "ORDER BY s.show_date, s.show_time, s.auditorium"
        ):
            print(
                f"  [{show['id']}] {show['show_date']} {show['show_time']} "
                f"{show['auditorium']:<9} {show['title']}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
