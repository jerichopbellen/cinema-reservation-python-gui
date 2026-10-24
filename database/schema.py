"""Database schema definition.

All statements use ``IF NOT EXISTS`` so :func:`create_schema` is safe to run on
every launch; it never drops or rewrites existing tables or data.

Design notes
------------
* Money columns (``ticket_price``, ``total_amount``) store integer centavos.
* Foreign keys use ``ON DELETE RESTRICT`` so that deleting a user, movie, or
  showtime can never silently erase booking history. The only cascade is from
  a booking to its own seat rows.
* Seat uniqueness is enforced by a *partial* unique index on
  ``booked_seats(showtime_id, seat_row, seat_number) WHERE is_released = 0``.
  When a booking is canceled (Stage 4), its seat rows are kept for history and
  flagged ``is_released = 1``, which frees the seat for a new booking.
  SQLite partial indexes cannot reference other tables, which is why the flag
  lives on ``booked_seats`` rather than being derived from ``bookings.status``.
* ``booked_seats`` references ``bookings(id, showtime_id)`` as a composite key
  so a seat row can never point to a different showtime than its booking.
* SQLite treats a CHECK that evaluates to NULL as passing, so date/time checks
  use ``IS`` comparisons to reject unparseable values.
"""

from __future__ import annotations

import sqlite3

BOOKING_STATUSES = ("confirmed", "canceled")

_STATUS_LIST = ", ".join(f"'{status}'" for status in BOOKING_STATUSES)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS movies (
        id               INTEGER PRIMARY KEY,
        title            TEXT    NOT NULL CHECK (length(trim(title)) > 0),
        genre            TEXT    NOT NULL CHECK (length(trim(genre)) > 0),
        duration_minutes INTEGER NOT NULL
                         CHECK (typeof(duration_minutes) = 'integer' AND duration_minutes > 0),
        age_rating       TEXT    NOT NULL CHECK (length(trim(age_rating)) > 0),
        description      TEXT    NOT NULL CHECK (length(trim(description)) > 0),
        ticket_price     INTEGER NOT NULL
                         CHECK (typeof(ticket_price) = 'integer' AND ticket_price >= 0),
        is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        UNIQUE (title)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS showtimes (
        id          INTEGER PRIMARY KEY,
        movie_id    INTEGER NOT NULL REFERENCES movies (id) ON DELETE RESTRICT,
        show_date   TEXT    NOT NULL CHECK (date(show_date) IS show_date),
        show_time   TEXT    NOT NULL CHECK (strftime('%H:%M', show_time) IS show_time),
        auditorium  TEXT    NOT NULL CHECK (length(trim(auditorium)) > 0),
        is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        UNIQUE (auditorium, show_date, show_time)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY,
        full_name     TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
        username      TEXT NOT NULL UNIQUE COLLATE NOCASE
                      CHECK (length(trim(username)) > 0),
        password_hash TEXT NOT NULL CHECK (length(password_hash) > 0),
        password_salt TEXT NOT NULL CHECK (length(password_salt) > 0),
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS bookings (
        id                INTEGER PRIMARY KEY,
        booking_reference TEXT    NOT NULL UNIQUE CHECK (length(trim(booking_reference)) > 0),
        user_id           INTEGER NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        showtime_id       INTEGER NOT NULL REFERENCES showtimes (id) ON DELETE RESTRICT,
        total_amount      INTEGER NOT NULL
                          CHECK (typeof(total_amount) = 'integer' AND total_amount >= 0),
        status            TEXT    NOT NULL DEFAULT 'confirmed' CHECK (status IN ({_STATUS_LIST})),
        created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
        UNIQUE (id, showtime_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS booked_seats (
        id           INTEGER PRIMARY KEY,
        booking_id   INTEGER NOT NULL,
        showtime_id  INTEGER NOT NULL REFERENCES showtimes (id) ON DELETE RESTRICT,
        seat_row     TEXT    NOT NULL CHECK (seat_row GLOB '[A-Z]'),
        seat_number  INTEGER NOT NULL
                     CHECK (typeof(seat_number) = 'integer' AND seat_number > 0),
        is_released  INTEGER NOT NULL DEFAULT 0 CHECK (is_released IN (0, 1)),
        FOREIGN KEY (booking_id, showtime_id)
            REFERENCES bookings (id, showtime_id) ON DELETE CASCADE,
        UNIQUE (booking_id, seat_row, seat_number)
    )
    """,
    # A seat may be held by at most one non-released booking per showtime.
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_booked_seats_active_seat
        ON booked_seats (showtime_id, seat_row, seat_number)
        WHERE is_released = 0
    """,
    "CREATE INDEX IF NOT EXISTS ix_showtimes_movie_date ON showtimes (movie_id, show_date, show_time)",
    "CREATE INDEX IF NOT EXISTS ix_bookings_user ON bookings (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_bookings_showtime ON bookings (showtime_id)",
    "CREATE INDEX IF NOT EXISTS ix_booked_seats_booking ON booked_seats (booking_id, showtime_id)",
)

REQUIRED_TABLES = ("movies", "showtimes", "users", "bookings", "booked_seats")

ROLE_CUSTOMER = "customer"
ROLE_ADMIN = "admin"
USER_ROLES = (ROLE_CUSTOMER, ROLE_ADMIN)
SCHEMA_VERSION = 2

# Additive column migrations, applied to new and existing databases alike, in order:
# (table, column, column definition, optional backfill statement). Each runs only if
# the column is missing, so it is safe on every launch and never rewrites a table.
COLUMN_MIGRATIONS: tuple[tuple[str, str, str, str | None], ...] = (
    # v2: role-based access. Existing accounts become customers via the default.
    ("users", "role",
     f"role TEXT NOT NULL DEFAULT '{ROLE_CUSTOMER}' "
     f"CHECK (role IN ({', '.join(repr(role) for role in USER_ROLES)}))",
     None),
    # v2: snapshot the movie title on each booking so later edits to a movie
    # never rewrite booking history or receipts.
    ("bookings", "movie_title",
     "movie_title TEXT CHECK (movie_title IS NULL OR length(trim(movie_title)) > 0)",
     """
     UPDATE bookings SET movie_title = (
         SELECT m.title FROM showtimes s JOIN movies m ON m.id = s.movie_id
         WHERE s.id = bookings.showtime_id
     ) WHERE movie_title IS NULL
     """),
)


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes that do not exist yet."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    # Table names come from the fixed migration list, not user input.
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Add any missing columns and backfill them. Returns ``table.column`` names added.

    Run inside a transaction (see ``initialize_database``) so a failed migration
    leaves the database exactly as it was.
    """
    applied = []
    for table, column, definition, backfill in COLUMN_MIGRATIONS:
        if column in column_names(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
        if backfill:
            conn.execute(backfill)
        applied.append(f"{table}.{column}")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return applied
