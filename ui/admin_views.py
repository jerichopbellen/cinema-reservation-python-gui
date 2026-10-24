"""Administrator screens: movie management, the add/edit movie form, showtimes, and
each showtime's confirmed bookings.

These screens are only reachable through ``App._show_admin``, but they do not
rely on that: every action goes through
:class:`~services.movie_admin_service.MovieAdminService`, which re-checks the
signed-in user's role in the database before doing anything.
"""

from __future__ import annotations

import datetime as dt
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from database.seed import AUDITORIUMS
from services.auth_service import AuthorizationError, User
from services.movie_admin_service import (
    AGE_RATINGS,
    AdminMovie,
    MovieNotFoundError,
    validate_movie,
)
from services.showtime_admin_service import (
    CLEANING_MINUTES,
    AdminShowtime,
    ShowtimeBooking,
    ShowtimeNotFoundError,
)
from ui import styles
from ui.widgets import (
    EXPECTED_ERRORS,
    Form,
    FormField,
    ScrollFrame,
    StatusMessage,
    Table,
    message_panel,
    run_in_background,
    screen_title,
    user_message_for,
)
from utils.formatting import (
    format_duration,
    format_local_datetime,
    format_peso,
    format_show_date,
    format_show_time,
    format_showtime,
)

if TYPE_CHECKING:
    from ui.app import App

LINK_WIDTH = 7  # characters, so Delete/Archive/Restore line up across rows

# (header, stretches): columns size to their widest cell; the stretching one takes the rest.
MOVIE_COLUMNS = [("TITLE", True), ("PRICE", False), ("STATUS", False),
                 ("", False)]
# The spare width is shared equally by the data columns, so every gap between columns
# (including the one before the actions) is the same.
SHOWTIME_COLUMNS = [("DATE", True), ("TIME", True), ("CINEMA", True), ("BOOKINGS", True),
                    ("STATUS", True), ("", False)]
BOOKING_COLUMNS = [("REFERENCE", False), ("CUSTOMER", False), ("SEATS", True), ("TOTAL", False),
                   ("BOOKED", False)]


def price_text(centavos: int) -> str:
    """Centavos as plain form text, e.g. ``35050 -> "350.50"``."""
    return f"{centavos // 100}.{centavos % 100:02d}"


def handle_admin_error(app: App, exc: Exception) -> bool:
    """Route errors every admin screen treats the same way. Returns True if handled."""
    if isinstance(exc, AuthorizationError):
        app.toast(str(exc), error=True)
        app.show_home()
        return True
    if isinstance(exc, MovieNotFoundError):
        app.toast(str(exc), error=True)
        app.show_admin_movies()
        return True
    return False


class AdminMoviesView(ttk.Frame):
    """All movies, active and archived, with add, edit, archive/delete, and restore."""

    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user = user

        top = ttk.Frame(self, style="App.TFrame")
        top.pack(fill="x", pady=(0, styles.SPACE_LG))
        ttk.Button(top, text="+  Add Movie", style="Accent.TButton", cursor="hand2",
                   command=lambda: app.show_movie_form()).pack(side="right", anchor="s")
        screen_title(top, "Manage movies", eyebrow="Admin",
                     subtitle="Movies with showtimes or bookings are archived instead of deleted, "
                              "so booking history is never lost.").pack(side="left", fill="x", expand=True,
                                                                         padx=(0, styles.SPACE_LG))

        try:
            movies = app.movie_admin.list_movies(user.id)
        except EXPECTED_ERRORS as exc:
            if not handle_admin_error(app, exc):
                message_panel(self, "Movies could not be loaded", user_message_for(exc),
                              error=True).pack(fill="x")
            return
        if not movies:
            box = message_panel(self, "No movies yet",
                                "Add your first movie to make it available in the customer catalog.")
            box.pack(fill="x")
            return

        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        table = Table(scroll.body, MOVIE_COLUMNS)
        table.pack(fill="x")
        for movie in movies:
            self._add_movie_row(table, movie)

    def _add_movie_row(self, table: Table, movie: AdminMovie) -> None:
        def title_cell(parent: Table):
            cell = ttk.Frame(parent, style="Panel.TFrame")
            details = f"{movie.genre}  ·  {format_duration(movie.duration_minutes)}  ·  {movie.age_rating}".upper()
            for text, style in ((movie.title, "PanelField.TLabel"), (details, "PanelEyebrow.TLabel")):
                parent.wrap(ttk.Label(cell, text=text, style=style, justify="left"), 0).pack(anchor="w")
            return cell

        def actions_cell(parent):
            cell = ttk.Frame(parent, style="Panel.TFrame")
            ttk.Button(cell, text="Showtimes", style="Compact.TButton", cursor="hand2",
                       command=lambda: self.app.show_admin_showtimes(movie.id)).pack(side="left")
            ttk.Button(cell, text="Edit", style="Compact.TButton", cursor="hand2",
                       command=lambda: self.app.show_movie_form(movie.id)).pack(
                side="left", padx=(styles.SPACE_SM, 0))
            if movie.is_active:
                text, command = ("Delete" if movie.can_delete else "Archive"), lambda: self._remove(movie)
            else:
                text, command = "Restore", lambda: self._restore(movie)
            ttk.Button(cell, text=text, style="Link.TButton", cursor="hand2", width=LINK_WIDTH,
                       command=command).pack(side="left", padx=(styles.SPACE_MD, 0))
            return cell

        table.add_row([
            title_cell,
            lambda parent: ttk.Label(parent, text=format_peso(movie.ticket_price), style="PanelPrice.TLabel"),
            lambda parent: ttk.Label(parent, text="ACTIVE" if movie.is_active else "ARCHIVED",
                                     style="BadgeUpcoming.TLabel" if movie.is_active else "BadgeCompleted.TLabel"),
            actions_cell,
        ], sticky=("w", "w", "w", "e"))

    def _remove(self, movie: AdminMovie) -> None:
        if movie.can_delete:
            title, question = "Delete movie", (
                f"Permanently delete “{movie.title}”?\n\nIt has no showtimes or bookings, so no "
                "history will be lost. This cannot be undone.")
        else:
            title, question = "Archive movie", (
                f"Archive “{movie.title}”?\n\nIt has {movie.showtime_count} showtime(s) and "
                f"{movie.booking_count} booking(s), so it will be archived instead of deleted: hidden "
                "from customers and closed to new bookings. Existing bookings and receipts are kept, "
                "and you can restore it later.")
        if not messagebox.askyesno(title, question, icon="warning", parent=self):
            return
        try:
            outcome = self.app.movie_admin.remove_movie(self.user.id, movie.id)
        except EXPECTED_ERRORS as exc:
            if not handle_admin_error(self.app, exc):
                messagebox.showerror(f"{title} failed", user_message_for(exc), parent=self)
            return
        self.app.show_admin_movies()
        self.app.toast(f"“{movie.title}” was {outcome}."
                       + ("" if outcome == "deleted" else " Its booking history was kept."))

    def _restore(self, movie: AdminMovie) -> None:
        try:
            self.app.movie_admin.restore_movie(self.user.id, movie.id)
        except EXPECTED_ERRORS as exc:
            if not handle_admin_error(self.app, exc):
                messagebox.showerror("Restore failed", user_message_for(exc), parent=self)
            return
        self.app.show_admin_movies()
        self.app.toast(f"“{movie.title}” is back in the customer catalog.")


class MovieFormView(ttk.Frame):
    """Add a movie (``movie_id`` is None) or edit an existing one."""

    def __init__(self, master: ttk.Frame, app: App, user: User, movie_id: int | None = None) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user = user
        self.movie_id = movie_id
        editing = movie_id is not None

        screen_title(self, "Edit movie" if editing else "Add movie", "← Back to movie list",
                     app.show_admin_movies, eyebrow="Admin").pack(fill="x", pady=(0, styles.SPACE_LG))

        movie: AdminMovie | None = None
        if editing:
            try:
                movie = app.movie_admin.get_movie(user.id, movie_id)
            except EXPECTED_ERRORS as exc:
                if not handle_admin_error(app, exc):
                    message_panel(self, "Movie could not be loaded", user_message_for(exc),
                                  error=True).pack(fill="x")
                return

        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        card = ttk.Frame(scroll.body, style="Panel.TFrame", padding=styles.SPACE_LG)
        card.pack(fill="x")
        if movie is not None and not movie.is_active:
            ttk.Label(card, text="This movie is archived: customers cannot see or book it until it "
                                 "is restored from the movie list.", style="PanelFailure.TLabel",
                      wraplength=760, justify="left").pack(anchor="w", pady=(0, styles.SPACE_MD))

        grid = ttk.Frame(card, style="Panel.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure((0, 1, 2), weight=1, uniform="movie")
        price_hint = "In pesos, for example 350 or 350.50."
        if editing:
            price_hint += " A new price applies to future bookings only."
        fields = {
            "title": FormField(grid, "Title", width=60),
            "genre": FormField(grid, "Genre", hint="For example Drama or Sci-Fi Thriller.", width=24),
            "age_rating": FormField(grid, "Age rating", choices=AGE_RATINGS, width=10),
            "duration_minutes": FormField(grid, "Running time (minutes)", width=10),
            "ticket_price": FormField(grid, "Ticket price (₱)", hint=price_hint, width=12),
            "description": FormField(grid, "Description", lines=3, width=60,
                                     hint="A one- or two-sentence synopsis shown in the catalog."),
        }
        layout = (("title", 0, 0, 2), ("age_rating", 0, 2, 1), ("genre", 1, 0, 1),
                  ("duration_minutes", 1, 1, 1), ("ticket_price", 1, 2, 1), ("description", 2, 0, 3))
        for name, row, column, span in layout:
            fields[name].grid(row=row, column=column, columnspan=span, sticky="new",
                              padx=(0 if column == 0 else styles.SPACE_MD, 0), pady=(0, styles.SPACE_MD))

        if movie is not None:
            for name, value in (("title", movie.title), ("genre", movie.genre),
                                ("age_rating", movie.age_rating),
                                ("duration_minutes", str(movie.duration_minutes)),
                                ("ticket_price", price_text(movie.ticket_price)),
                                ("description", movie.description)):
                fields[name].set(value)

        actions = ttk.Frame(card, style="Panel.TFrame")
        actions.pack(fill="x")
        button = ttk.Button(actions, text="Save changes" if editing else "Add movie",
                            style="Accent.TButton", cursor="hand2")
        button.pack(side="left")
        ttk.Button(actions, text="Cancel", style="Secondary.TButton", cursor="hand2",
                   command=app.show_admin_movies).pack(side="left", padx=(styles.SPACE_SM, 0))
        status = StatusMessage(actions, wraplength=480)
        status.pack(side="left", padx=(styles.SPACE_MD, 0))

        self.form = Form(fields, status, button, busy_text="Saving…")
        self.form.bind_submit(self._save)
        fields["title"].entry.focus_set()

    def _save(self) -> None:
        if not self.form.begin():
            return
        values = self.form.values()
        admin_id, movie_id = self.user.id, self.movie_id

        def task() -> AdminMovie:
            draft = validate_movie(values["title"], values["genre"], values["duration_minutes"],
                                   values["age_rating"], values["description"], values["ticket_price"])
            if movie_id is None:
                return self.app.movie_admin.create_movie(admin_id, draft)
            return self.app.movie_admin.update_movie(admin_id, movie_id, draft)

        run_in_background(self, task, self._on_saved, self._on_error)

    def _on_saved(self, movie: AdminMovie) -> None:
        self.app.show_admin_movies()
        verb = "added" if self.movie_id is None else "updated"
        self.app.toast(f"“{movie.title}” was {verb}.")

    def _on_error(self, exc: Exception) -> None:
        self.form.end()
        if not handle_admin_error(self.app, exc):
            self.form.show_error(exc)


class AdminShowtimesView(ttk.Frame):
    """A movie's showtimes: add new screenings, and delete, deactivate, or restore existing ones."""

    def __init__(self, master: ttk.Frame, app: App, user: User, movie_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user = user
        self.movie_id = movie_id

        try:
            movie = app.movie_admin.get_movie(user.id, movie_id)
            showtimes = app.showtime_admin.list_showtimes(user.id, movie_id)
        except EXPECTED_ERRORS as exc:
            screen_title(self, "Showtimes", "← Back to movie list", app.show_admin_movies,
                         eyebrow="Admin").pack(fill="x", pady=(0, styles.SPACE_LG))
            if not handle_admin_error(app, exc):
                message_panel(self, "Showtimes could not be loaded", user_message_for(exc),
                              error=True).pack(fill="x")
            return
        self.movie = movie

        screen_title(self, "Showtimes", "← Back to movie list", app.show_admin_movies,
                     eyebrow=f"Admin  ·  {movie.title}",
                     subtitle=f"{format_duration(movie.duration_minutes)} running time. Each screening blocks "
                              f"its cinema for the running time plus {CLEANING_MINUTES} minutes of cleaning."
                     ).pack(fill="x", pady=(0, styles.SPACE_LG))

        if movie.is_active:
            self._build_add_form()
        else:
            message_panel(self, "This movie is archived",
                          "Restore it from the movie list before adding showtimes.").pack(fill="x")

        if not showtimes:
            message_panel(self, "No showtimes yet",
                          "Add a showtime above to make this movie bookable.").pack(
                fill="x", pady=(styles.SPACE_MD, 0))
            return
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True, pady=(styles.SPACE_LG, 0))
        table = Table(scroll.body, SHOWTIME_COLUMNS)
        table.pack(fill="x")
        now = app.catalog.now()
        for showtime in showtimes:
            self._add_showtime_row(table, showtime, now)

    def _build_add_form(self) -> None:
        card = ttk.Frame(self, style="Panel.TFrame", padding=styles.SPACE_LG)
        card.pack(fill="x")
        ttk.Label(card, text="ADD SHOWTIME", style="PanelEyebrow.TLabel").pack(anchor="w",
                                                                           pady=(0, styles.SPACE_SM))
        row = ttk.Frame(card, style="Panel.TFrame")
        row.pack(fill="x")
        row.columnconfigure((0, 1, 2), weight=1, uniform="add")
        fields = {
            "show_date": FormField(row, "Date", hint="YYYY-MM-DD", width=14),
            "show_time": FormField(row, "Start time", hint="24-hour, e.g. 19:30", width=10),
            "auditorium": FormField(row, "Cinema", choices=AUDITORIUMS, width=12),
        }
        for column, field in enumerate(fields.values()):
            field.grid(row=0, column=column, sticky="new", padx=(0, styles.SPACE_MD))
        tomorrow = (self.app.catalog.now() + dt.timedelta(days=1)).date()
        fields["show_date"].set(tomorrow.isoformat())
        fields["show_time"].set("19:00")
        fields["auditorium"].set(AUDITORIUMS[0])

        actions = ttk.Frame(row, style="Panel.TFrame")
        actions.grid(row=0, column=3, sticky="sw", pady=(0, styles.SPACE_LG))
        button = ttk.Button(actions, text="Add showtime", style="Accent.TButton", cursor="hand2")
        button.pack(side="left")
        status = StatusMessage(card, wraplength=760)
        status.pack(anchor="w")
        self.form = Form(fields, status, button, busy_text="Adding…")
        self.form.bind_submit(self._add)

    def _add_showtime_row(self, table: Table, showtime: AdminShowtime, now: dt.datetime) -> None:
        if not showtime.is_active:
            status, badge = "INACTIVE", "BadgeCanceled.TLabel"
        elif showtime.has_started(now):
            status, badge = "PAST", "BadgeCompleted.TLabel"
        else:
            status, badge = "UPCOMING", "BadgeUpcoming.TLabel"
        def bookings_cell(parent):
            # The confirmed count is itself the button that opens the bookings list.
            return ttk.Button(parent, text=f"{showtime.confirmed_count} confirmed", style="Compact.TButton",
                              cursor="hand2", command=lambda: self.app.show_showtime_bookings(showtime.id))

        def action_cell(parent):
            if showtime.is_active and showtime.is_locked(now):
                return ttk.Label(parent, text="Locked", style="PanelHint.TLabel")
            if showtime.is_active:
                text = "Delete" if showtime.removal_outcome() == "deleted" else "Deactivate"
                command = lambda: self._remove(showtime)
            elif not showtime.has_started(now):
                text, command = "Restore", lambda: self._restore(showtime)
            else:
                return ttk.Label(parent, text="", style="PanelHint.TLabel")
            return ttk.Button(parent, text=text, style="Link.TButton", cursor="hand2", command=command)

        times = f"{format_show_time(showtime.starts_at)} – {format_show_time(showtime.ends_at)}"
        table.add_row([
            lambda parent: ttk.Label(parent, text=format_show_date(showtime.starts_at.date()),
                                     style="PanelField.TLabel"),
            lambda parent: ttk.Label(parent, text=times, style="PanelBody.TLabel"),
            lambda parent: ttk.Label(parent, text=showtime.auditorium, style="PanelBody.TLabel"),
            bookings_cell,
            lambda parent: ttk.Label(parent, text=status, style=badge),
            action_cell,
        ])

    def _add(self) -> None:
        if not self.form.begin():
            return
        values = self.form.values()
        admin_id, movie_id = self.user.id, self.movie_id
        run_in_background(
            self,
            lambda: self.app.showtime_admin.add_showtime(admin_id, movie_id, values["show_date"],
                                                         values["show_time"], values["auditorium"]),
            self._on_added,
            self._on_add_error,
        )

    def _on_added(self, showtime: AdminShowtime) -> None:
        self.app.show_admin_showtimes(self.movie_id)
        self.app.toast(f"Added {format_show_date(showtime.starts_at.date())}, "
                       f"{format_show_time(showtime.starts_at)} in {showtime.auditorium}.")

    def _on_add_error(self, exc: Exception) -> None:
        self.form.end()
        if not handle_showtime_error(self.app, exc, self.movie_id):
            self.form.show_error(exc)

    def _remove(self, showtime: AdminShowtime) -> None:
        when = f"{format_show_date(showtime.starts_at.date())} at {format_show_time(showtime.starts_at)}"
        if showtime.removal_outcome() == "deleted":
            title, question = "Delete showtime", (
                f"Delete the {when} showtime in {showtime.auditorium}?\n\nIt has never had a booking. "
                "This cannot be undone.")
        else:
            title, question = "Deactivate showtime", (
                f"Deactivate the {when} showtime in {showtime.auditorium}?\n\nIt has booking history, "
                "so it will be hidden from customers instead of deleted. Past and canceled bookings "
                "and their receipts are kept.")
        if not messagebox.askyesno(title, question, icon="warning", parent=self):
            return
        try:
            outcome = self.app.showtime_admin.remove_showtime(self.user.id, showtime.id)
        except EXPECTED_ERRORS as exc:
            if not handle_showtime_error(self.app, exc, self.movie_id):
                messagebox.showerror(f"{title} failed", user_message_for(exc), parent=self)
                self.app.show_admin_showtimes(self.movie_id)
            return
        self.app.show_admin_showtimes(self.movie_id)
        self.app.toast(f"The {when} showtime was {outcome}.")

    def _restore(self, showtime: AdminShowtime) -> None:
        try:
            self.app.showtime_admin.restore_showtime(self.user.id, showtime.id)
        except EXPECTED_ERRORS as exc:
            if not handle_showtime_error(self.app, exc, self.movie_id):
                messagebox.showerror("Restore failed", user_message_for(exc), parent=self)
            return
        self.app.show_admin_showtimes(self.movie_id)
        self.app.toast("The showtime is bookable again.")


def handle_showtime_error(app: App, exc: Exception, movie_id: int) -> bool:
    """Admin-wide errors, plus a vanished showtime (refresh the list). Returns True if handled."""
    if isinstance(exc, ShowtimeNotFoundError):
        app.toast(str(exc), error=True)
        app.show_admin_showtimes(movie_id)
        return True
    return handle_admin_error(app, exc)


class AdminShowtimeBookingsView(ttk.Frame):
    """Read-only list of one showtime's confirmed bookings, with seats sold and revenue."""

    def __init__(self, master: ttk.Frame, app: App, user: User, showtime_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        try:
            report = app.showtime_admin.list_confirmed_bookings(user.id, showtime_id)
        except EXPECTED_ERRORS as exc:
            screen_title(self, "Bookings", "← Back to movie list", app.show_admin_movies,
                         eyebrow="Admin").pack(fill="x", pady=(0, styles.SPACE_LG))
            if not handle_admin_error(app, exc):
                message_panel(self, "Bookings could not be loaded", user_message_for(exc),
                              error=True).pack(fill="x")
            return
        showtime = report.showtime

        screen_title(self, "Confirmed bookings", "← Back to showtimes",
                     lambda: app.show_admin_showtimes(showtime.movie_id),
                     eyebrow=f"Admin  ·  {report.movie_title}",
                     subtitle=f"{format_showtime(showtime.starts_at)}  ·  {showtime.auditorium}"
                     ).pack(fill="x", pady=(0, styles.SPACE_LG))

        summary = ttk.Frame(self, style="App.TFrame")
        summary.pack(fill="x", pady=(0, styles.SPACE_LG))
        tiles = (
            ("CONFIRMED BOOKINGS", str(len(report.bookings))),
            ("SEATS SOLD", f"{report.seats_sold} / {report.capacity}"),
            ("REVENUE", format_peso(report.revenue)),
        )
        for column, (label, value) in enumerate(tiles):
            summary.columnconfigure(column, weight=1, uniform="summary")
            tile = ttk.Frame(summary, style="Panel.TFrame", padding=(styles.SPACE_LG, styles.SPACE_MD))
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else styles.SPACE_MD, 0))
            ttk.Label(tile, text=label, style="PanelEyebrow.TLabel").pack(anchor="w")
            ttk.Label(tile, text=value, style="PanelTotal.TLabel").pack(anchor="w")
        if report.canceled_count:
            ttk.Label(self, text=f"{report.canceled_count} canceled booking"
                                 f"{'s are' if report.canceled_count != 1 else ' is'} not shown; "
                                 "their seats were released.", style="Meta.TLabel").pack(
                anchor="w", pady=(0, styles.SPACE_SM))

        if not report.bookings:
            message_panel(self, "No confirmed bookings yet",
                          "Bookings will appear here as customers reserve seats for this showtime."
                          ).pack(fill="x")
            return
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        table = Table(scroll.body, BOOKING_COLUMNS)
        table.pack(fill="x")
        for booking in report.bookings:
            self._add_booking_row(table, booking)

    @staticmethod
    def _add_booking_row(table: Table, booking: ShowtimeBooking) -> None:
        def customer_cell(parent):
            cell = ttk.Frame(parent, style="Panel.TFrame")
            ttk.Label(cell, text=booking.customer_name, style="PanelField.TLabel").pack(anchor="w")
            ttk.Label(cell, text=f"@{booking.username}", style="PanelMono.TLabel").pack(anchor="w")
            return cell

        def seats_cell(parent: Table):
            cell = ttk.Frame(parent, style="Panel.TFrame")
            parent.wrap(ttk.Label(cell, text=", ".join(booking.seat_labels), style="PanelField.TLabel",
                                  justify="left"), 2).pack(anchor="w")
            tickets = f"{booking.ticket_count} TICKET{'S' if booking.ticket_count != 1 else ''}"
            ttk.Label(cell, text=tickets, style="PanelEyebrow.TLabel").pack(anchor="w")
            return cell

        table.add_row([
            lambda parent: ttk.Label(parent, text=booking.reference, style="PanelMono.TLabel"),
            customer_cell,
            seats_cell,
            lambda parent: ttk.Label(parent, text=format_peso(booking.total_amount), style="PanelPrice.TLabel"),
            lambda parent: ttk.Label(parent, text=format_local_datetime(booking.created_at, with_year=False),
                                     style="PanelBody.TLabel"),
        ])
