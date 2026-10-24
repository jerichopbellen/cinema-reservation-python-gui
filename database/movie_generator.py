"""Generate fictional movies and future showtimes for ``seed_movies.py``.

Every generated movie has a title and description that do not already exist in
the database (compared case-insensitively), and every generated showtime starts
after "now" and fits around the auditorium's existing active screenings, using
the same overlap rule as the admin screens (running time plus cleaning).

The functions here are pure apart from the ``rng`` they are given, so tests can
pass a seeded :class:`random.Random` and a fixed clock.
"""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
from dataclasses import dataclass

from database.seed import AUDITORIUMS
from services.catalog_service import SHOWTIME_KEY_FORMAT
from services.movie_admin_service import AGE_RATINGS
from services.showtime_admin_service import CLEANING_MINUTES

# Title parts. Patterns mix them so a few dozen words give thousands of titles.
_ADJECTIVES = (
    "Silent", "Crimson", "Hollow", "Last", "Burning", "Paper", "Glass", "Midnight", "Salt",
    "Forgotten", "Electric", "Golden", "Broken", "Northern", "Restless", "Velvet", "Iron",
    "Drifting", "Hidden", "Wild", "Distant", "Sleepless", "Painted", "Faded",
)
_NOUNS = (
    "Harbor", "Lantern", "Tide", "Archive", "Signal", "Orchard", "Ferry", "Monsoon", "Kite",
    "Compass", "Garden", "Frequency", "Lighthouse", "Carnival", "Market", "Bridge", "Island",
    "Station", "Letter", "Mirror", "Engine", "Shoreline", "Typhoon", "Rooftop",
)
_PLACES = (
    "Taal", "Batanes", "Quiapo", "Siargao", "Vigan", "Intramuros", "Bohol", "Palawan",
    "Sagada", "Binondo", "Iloilo", "Baguio", "Camiguin", "Dumaguete", "Marikina", "Escolta",
)
_TITLE_PATTERNS = (
    "The {adj} {noun}",
    "{noun} of {place}",
    "{adj} {noun} of {place}",
    "The {noun} at {place}",
    "{place} {noun}",
    "{adj} Over {place}",
    "Beyond the {adj} {noun}",
)

# Description parts: "<who> <what happens>, <stakes>."
_PROTAGONISTS = (
    "A retired ferry captain", "Two estranged sisters", "A night-shift nurse", "A teenage radio hacker",
    "A widowed baker", "A rookie coast guard", "A street magician", "A disgraced architect",
    "An overseas worker on leave", "A small-town mayor", "A jeepney driver", "A museum night guard",
    "A pair of rival chefs", "A college debate team", "A grieving cartographer", "A traveling choir",
)
_EVENTS = (
    "finds a map hidden inside a church bell", "receives letters dated thirty years in the future",
    "inherits a cinema that only plays films no one has made", "witnesses the sea pull back for a whole night",
    "is hired to guard a box no one may open", "hears a song on the radio that predicts the news",
    "wakes up in a town where it is always the same Sunday", "discovers a stranger wearing their face",
    "stumbles on a heist planned for the night of the fiesta", "loses a bet with a spirit of the mountain",
    "is stranded on an island that is not on any chart", "agrees to deliver one last package across the city",
)
_STAKES = (
    "and has until sunrise to set things right", "and must decide who to trust before the storm hits",
    "while a typhoon closes in on the coast", "and the whole barangay is watching",
    "but every answer costs a memory", "and the only way out is through their own past",
    "as an old rivalry catches up with them", "before the last boat leaves the harbor",
    "and learns the truth is stranger than the rumors", "with nothing but a borrowed camera and nerve",
)
_GENRES = (
    "Drama", "Comedy", "Romance", "Horror", "Mystery", "Action", "Sci-Fi", "Fantasy", "Thriller",
    "Family", "Adventure", "Musical",
)

# Screenings start on the quarter hour between these times.
FIRST_START = dt.time(9, 0)
LAST_START = dt.time(22, 0)
SLOT_MINUTES = 15
LEAD_MINUTES = 30  # earliest showtime is at least this far after "now"
MAX_ATTEMPTS = 500
MAX_SKIPPED_DAYS = 14  # full days the planner may pass over before giving up


class GenerationError(Exception):
    """Not enough unique titles, descriptions, or free auditorium time."""


@dataclass(frozen=True)
class GeneratedMovie:
    title: str
    genre: str
    duration_minutes: int
    age_rating: str
    description: str
    ticket_price: int  # centavos


@dataclass(frozen=True)
class PlannedShowtime:
    movie_index: int
    starts_at: dt.datetime
    auditorium: str


def generate_movies(count: int, rng: random.Random, taken_titles: set[str],
                    taken_descriptions: set[str]) -> list[GeneratedMovie]:
    """Return ``count`` movies whose titles and descriptions are all new.

    ``taken_*`` hold the lower-cased values already in the database; they are
    extended with the new ones so a batch never repeats itself either.
    """
    movies = []
    for _ in range(count):
        title = _unique(rng, taken_titles, lambda: rng.choice(_TITLE_PATTERNS).format(
            adj=rng.choice(_ADJECTIVES), noun=rng.choice(_NOUNS), place=rng.choice(_PLACES)), "title")
        description = _unique(rng, taken_descriptions, lambda: (
            f"{rng.choice(_PROTAGONISTS)} {rng.choice(_EVENTS)}, {rng.choice(_STAKES)}."), "description")
        movies.append(GeneratedMovie(
            title=title,
            genre=rng.choice(_GENRES),
            duration_minutes=rng.randrange(85, 161, 5),
            age_rating=rng.choice(AGE_RATINGS),
            description=description,
            ticket_price=rng.randrange(280, 481, 10) * 100,
        ))
    return movies


def _unique(rng: random.Random, taken: set[str], make, what: str) -> str:
    for _ in range(MAX_ATTEMPTS):
        candidate = make()
        if candidate.lower() not in taken:
            taken.add(candidate.lower())
            return candidate
    raise GenerationError(f"Could not find an unused {what}; the database already has most combinations.")


def candidate_starts(now: dt.datetime, days: int) -> list[list[dt.datetime]]:
    """Quarter-hour start times for the next ``days`` days that still have any, all after ``now``.

    Today counts only if it has a start time left at least ``LEAD_MINUTES`` from now.
    """
    earliest = now + dt.timedelta(minutes=LEAD_MINUTES)
    result: list[list[dt.datetime]] = []
    day = now.date()
    while len(result) < days:
        moment = dt.datetime.combine(day, FIRST_START)
        last = dt.datetime.combine(day, LAST_START)
        starts = []
        while moment <= last:
            if moment >= earliest:
                starts.append(moment)
            moment += dt.timedelta(minutes=SLOT_MINUTES)
        if starts:
            result.append(starts)
        day += dt.timedelta(days=1)
    return result


def plan_showtimes(movies: list[GeneratedMovie], per_day: int, days: int, now: dt.datetime,
                   rng: random.Random, existing: list[tuple[dt.datetime, int, str]],
                   taken_slots: set[tuple[str, str, str]]) -> list[PlannedShowtime]:
    """Pick ``per_day`` screenings per movie on each of ``days`` days, starting today.

    ``existing`` holds ``(starts_at, duration_minutes, auditorium)`` for active
    showtimes already scheduled; ``taken_slots`` holds every
    ``(auditorium, date, time)`` in the table, inactive ones included, because the
    table keeps those unique too. A movie's screenings on one day are at least
    its running time plus cleaning apart, so they never overlap each other either.

    A day without room for every movie is skipped (nothing is scheduled on it)
    and the next day is tried, up to ``MAX_SKIPPED_DAYS`` extra days.
    """
    gap = dt.timedelta(minutes=CLEANING_MINUTES)
    busy: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {auditorium: [] for auditorium in AUDITORIUMS}
    for starts_at, duration, auditorium in existing:
        if auditorium in busy:
            busy[auditorium].append((starts_at, starts_at + dt.timedelta(minutes=duration) + gap))

    plan: list[PlannedShowtime] = []
    planned_days = 0
    for day_starts in candidate_starts(now, days + MAX_SKIPPED_DAYS):
        day_plan = _plan_day(movies, per_day, day_starts, rng, busy, taken_slots)
        if day_plan is None:
            continue
        for show in day_plan:
            end = show.starts_at + dt.timedelta(minutes=movies[show.movie_index].duration_minutes) + gap
            busy[show.auditorium].append((show.starts_at, end))
            taken_slots.add((show.auditorium, show.starts_at.date().isoformat(),
                             show.starts_at.strftime("%H:%M")))
        plan.extend(day_plan)
        planned_days += 1
        if planned_days == days:
            plan.sort(key=lambda show: (show.starts_at, show.auditorium))
            return plan
    raise GenerationError(
        f"The cinemas are too full to fit {per_day} screening(s) a day of {len(movies)} movie(s) "
        f"on {days} day(s) within the next {days + MAX_SKIPPED_DAYS} days. "
        "Try fewer movies or fewer screenings per day.")


def _plan_day(movies: list[GeneratedMovie], per_day: int, day_starts: list[dt.datetime],
              rng: random.Random, busy: dict[str, list[tuple[dt.datetime, dt.datetime]]],
              taken_slots: set[tuple[str, str, str]]) -> list[PlannedShowtime] | None:
    """One day's screenings for every movie, or None if they do not all fit.

    Works on copies of ``busy`` and ``taken_slots``; the caller records the result.
    """
    gap = dt.timedelta(minutes=CLEANING_MINUTES)
    busy = {auditorium: intervals[:] for auditorium, intervals in busy.items()}
    taken = set(taken_slots)
    day_plan = []
    for index, movie in enumerate(movies):
        length = dt.timedelta(minutes=movie.duration_minutes)
        starts = day_starts[:]
        rng.shuffle(starts)
        chosen: list[dt.datetime] = []
        for starts_at in starts:
            if len(chosen) == per_day:
                break
            if any(abs(starts_at - other) < length + gap for other in chosen):
                continue
            end = starts_at + length + gap
            key = (starts_at.date().isoformat(), starts_at.strftime("%H:%M"))
            halls = list(AUDITORIUMS)
            rng.shuffle(halls)
            for auditorium in halls:
                if (auditorium, *key) in taken:
                    continue
                if all(not (starts_at < b_end and b_start < end) for b_start, b_end in busy[auditorium]):
                    busy[auditorium].append((starts_at, end))
                    taken.add((auditorium, *key))
                    chosen.append(starts_at)
                    day_plan.append(PlannedShowtime(index, starts_at, auditorium))
                    break
        if len(chosen) < per_day:
            return None
    return day_plan


def seed_generated(conn: sqlite3.Connection, count: int, per_day: int, days: int, now: dt.datetime,
                   rng: random.Random) -> tuple[list[GeneratedMovie], list[PlannedShowtime]]:
    """Generate and insert movies and showtimes using ``conn`` (the caller's transaction)."""
    titles = {row[0].lower() for row in conn.execute("SELECT title FROM movies")}
    descriptions = {row[0].lower() for row in conn.execute("SELECT description FROM movies")}
    existing = []
    taken_slots = set()
    for row in conn.execute(
        "SELECT s.show_date, s.show_time, s.auditorium, s.is_active, m.duration_minutes "
        "FROM showtimes s JOIN movies m ON m.id = s.movie_id"
    ):
        taken_slots.add((row[2], row[0], row[1]))
        if row[3]:
            starts_at = dt.datetime.strptime(f"{row[0]} {row[1]}", SHOWTIME_KEY_FORMAT)
            existing.append((starts_at, row[4], row[2]))

    movies = generate_movies(count, rng, titles, descriptions)
    plan = plan_showtimes(movies, per_day, days, now, rng, existing, taken_slots)

    movie_ids = []
    for movie in movies:
        cursor = conn.execute(
            "INSERT INTO movies (title, genre, duration_minutes, age_rating, description, ticket_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (movie.title, movie.genre, movie.duration_minutes, movie.age_rating, movie.description,
             movie.ticket_price),
        )
        movie_ids.append(cursor.lastrowid)
    conn.executemany(
        "INSERT INTO showtimes (movie_id, show_date, show_time, auditorium) VALUES (?, ?, ?, ?)",
        [(movie_ids[show.movie_index], show.starts_at.date().isoformat(), show.starts_at.strftime("%H:%M"),
          show.auditorium) for show in plan],
    )
    return movies, plan
