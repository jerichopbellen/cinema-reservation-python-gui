"""Fictional sample data for a fresh database.

Seeding runs at most once per database. After the first successful seed, a
marker row is written to ``app_meta``; later launches see the marker and skip
seeding entirely, so edits or removals made to sample records are never undone.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

SEED_MARKER_KEY = "sample_data_seeded_at"

# Prices are integer centavos (35000 == PHP 350.00). Ratings follow MTRCB labels.
SAMPLE_MOVIES: tuple[dict[str, object], ...] = (
    {
        "title": "The Last Lighthouse Keeper",
        "genre": "Drama",
        "duration_minutes": 118,
        "age_rating": "PG",
        "description": "A retired keeper on a remote Batanes island guards one final secret "
                       "as a storm closes in.",
        "ticket_price": 35000,
    },
    {
        "title": "Neon Monsoon",
        "genre": "Sci-Fi Thriller",
        "duration_minutes": 132,
        "age_rating": "R-13",
        "description": "In a flooded future Manila, a courier discovers the rain itself "
                       "is carrying stolen memories.",
        "ticket_price": 42000,
    },
    {
        "title": "Paper Kites Over Taal",
        "genre": "Family",
        "duration_minutes": 96,
        "age_rating": "G",
        "description": "Three siblings build a kite big enough to carry a message to "
                       "their father working overseas.",
        "ticket_price": 30000,
    },
    {
        "title": "Orbitfall",
        "genre": "Action",
        "duration_minutes": 141,
        "age_rating": "R-13",
        "description": "A salvage crew has ninety minutes to stop a derelict station from "
                       "crashing into the Pacific.",
        "ticket_price": 45000,
    },
    {
        "title": "The Quiet Archivist",
        "genre": "Mystery",
        "duration_minutes": 109,
        "age_rating": "PG",
        "description": "A library archivist finds a decades-old case file annotated in "
                       "her own handwriting.",
        "ticket_price": 35000,
    },
    {
        "title": "Midnight at Kalye Uno",
        "genre": "Horror",
        "duration_minutes": 101,
        "age_rating": "R-16",
        "description": "Every night at twelve, the last jeepney on Kalye Uno picks up a "
                       "passenger who is not alive.",
        "ticket_price": 38000,
    },
)

AUDITORIUMS = ("Cinema 1", "Cinema 2", "Cinema 3")
TIME_SLOTS = ("10:30", "13:45", "17:00", "20:15")
SHOWTIME_DAYS_AHEAD = (1, 2, 3)


def build_sample_showtimes(movie_count: int, today: dt.date) -> list[tuple[int, str, str, str]]:
    """Return ``(movie_index, show_date, show_time, auditorium)`` tuples.

    Each movie gets two screenings per day in a fixed auditorium. Slots are
    allocated so no auditorium is double-booked at the same date and time.
    """
    slots_per_movie = 2
    movies_per_auditorium = len(TIME_SLOTS) // slots_per_movie
    if movie_count > len(AUDITORIUMS) * movies_per_auditorium:
        raise ValueError("Not enough auditorium slots for the sample movies.")

    showtimes = []
    for days_ahead in SHOWTIME_DAYS_AHEAD:
        show_date = (today + dt.timedelta(days=days_ahead)).isoformat()
        for movie_index in range(movie_count):
            auditorium = AUDITORIUMS[movie_index % len(AUDITORIUMS)]
            first_slot = movie_index // len(AUDITORIUMS)
            for slot in (first_slot, first_slot + movies_per_auditorium):
                showtimes.append((movie_index, show_date, TIME_SLOTS[slot], auditorium))
    return showtimes


def is_seeded(conn: sqlite3.Connection) -> bool:
    """Return True if sample data has already been seeded into this database."""
    row = conn.execute("SELECT 1 FROM app_meta WHERE key = ?", (SEED_MARKER_KEY,)).fetchone()
    return row is not None


def seed_sample_data(conn: sqlite3.Connection, today: dt.date | None = None) -> bool:
    """Insert sample movies and showtimes once. Returns True if data was inserted.

    The caller is responsible for committing (``get_connection`` does this), so
    the movies, showtimes, and marker row are written in a single transaction.
    """
    if is_seeded(conn):
        return False

    today = today or dt.date.today()
    movie_ids = []
    for movie in SAMPLE_MOVIES:
        cursor = conn.execute(
            """
            INSERT INTO movies (title, genre, duration_minutes, age_rating, description, ticket_price)
            VALUES (:title, :genre, :duration_minutes, :age_rating, :description, :ticket_price)
            """,
            movie,
        )
        movie_ids.append(cursor.lastrowid)

    conn.executemany(
        "INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) VALUES (?, ?, ?, ?)",
        [
            (movie_ids[index], show_date, show_time, auditorium)
            for index, show_date, show_time, auditorium
            in build_sample_showtimes(len(movie_ids), today)
        ],
    )

    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?)",
        (SEED_MARKER_KEY, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
    )
    return True
