"""Tests for the default "genre field" posters' color logic. No windows are created."""

from __future__ import annotations

import unittest

from database.seed import SAMPLE_MOVIES
from ui import styles
from ui.posters import (
    CHIP_DARKEN,
    FALLBACK_COLORS,
    GENRE_COLORS,
    blend,
    genre_color,
    poster_initial,
)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2 contrast ratio between two ``#RRGGBB`` colors."""
    def luminance(color: str) -> float:
        channels = []
        for i in (1, 3, 5):
            value = int(color[i:i + 2], 16) / 255
            channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
        r, g, b = channels
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class GenreColorTests(unittest.TestCase):
    def test_sample_genres_get_distinct_named_colors(self) -> None:
        colors = {movie["genre"]: genre_color(movie["genre"]) for movie in SAMPLE_MOVIES}
        known = {color for _, color in GENRE_COLORS}
        self.assertTrue(all(color in known for color in colors.values()))
        self.assertEqual(len(set(colors.values())), len(colors), colors)

    def test_matching_is_case_insensitive_and_first_keyword_wins(self) -> None:
        self.assertEqual(genre_color("HORROR"), genre_color("horror"))
        self.assertEqual(genre_color("Sci-Fi Thriller"), genre_color("sci-fi"))
        self.assertNotEqual(genre_color("Sci-Fi Thriller"), genre_color("thriller"))

    def test_unknown_genres_get_a_stable_fallback(self) -> None:
        for genre in ("Western", "Musical", "Noir"):
            with self.subTest(genre=genre):
                self.assertIn(genre_color(genre), FALLBACK_COLORS)
                self.assertEqual(genre_color(genre), genre_color(f"  {genre.upper()} "))

    def test_poster_text_stays_readable_on_every_field(self) -> None:
        for color in {c for _, c in GENRE_COLORS} | set(FALLBACK_COLORS):
            with self.subTest(color=color):
                self.assertGreaterEqual(contrast_ratio(styles.PAPER, color), 4.5)
                chip = blend(color, "#000000", CHIP_DARKEN)
                self.assertGreaterEqual(contrast_ratio(styles.TEXT_PRIMARY, chip), 4.5)


class HelperTests(unittest.TestCase):
    def test_blend(self) -> None:
        self.assertEqual(blend("#000000", "#FFFFFF", 0), "#000000")
        self.assertEqual(blend("#000000", "#FFFFFF", 1), "#FFFFFF")
        self.assertEqual(blend("#000000", "#FFFFFF", 0.5), "#808080")
        self.assertEqual(blend("#3B1F24", "#3B1F24", 0.7), "#3B1F24")

    def test_poster_initial(self) -> None:
        self.assertEqual(poster_initial("neon monsoon"), "N")
        self.assertEqual(poster_initial("  'Orbitfall'"), "O")
        self.assertEqual(poster_initial("..."), "?")


if __name__ == "__main__":
    unittest.main()
