"""Interactive seat selection for one showtime.

Seats are real ``tk.Button`` controls (ttk buttons cannot easily be recolored
individually). Availability is loaded from the database when the screen opens
and rechecked when the user continues; the selection itself is kept only in
the session and is never written to the database.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from services.catalog_service import ShowtimeUnavailableError
from services.seating_service import (
    ALL_SEATS,
    SEAT_ROWS,
    SEATS_PER_ROW,
    Seat,
    SeatSelection,
    SeatSelectionError,
    SeatsUnavailableError,
)
from ui import styles
from ui.widgets import StatusMessage, message_panel, screen_title, user_message_for
from utils.formatting import format_peso, format_show_date, format_show_time

if TYPE_CHECKING:
    from ui.app import App

AISLE_AFTER_SEAT = 5
CHECKOUT_NEXT_STAGE_MESSAGE = "Checkout will be available in the next stage."


class SeatingView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, showtime_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_MD))
        self.app = app
        self._buttons: dict[Seat, tk.Button] = {}

        try:
            movie, showtime, self.booked = app.seating.open_showtime(showtime_id)
        except Exception as exc:
            previous = app.session.seat_selection
            back = (lambda: app.show_showtimes(previous.movie.id)) if previous else app.show_movies
            screen_title(self, "Select your seats", "← Back", back).pack(fill="x")
            message_panel(self, "Seats could not be loaded", user_message_for(exc),
                          error=True).pack(fill="x", pady=(styles.SPACE_MD, 0))
            return

        # Keep an existing selection only if it is for this same showtime.
        selection = app.session.seat_selection
        if selection is None or selection.showtime.id != showtime.id:
            selection = SeatSelection(movie, showtime)
            app.session.seat_selection = selection
        else:
            selection.update_movie(movie)
        app.session.pending_checkout = None
        self.selection = selection

        stale = frozenset(selection.seats) & self.booked
        selection.discard(stale)

        header = ttk.Frame(self, style="App.TFrame")
        header.pack(fill="x", pady=(0, styles.SPACE_MD))
        ttk.Button(header, text="← Back to showtimes", style="AppLink.TButton", cursor="hand2",
                   command=lambda: app.show_showtimes(movie.id)).pack(side="right", anchor="n")
        ttk.Label(header, text=f"Select your seats · {movie.title}", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text=(f"{format_show_date(showtime.starts_at.date())}  ·  "
                  f"{format_show_time(showtime.starts_at)}  ·  {showtime.auditorium}"),
            style="Meta.TLabel",
        ).pack(anchor="w")

        body = ttk.Frame(self, style="App.TFrame")
        body.pack(fill="both", expand=True)
        summary = self._build_summary(body)
        summary.pack(side="right", fill="y", padx=(styles.SPACE_LG, 0))
        hall = ttk.Frame(body, style="App.TFrame")
        hall.pack(side="left", fill="both", expand=True)
        self._build_hall(hall)

        self._refresh()
        if stale:
            labels = ", ".join(seat.label for seat in sorted(stale))
            self.status.error(f"{labels} {'was' if len(stale) == 1 else 'were'} booked since you "
                              "last looked and removed from your selection.")

    # --- Layout ---------------------------------------------------------------

    def _build_hall(self, parent: ttk.Frame) -> None:
        hall = ttk.Frame(parent, style="App.TFrame")
        hall.pack(anchor="n")

        ttk.Label(hall, text="SCREEN", style="Screen.TLabel", anchor="center").pack(fill="x", padx=28)
        ttk.Frame(hall, style="Accent.TFrame", height=3).pack(fill="x", padx=28,
                                                              pady=(0, styles.SPACE_MD))

        grid = ttk.Frame(hall, style="App.TFrame")
        grid.pack()
        for row_index, row in enumerate(SEAT_ROWS):
            ttk.Label(grid, text=row, style="RowLabel.TLabel", width=3).grid(row=row_index, column=0)
            for number in range(1, SEATS_PER_ROW + 1):
                seat = Seat(row, number)
                button = tk.Button(
                    grid, text=seat.label, width=4, font=styles.FONT_SEAT, relief="flat",
                    borderwidth=0, highlightthickness=0, cursor="hand2",
                    command=lambda s=seat: self._on_seat_click(s),
                )
                aisle = styles.SPACE_LG if number == AISLE_AFTER_SEAT + 1 else 0
                button.grid(row=row_index, column=number, padx=(3 + aisle, 3), pady=3, ipady=1)
                self._buttons[seat] = button
            ttk.Label(grid, text=row, style="RowLabel.TLabel", width=3).grid(
                row=row_index, column=SEATS_PER_ROW + 1)

        legend = ttk.Frame(hall, style="App.TFrame")
        legend.pack(pady=(styles.SPACE_MD, 0))
        for text, color in (("Available", styles.SEAT_AVAILABLE),
                            ("Selected", styles.SEAT_SELECTED),
                            ("Booked", styles.SEAT_BOOKED)):
            tk.Frame(legend, width=16, height=16, background=color,
                     highlightthickness=1, highlightbackground=styles.BORDER).pack(side="left")
            ttk.Label(legend, text=text, style="Legend.TLabel").pack(
                side="left", padx=(styles.SPACE_XS, styles.SPACE_LG))

    def _build_summary(self, parent: ttk.Frame) -> ttk.Frame:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=styles.SPACE_MD)
        ttk.Label(card, text="Your selection", style="PanelHeading.TLabel").pack(anchor="w")

        ttk.Label(card, text="Seats", style="PanelHint.TLabel").pack(anchor="w", pady=(styles.SPACE_SM, 0))
        self.seats_label = ttk.Label(card, style="PanelValue.TLabel", wraplength=250, justify="left")
        self.seats_label.pack(anchor="w")

        rows = ttk.Frame(card, style="Panel.TFrame")
        rows.pack(fill="x", pady=(styles.SPACE_SM, 0))
        rows.columnconfigure(1, weight=1)
        self.count_label = self._summary_row(rows, 0, "Tickets")
        self.price_label = self._summary_row(rows, 1, "Price per ticket")

        ttk.Frame(card, style="Divider.TFrame", height=1).pack(fill="x", pady=styles.SPACE_SM)
        total_row = ttk.Frame(card, style="Panel.TFrame")
        total_row.pack(fill="x")
        ttk.Label(total_row, text="Total", style="PanelField.TLabel").pack(side="left", anchor="s")
        self.total_label = ttk.Label(total_row, style="PanelTotal.TLabel")
        self.total_label.pack(side="right")

        ttk.Button(card, text="Continue", style="Accent.TButton", cursor="hand2",
                   command=self._on_continue).pack(fill="x", pady=(styles.SPACE_MD, 0))
        ttk.Button(card, text="Clear Selection", style="Secondary.TButton", cursor="hand2",
                   command=self._on_clear).pack(fill="x", pady=(styles.SPACE_SM, 0))

        self.status = StatusMessage(card, wraplength=250)
        self.status.pack(anchor="w", fill="x", pady=(styles.SPACE_SM, 0))
        return card

    @staticmethod
    def _summary_row(parent: ttk.Frame, row: int, label: str) -> ttk.Label:
        ttk.Label(parent, text=label, style="PanelBody.TLabel").grid(row=row, column=0, sticky="w")
        value = ttk.Label(parent, style="PanelField.TLabel")
        value.grid(row=row, column=1, sticky="e")
        return value

    # --- Rendering ------------------------------------------------------------

    def _paint(self, seat: Seat) -> None:
        button = self._buttons[seat]
        if seat in self.booked:
            button.configure(state="disabled", background=styles.SEAT_BOOKED,
                             disabledforeground=styles.SEAT_BOOKED_TEXT, cursor="arrow")
        elif self.selection.is_selected(seat):
            button.configure(state="normal", background=styles.SEAT_SELECTED,
                             foreground=styles.TEXT_PRIMARY,
                             activebackground=styles.SEAT_SELECTED_HOVER,
                             activeforeground=styles.TEXT_PRIMARY, cursor="hand2")
        else:
            button.configure(state="normal", background=styles.SEAT_AVAILABLE,
                             foreground=styles.TEXT_PRIMARY,
                             activebackground=styles.SEAT_AVAILABLE_HOVER,
                             activeforeground=styles.TEXT_PRIMARY, cursor="hand2")

    def _refresh(self) -> None:
        """Repaint every seat and the price summary from the current state."""
        for seat in ALL_SEATS:
            self._paint(seat)
        selection = self.selection
        self.seats_label.configure(text=", ".join(selection.labels) or "No seats selected")
        self.count_label.configure(text=str(selection.count))
        self.price_label.configure(text=format_peso(selection.price_per_ticket))
        self.total_label.configure(text=format_peso(selection.total))

    # --- Actions --------------------------------------------------------------

    def _selection_changed(self) -> None:
        self.app.session.pending_checkout = None
        self.status.clear()
        self._refresh()

    def _on_seat_click(self, seat: Seat) -> None:
        try:
            self.selection.toggle(seat, self.booked)
        except SeatSelectionError as exc:
            self.status.error(str(exc))
            return
        self._selection_changed()

    def _on_clear(self) -> None:
        self.selection.clear()
        self._selection_changed()

    def _on_continue(self) -> None:
        try:
            checkout = self.app.seating.prepare_checkout(self.selection)
            self.booked = self.app.seating.get_booked_seats(self.selection.showtime.id)
        except SeatsUnavailableError as exc:
            self.booked = exc.booked
            self._selection_changed()
            self.status.error(str(exc))
            return
        except ShowtimeUnavailableError as exc:
            messagebox.showerror(styles.APP_NAME, str(exc), parent=self)
            self.app.session.seat_selection = None
            self.app.show_showtimes(self.selection.movie.id)
            return
        except Exception as exc:
            self.status.error(user_message_for(exc))
            return

        self.app.session.pending_checkout = checkout
        self._refresh()
        verb = "is" if len(checkout.seats) == 1 else "are"
        self.status.success(f"Your {'seat' if verb == 'is' else 'seats'} {verb} still available. "
                            f"{CHECKOUT_NEXT_STAGE_MESSAGE}")
