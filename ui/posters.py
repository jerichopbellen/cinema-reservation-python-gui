"""Default movie posters ("genre fields"), generated from the movie's own data.

Each genre gets a muted color field. The title's first letter is set huge and
faded in the background, cropped by the poster's edge; a small mono chip shows
the genre and rating; the title sits large at the bottom. Posters redraw
themselves whenever their size changes, so they can stretch with a grid.
"""

from __future__ import annotations

import tkinter as tk
import zlib

from services.catalog_service import Movie
from ui import styles

# Matched in order against the lowercased genre, so "Sci-Fi Thriller" is sci-fi.
GENRE_COLORS: tuple[tuple[str, str], ...] = (
    ("horror", "#3B1F24"),
    ("sci-fi", "#1E2B3D"),
    ("science fiction", "#1E2B3D"),
    ("family", "#22362B"),
    ("animation", "#22362B"),
    ("action", "#3D2716"),
    ("drama", "#2E2638"),
    ("mystery", "#1F3236"),
    ("thriller", "#2B2B3D"),
    ("romance", "#3D2233"),
    ("comedy", "#38351F"),
    ("documentary", "#2A2A2A"),
)
FALLBACK_COLORS = ("#2E2638", "#1F3236", "#3D2716", "#22362B", "#1E2B3D", "#3B1F24")
LETTER_STRENGTH = 0.16  # how far the background letter is blended toward white
CHIP_DARKEN = 0.35


def genre_color(genre: str) -> str:
    """The field color for a genre; unknown genres get a stable color from the fallback set."""
    key = genre.strip().lower()
    for keyword, color in GENRE_COLORS:
        if keyword in key:
            return color
    return FALLBACK_COLORS[zlib.crc32(key.encode("utf-8")) % len(FALLBACK_COLORS)]


def blend(color: str, toward: str, amount: float) -> str:
    """Mix two ``#RRGGBB`` colors; ``amount`` 0 keeps ``color``, 1 gives ``toward``."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(toward[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(a, b))


def poster_initial(title: str) -> str:
    return next((ch.upper() for ch in title if ch.isalnum()), "?")


class GenrePoster(tk.Canvas):
    """A poster canvas for one movie. ``width`` is a minimum when packed with fill."""

    def __init__(self, master: tk.Misc, movie: Movie, *, width: int, height: int,
                 title_size: int = 18) -> None:
        self.field = genre_color(movie.genre)
        super().__init__(master, width=width, height=height, background=self.field,
                         highlightthickness=0, borderwidth=0)
        self.movie = movie
        self.title_size = title_size
        self.bind("<Configure>", lambda _event: self.redraw())
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), int(self["width"]))
        height = max(self.winfo_height(), int(self["height"]))
        pad = 14

        # Huge faded initial, cropped by the bottom-right edge.
        self.create_text(width + height * 0.06, height + height * 0.30, anchor="se",
                         text=poster_initial(self.movie.title),
                         fill=blend(self.field, styles.PAPER, LETTER_STRENGTH),
                         font=(styles.FONT_DISPLAY[0], -int(height * 1.45), "bold"))

        # Shorten the chip until it fits: full genre, then its first word, then the rating alone.
        genre = self.movie.genre.upper()
        for text in (f"{genre} · {self.movie.age_rating}",
                     f"{genre.split()[0]} · {self.movie.age_rating}" if genre.split() else "",
                     self.movie.age_rating):
            if not text:
                continue
            chip = self.create_text(pad + 7, pad + 3, anchor="nw", text=text,
                                    fill=styles.TEXT_PRIMARY, font=styles.FONT_EYEBROW)
            x1, y1, x2, y2 = self.bbox(chip)
            if x2 + 7 <= width - pad:
                break
            self.delete(chip)
        backing = self.create_rectangle(x1 - 7, y1 - 3, x2 + 7, y2 + 3, width=0,
                                        fill=blend(self.field, "#000000", CHIP_DARKEN))
        self.tag_lower(backing, chip)

        self.create_text(pad, height - pad, anchor="sw", width=width - 2 * pad,
                         text=self.movie.title.upper(), fill=styles.PAPER,
                         font=(styles.FONT_DISPLAY[0], -self.title_size - 4, "bold"))
