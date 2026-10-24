"""Tests for seed_movies.py. Temporary databases only; no windows."""

from __future__ import annotations

import datetime as dt
import io
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import seed_movies
from database.connection import DEFAULT_DB_PATH, connect
from database.movie_generator import candidate_starts
from services.catalog_service import SHOWTIME_KEY_FORMAT
from services.movie_admin_service import validate_movie
from services.showtime_admin_service import CLEANING_MINUTES
from tests.helpers import START_CLOCK, create_seeded_database
from utils.formatting import format_peso

NOW = START_CLOCK  # 2030-01-02 12:00, in the middle of the sample schedule (Jan 2–4)
QUIET_NOW = dt.datetime(2030, 1, 10, 12, 0)  # after the sample schedule, so the cinemas are empty


class SeedMoviesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "seed.db"
        self.assertNotEqual(self.db_path.resolve(), DEFAULT_DB_PATH.resolve())
        create_seeded_database(self.db_path)
        self.conn = connect(self.db_path)
        self.addCleanup(self.conn.close)

    def seed(self, *args: str, answer: str = "yes", now: dt.datetime = NOW, seed: int = 7) -> tuple[int, str]:
        out = io.StringIO()
        code = seed_movies.run([*args, "--db", str(self.db_path)], input_fn=lambda _prompt: answer,
                               out=out, now=lambda: now, rng=random.Random(seed))
        return code, out.getvalue()

    def movies(self) -> list[tuple[str, str]]:
        return self.conn.execute("SELECT title, description FROM movies").fetchall()

    def showtimes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT s.movie_id, s.show_date, s.show_time, s.auditorium, s.is_active, m.duration_minutes "
            "FROM showtimes s JOIN movies m ON m.id = s.movie_id").fetchall()
        return [{"movie_id": r[0], "start": dt.datetime.strptime(f"{r[1]} {r[2]}", SHOWTIME_KEY_FORMAT),
                 "auditorium": r[3], "active": r[4], "minutes": r[5]} for r in rows]

    def new_movie_ids(self, before: int) -> list[int]:
        return [r[0] for r in self.conn.execute("SELECT id FROM movies ORDER BY id").fetchall()[before:]]


class SeedMoviesTests(SeedMoviesTestCase):
    def test_adds_requested_movies_and_showtimes(self) -> None:
        before_movies, before_shows = len(self.movies()), len(self.showtimes())
        code, output = self.seed("--movies", "4", "--days", "3", "--per-day", "2")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(self.movies()), before_movies + 4)
        self.assertEqual(len(self.showtimes()), before_shows + 4 * 3 * 2)
        self.assertIn("Added 4 movies and 24 showtimes.", output)

    def test_every_new_showtime_starts_after_the_moment_of_seeding(self) -> None:
        for now in (NOW, dt.datetime(2030, 1, 2, 21, 50), dt.datetime(2030, 1, 2, 23, 40)):
            with self.subTest(now=now):
                before = len(self.movies())
                self.assertEqual(self.seed("--movies", "2", now=now)[0], 0)
                new_ids = set(self.new_movie_ids(before))
                starts = [s["start"] for s in self.showtimes() if s["movie_id"] in new_ids]
                self.assertTrue(starts)
                self.assertTrue(all(start > now for start in starts))

    def test_today_counts_when_it_still_has_time_left(self) -> None:
        before = len(self.movies())
        self.seed("--movies", "1", "--days", "1", now=QUIET_NOW)
        new_ids = set(self.new_movie_ids(before))
        days = {s["start"].date() for s in self.showtimes() if s["movie_id"] in new_ids}
        self.assertEqual(days, {QUIET_NOW.date()})

    def test_late_at_night_the_database_gets_tomorrows_showtimes(self) -> None:
        late = dt.datetime(2030, 1, 10, 23, 0)
        before = len(self.movies())
        self.assertEqual(self.seed("--movies", "1", "--days", "1", now=late)[0], 0)
        new_ids = set(self.new_movie_ids(before))
        days = {s["start"].date() for s in self.showtimes() if s["movie_id"] in new_ids}
        self.assertEqual(days, {dt.date(2030, 1, 11)})

    def test_a_full_day_is_skipped_for_the_next_one_with_room(self) -> None:
        # The sample schedule leaves too little room on Jan 2 for five more movies twice each.
        before = len(self.movies())
        self.assertEqual(self.seed("--movies", "5", "--days", "2", "--per-day", "2")[0], 0)
        new_ids = set(self.new_movie_ids(before))
        by_day: dict[dt.date, int] = {}
        for show in self.showtimes():
            if show["movie_id"] in new_ids:
                by_day[show["start"].date()] = by_day.get(show["start"].date(), 0) + 1
        self.assertEqual(sorted(by_day.values()), [10, 10], by_day)  # two whole days, nothing partial

    def test_late_at_night_the_schedule_starts_tomorrow(self) -> None:
        late = dt.datetime(2030, 1, 2, 23, 0)
        self.assertEqual([day[0].date() for day in candidate_starts(late, 2)],
                         [dt.date(2030, 1, 3), dt.date(2030, 1, 4)])

    def test_titles_and_descriptions_are_unique_across_runs(self) -> None:
        for _ in range(5):
            # The same random seed every time: uniqueness must come from checking the database.
            self.assertEqual(self.seed("--movies", "6", "--days", "1", "--per-day", "1", seed=1)[0], 0)
        titles = [title.lower() for title, _ in self.movies()]
        descriptions = [description.lower() for _, description in self.movies()]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(descriptions), len(set(descriptions)))

    def test_no_screenings_overlap_in_any_cinema_including_cleaning(self) -> None:
        for _ in range(3):
            self.assertEqual(self.seed("--movies", "5", "--days", "3", "--per-day", "2",
                                       seed=random.randrange(10_000))[0], 0)
        gap = dt.timedelta(minutes=CLEANING_MINUTES)
        active = [s for s in self.showtimes() if s["active"]]
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if a["auditorium"] != b["auditorium"]:
                    continue
                a_end = a["start"] + dt.timedelta(minutes=a["minutes"]) + gap
                b_end = b["start"] + dt.timedelta(minutes=b["minutes"]) + gap
                self.assertFalse(a["start"] < b_end and b["start"] < a_end, (a, b))

    def test_a_movies_own_screenings_never_overlap(self) -> None:
        before = len(self.movies())
        self.seed("--movies", "3", "--days", "2", "--per-day", "4")
        for movie_id in self.new_movie_ids(before):
            shows = sorted((s for s in self.showtimes() if s["movie_id"] == movie_id), key=lambda s: s["start"])
            for first, second in zip(shows, shows[1:]):
                self.assertGreaterEqual(second["start"] - first["start"],
                                        dt.timedelta(minutes=first["minutes"] + CLEANING_MINUTES))

    def test_generated_movies_pass_the_admin_form_validation(self) -> None:
        before = len(self.movies())
        self.seed("--movies", "10", "--days", "1", "--per-day", "1")
        for movie_id in self.new_movie_ids(before):
            row = self.conn.execute("SELECT title, genre, duration_minutes, age_rating, description, "
                                    "ticket_price FROM movies WHERE id = ?", (movie_id,)).fetchone()
            draft = validate_movie(row[0], row[1], str(row[2]), row[3], row[4], format_peso(row[5]))
            self.assertEqual((draft.title, draft.duration_minutes, draft.ticket_price), (row[0], row[2], row[5]))

    def test_cancelling_changes_nothing(self) -> None:
        before = (len(self.movies()), len(self.showtimes()))
        code, output = self.seed(answer="no")
        self.assertEqual(code, 1)
        self.assertIn("No changes were made", output)
        self.assertEqual((len(self.movies()), len(self.showtimes())), before)

    def test_yes_flag_skips_the_prompt(self) -> None:
        def refuse(_prompt: str) -> str:
            raise AssertionError("should not ask")
        out = io.StringIO()
        code = seed_movies.run(["--yes", "--movies", "1", "--db", str(self.db_path)], input_fn=refuse,
                               out=out, now=lambda: NOW, rng=random.Random(3))
        self.assertEqual(code, 0, out.getvalue())

    def test_when_the_cinemas_are_full_nothing_is_added(self) -> None:
        before = (len(self.movies()), len(self.showtimes()))
        code, output = self.seed("--movies", "20", "--days", "1", "--per-day", "4")
        self.assertEqual(code, 2)
        self.assertIn("too full", output)
        self.assertEqual((len(self.movies()), len(self.showtimes())), before)

    def test_rejects_out_of_range_options(self) -> None:
        for args in (["--movies", "0"], ["--days", "15"], ["--per-day", "x"]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                with mock.patch("sys.stderr", io.StringIO()):
                    self.seed(*args)


if __name__ == "__main__":
    unittest.main()
