"""Movie catalog and showtime selection screens."""

from __future__ import annotations

from itertools import groupby
from tkinter import ttk
from typing import TYPE_CHECKING

from services.catalog_service import Movie, Showtime
from ui import styles
from ui.posters import GenrePoster
from ui.widgets import (
    EXPECTED_ERRORS,
    ScrollFrame,
    message_panel,
    screen_title,
    user_message_for,
    wrap_to_container,
)
from utils.formatting import format_duration, format_peso, format_show_date, format_show_time

if TYPE_CHECKING:
    from ui.app import App

CATALOG_COLUMNS = 3
TILE_COLUMNS = 4


def movie_meta(movie: Movie) -> str:
    return f"{movie.genre}  ·  {format_duration(movie.duration_minutes)}"


class MoviesView(ttk.Frame):
    """Grid of active movies loaded from the database."""

    def __init__(self, master: ttk.Frame, app: App) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app

        screen_title(self, "Now Showing", eyebrow="Movies",
                     subtitle="Choose a movie to see its upcoming showtimes.").pack(
            fill="x", pady=(0, styles.SPACE_LG))

        try:
            movies = app.catalog.list_active_movies()
        except EXPECTED_ERRORS as exc:
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
        card = ttk.Frame(parent, style="Panel.TFrame")
        # The poster stretches to the card width and redraws itself at the new size.
        GenrePoster(card, movie, width=260, height=160).pack(fill="x")

        body = ttk.Frame(card, style="Panel.TFrame", padding=styles.SPACE_MD)
        body.pack(fill="both", expand=True)
        footer = ttk.Frame(body, style="Panel.TFrame")
        footer.pack(side="bottom", fill="x", pady=(styles.SPACE_MD, 0))
        ttk.Label(footer, text=format_peso(movie.ticket_price), style="PanelPrice.TLabel").pack(
            side="left")
        ttk.Button(footer, text="Book Tickets", style="Accent.TButton", cursor="hand2",
                   command=lambda: self.app.show_showtimes(movie.id)).pack(side="right")

        ttk.Label(body, text=movie_meta(movie).upper(), style="PanelEyebrow.TLabel").pack(anchor="w")
        title = ttk.Label(body, text=movie.title, style="PanelHeading.TLabel", wraplength=260,
                          justify="left")
        title.pack(anchor="w", pady=(2, styles.SPACE_XS))
        description = ttk.Label(body, text=movie.description, style="PanelBody.TLabel",
                                wraplength=260, justify="left")
        description.pack(anchor="w")
        for label in (title, description):
            wrap_to_container(label, body, margin=2 * styles.SPACE_MD)
        return card


class ShowtimesView(ttk.Frame):
    """Upcoming showtimes for one movie, grouped by date."""

    def __init__(self, master: ttk.Frame, app: App, movie_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app

        try:
            movie = app.catalog.get_active_movie(movie_id)
            showtimes = app.catalog.list_upcoming_showtimes(movie_id)
        except EXPECTED_ERRORS as exc:
            screen_title(self, "Showtimes", "← Back to movies", app.show_movies).pack(fill="x")
            message_panel(self, "Showtimes could not be loaded", user_message_for(exc),
                          error=True).pack(fill="x", pady=(styles.SPACE_MD, 0))
            return

        selection = app.session.seat_selection
        if selection is not None and selection.movie.id != movie.id:
            app.session.clear_booking_state()  # seats picked for another movie are stale

        ttk.Button(self, text="← Back to movies", style="AppLink.TButton", cursor="hand2",
                   command=app.show_movies).pack(anchor="w", pady=(0, styles.SPACE_MD))
        hero = ttk.Frame(self, style="App.TFrame")
        hero.pack(fill="x", pady=(0, styles.SPACE_LG))
        GenrePoster(hero, movie, width=150, height=220, title_size=14).pack(side="left", anchor="n")
        info = ttk.Frame(hero, style="App.TFrame")
        info.pack(side="left", fill="both", expand=True, padx=(styles.SPACE_LG, 0))
        ttk.Label(info, text=f"{movie.age_rating}  ·  {movie_meta(movie)}".upper(),
                  style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(info, text=movie.title, style="Display.TLabel", wraplength=760,
                  justify="left").pack(anchor="w")
        ttk.Label(info, text=movie.description, style="Meta.TLabel", wraplength=700,
                  justify="left").pack(anchor="w", pady=(styles.SPACE_XS, styles.SPACE_MD))
        ttk.Label(info, text=f"{format_peso(movie.ticket_price)} per ticket",
                  style="Price.TLabel").pack(anchor="w")

        if not showtimes:
            message_panel(
                self, "No upcoming showtimes",
                "There are no upcoming screenings for this movie. Please check back later "
                "or choose another movie.",
            ).pack(fill="x")
            return

        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        for column in range(TILE_COLUMNS):
            scroll.body.columnconfigure(column, weight=1, uniform="tiles")
        row = 0
        for show_date, group in groupby(showtimes, key=lambda s: s.starts_at.date()):
            ttk.Label(scroll.body, text=format_show_date(show_date).upper(), style="Eyebrow.TLabel").grid(
                row=row, column=0, columnspan=TILE_COLUMNS, sticky="w",
                pady=(0 if row == 0 else styles.SPACE_MD, styles.SPACE_SM))
            row += 1
            for column, showtime in enumerate(group):
                self._showtime_tile(scroll.body, movie, showtime).grid(
                    row=row + column // TILE_COLUMNS, column=column % TILE_COLUMNS, sticky="ew",
                    padx=(0 if column % TILE_COLUMNS == 0 else styles.SPACE_SM, 0),
                    pady=(0, styles.SPACE_SM))
            row += 1 + column // TILE_COLUMNS

    def _showtime_tile(self, parent: ttk.Frame, movie: Movie, showtime: Showtime) -> ttk.Button:
        """One clickable tile per showtime: time, auditorium, and price."""
        return ttk.Button(
            parent, style="Showtime.TButton", cursor="hand2",
            text=f"{format_show_time(showtime.starts_at)}\n{showtime.auditorium}  ·  "
                 f"{format_peso(movie.ticket_price)}",
            command=lambda: self.app.show_seating(showtime.id),
        )
