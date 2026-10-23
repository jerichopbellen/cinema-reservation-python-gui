"""Movie catalog and showtime selection screens."""

from __future__ import annotations

from tkinter import ttk
from typing import TYPE_CHECKING

from services.catalog_service import Movie, Showtime
from ui import styles
from ui.widgets import ScrollFrame, message_panel, screen_title, user_message_for
from utils.formatting import format_duration, format_peso, format_show_date, format_show_time

if TYPE_CHECKING:
    from ui.app import App

CATALOG_COLUMNS = 3


def movie_meta(movie: Movie) -> str:
    return f"{movie.genre}  ·  {format_duration(movie.duration_minutes)}"


class MoviesView(ttk.Frame):
    """Grid of active movies loaded from the database."""

    def __init__(self, master: ttk.Frame, app: App) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_MD))
        self.app = app

        screen_title(self, "Now Showing", "← Back to home", app.show_home).pack(fill="x")
        ttk.Label(self, text="Choose a movie to see its upcoming showtimes.",
                  style="Meta.TLabel").pack(anchor="w", pady=(0, styles.SPACE_MD))

        try:
            movies = app.catalog.list_active_movies()
        except Exception as exc:
            message_panel(self, "Movies could not be loaded", user_message_for(exc),
                          error=True).pack(fill="x")
            return
        if not movies:
            message_panel(self, "No movies are showing right now",
                          "Please check back later for new releases.").pack(fill="x")
            return

        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        for column in range(CATALOG_COLUMNS):
            scroll.body.columnconfigure(column, weight=1, uniform="movies")
        for index, movie in enumerate(movies):
            row, column = divmod(index, CATALOG_COLUMNS)
            self._movie_card(scroll.body, movie).grid(
                row=row, column=column, sticky="nsew",
                padx=(0 if column == 0 else styles.SPACE_MD, 0),
                pady=(0 if row == 0 else styles.SPACE_MD, 0),
            )

    def _movie_card(self, parent: ttk.Frame, movie: Movie) -> ttk.Frame:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=styles.SPACE_MD)

        footer = ttk.Frame(card, style="Panel.TFrame")
        footer.pack(side="bottom", fill="x", pady=(styles.SPACE_MD, 0))
        ttk.Label(footer, text=format_peso(movie.ticket_price), style="PanelPrice.TLabel").pack(side="left")
        ttk.Button(footer, text="Book Tickets", style="Accent.TButton", cursor="hand2",
                   command=lambda: self.app.show_showtimes(movie.id)).pack(side="right")

        ttk.Label(card, text=movie.title, style="PanelHeading.TLabel", wraplength=280,
                  justify="left").pack(anchor="w")
        meta = ttk.Frame(card, style="Panel.TFrame")
        meta.pack(anchor="w", pady=(styles.SPACE_XS, styles.SPACE_SM))
        ttk.Label(meta, text=movie.age_rating, style="PanelBadge.TLabel").pack(side="left")
        ttk.Label(meta, text=movie_meta(movie), style="PanelBody.TLabel").pack(
            side="left", padx=(styles.SPACE_SM, 0))
        ttk.Label(card, text=movie.description, style="PanelBody.TLabel", wraplength=280,
                  justify="left").pack(anchor="w")
        return card


class ShowtimesView(ttk.Frame):
    """Upcoming showtimes for one movie."""

    def __init__(self, master: ttk.Frame, app: App, movie_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_MD))
        self.app = app

        try:
            movie = app.catalog.get_active_movie(movie_id)
            showtimes = app.catalog.list_upcoming_showtimes(movie_id)
        except Exception as exc:
            screen_title(self, "Showtimes", "← Back to movies", app.show_movies).pack(fill="x")
            message_panel(self, "Showtimes could not be loaded", user_message_for(exc),
                          error=True).pack(fill="x", pady=(styles.SPACE_MD, 0))
            return

        screen_title(self, movie.title, "← Back to movies", app.show_movies).pack(fill="x")
        meta = ttk.Frame(self, style="App.TFrame")
        meta.pack(anchor="w")
        ttk.Label(meta, text=f"{movie.age_rating}  ·  {movie_meta(movie)}  ·  ",
                  style="Meta.TLabel").pack(side="left")
        ttk.Label(meta, text=f"{format_peso(movie.ticket_price)} per ticket",
                  style="Price.TLabel").pack(side="left")
        ttk.Label(self, text=movie.description, style="Meta.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(styles.SPACE_XS, styles.SPACE_MD))

        if not showtimes:
            message_panel(
                self, "No upcoming showtimes",
                "There are no upcoming screenings for this movie. Please check back later "
                "or choose another movie.",
            ).pack(fill="x")
            return

        ttk.Label(self, text="Choose a showtime", style="Heading.TLabel").pack(
            anchor="w", pady=(0, styles.SPACE_SM))
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        scroll.body.columnconfigure(0, weight=1)
        for index, showtime in enumerate(showtimes):
            self._showtime_row(scroll.body, index, movie, showtime)

    def _showtime_row(self, table: ttk.Frame, index: int, movie: Movie, showtime: Showtime) -> None:
        row = ttk.Frame(table, style="Panel.TFrame", padding=(styles.SPACE_MD, styles.SPACE_SM))
        row.grid(row=index, column=0, sticky="ew", pady=(0, styles.SPACE_XS))
        for column, weight in enumerate((3, 2, 2, 2, 0)):
            row.columnconfigure(column, weight=weight, uniform="showtime" if weight else "")

        cells = (
            (format_show_date(showtime.starts_at.date()), "PanelField.TLabel"),
            (format_show_time(showtime.starts_at), "PanelValue.TLabel"),
            (showtime.auditorium, "PanelBody.TLabel"),
            (format_peso(movie.ticket_price), "PanelPrice.TLabel"),
        )
        for column, (text, style) in enumerate(cells):
            ttk.Label(row, text=text, style=style).grid(row=0, column=column, sticky="w")
        ttk.Button(row, text="Select Seats", style="Accent.TButton", cursor="hand2",
                   command=lambda: self.app.show_seating(showtime.id)).grid(row=0, column=4, sticky="e")
