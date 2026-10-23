"""Checkout, booking confirmation, booking history, and receipt screens.

Every screen here reads bookings back from the database through
:class:`~services.booking_service.BookingService`, scoped to the signed-in user;
nothing is shown from temporary UI state once a booking exists.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from services.auth_service import User
from services.booking_service import (
    DISPLAY_CANCELED,
    DISPLAY_COMPLETED,
    BookingDetails,
    BookingError,
    SeatConflictError,
)
from services.catalog_service import ShowtimeUnavailableError
from services.receipt_service import RECEIPTS_DIR, receipt_filename, render_receipt, save_receipt
from services.seating_service import PendingCheckout, SeatsUnavailableError
from ui import styles
from ui.widgets import (
    EXPECTED_ERRORS,
    ScrollFrame,
    StatusMessage,
    message_panel,
    panel,
    run_in_background,
    screen_title,
    user_message_for,
)
from utils.formatting import (
    format_local_datetime,
    format_peso,
    format_show_date,
    format_show_time,
    format_showtime,
)

if TYPE_CHECKING:
    from ui.app import App

CHECK_GLYPH = "\uE73E"  # Segoe Fluent Icons check mark

BADGE_STYLES = {
    DISPLAY_CANCELED: "BadgeCanceled.TLabel",
    DISPLAY_COMPLETED: "BadgeCompleted.TLabel",
}


def detail_grid(parent: tk.Misc, rows: list[tuple[str, str]], *, value_style: str = "PanelField.TLabel",
                wraplength: int = 320) -> ttk.Frame:
    """Label/value pairs in two aligned columns on a panel."""
    grid = ttk.Frame(parent, style="Panel.TFrame")
    grid.columnconfigure(1, weight=1)
    for index, (label, value) in enumerate(rows):
        ttk.Label(grid, text=label, style="PanelBody.TLabel").grid(
            row=index, column=0, sticky="nw", padx=(0, styles.SPACE_LG), pady=2)
        ttk.Label(grid, text=value, style=value_style, wraplength=wraplength, justify="left").grid(
            row=index, column=1, sticky="nw", pady=2)
    return grid


def save_receipt_with_dialog(parent: tk.Misc, app: App, booking: BookingDetails) -> None:
    """Ask where to save the receipt, then write it. A canceled dialog does nothing."""
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = filedialog.asksaveasfilename(
        parent=parent, title="Save receipt", initialdir=str(RECEIPTS_DIR),
        initialfile=receipt_filename(booking.reference), defaultextension=".txt",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        saved = save_receipt(booking, path)
    except OSError as exc:
        app.toast(f"The receipt could not be saved: {exc.strerror or exc}. "
                  "Please choose another location.", error=True)
        return
    app.toast(f"Receipt saved to {saved}")


# --- Checkout -----------------------------------------------------------------

class CheckoutView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user = user
        self.busy = False

        selection = app.session.seat_selection
        if selection is None or app.session.pending_checkout is None:
            self._dead_end("Nothing to check out",
                           "Choose a movie, showtime, and seats before checking out.")
            return
        self.selection = selection

        # Re-read the price and availability from the database; never trust earlier UI state.
        try:
            checkout = app.seating.prepare_checkout(selection)
        except SeatsUnavailableError as exc:
            app.session.pending_checkout = None
            self._dead_end("Some seats are no longer available", str(exc), back_to_seats=True)
            return
        except ShowtimeUnavailableError as exc:
            app.session.clear_booking_state()
            self._dead_end("This showtime cannot be booked", str(exc))
            return
        except EXPECTED_ERRORS as exc:
            self._dead_end("Checkout could not be loaded", user_message_for(exc), back_to_seats=True)
            return
        app.session.pending_checkout = checkout
        self.checkout = checkout

        screen_title(self, "Review and confirm", "← Back to seat selection", self._back_to_seats,
                     eyebrow="Checkout",
                     subtitle="Check the details below, then confirm to reserve your seats.").pack(
            fill="x", pady=(0, styles.SPACE_LG))

        columns = ttk.Frame(self, style="App.TFrame")
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=3, uniform="checkout")
        columns.columnconfigure(1, weight=2, uniform="checkout")
        self._booking_panel(columns, checkout).grid(row=0, column=0, sticky="nsew",
                                                    padx=(0, styles.SPACE_MD))
        self._payment_panel(columns, checkout).grid(row=0, column=1, sticky="nsew")

    def _booking_panel(self, parent: ttk.Frame, checkout: PendingCheckout) -> ttk.Frame:
        card = panel(parent, "Booking summary")
        detail_grid(card, [
            ("Customer", self.user.full_name),
            ("Movie", checkout.movie.title),
            ("Date", format_show_date(checkout.showtime.starts_at.date())),
            ("Time", format_show_time(checkout.showtime.starts_at)),
            ("Auditorium", checkout.showtime.auditorium),
            ("Seats", ", ".join(seat.label for seat in checkout.seats)),
        ]).pack(fill="x", pady=(styles.SPACE_MD, 0))
        return card

    def _payment_panel(self, parent: ttk.Frame, checkout: PendingCheckout) -> ttk.Frame:
        card = panel(parent, "Total")
        detail_grid(card, [
            ("Tickets", str(len(checkout.seats))),
            ("Price per ticket", format_peso(checkout.price_per_ticket)),
        ]).pack(fill="x", pady=(styles.SPACE_MD, 0))
        ttk.Frame(card, style="Divider.TFrame", height=1).pack(fill="x", pady=styles.SPACE_SM)
        ttk.Label(card, text=format_peso(checkout.total), style="PanelTotal.TLabel").pack(anchor="e")

        self.confirm_button = ttk.Button(card, text="Confirm Booking", style="Accent.TButton",
                                         cursor="hand2", command=self._confirm)
        self.confirm_button.pack(fill="x", pady=(styles.SPACE_MD, 0))
        self.back_button = ttk.Button(card, text="Back to Seat Selection", style="Secondary.TButton",
                                      cursor="hand2", command=self._back_to_seats)
        self.back_button.pack(fill="x", pady=(styles.SPACE_SM, 0))
        self.cancel_button = ttk.Button(card, text="Cancel / Return to Movies", style="Link.TButton",
                                        cursor="hand2", command=self._return_to_movies)
        self.cancel_button.pack(pady=(styles.SPACE_SM, 0))
        self.status = StatusMessage(card, wraplength=300)
        self.status.pack(anchor="w", fill="x", pady=(styles.SPACE_SM, 0))
        return card

    def _dead_end(self, title: str, message: str, *, back_to_seats: bool = False) -> None:
        screen_title(self, "Checkout", eyebrow="Checkout").pack(fill="x", pady=(0, styles.SPACE_LG))
        box = message_panel(self, title, message, error=back_to_seats)
        box.pack(fill="x")
        actions = ttk.Frame(box, style="Panel.TFrame")
        actions.pack(anchor="w", pady=(styles.SPACE_MD, 0))
        if back_to_seats:
            ttk.Button(actions, text="Back to Seat Selection", style="Accent.TButton", cursor="hand2",
                       command=self._back_to_seats).pack(side="left", padx=(0, styles.SPACE_SM))
        ttk.Button(actions, text="Return to Movies", style="Secondary.TButton", cursor="hand2",
                   command=self.app.show_movies).pack(side="left")

    # --- Actions ---

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        for button in (self.confirm_button, self.back_button, self.cancel_button):
            button.state(state)
        self.confirm_button.configure(text="Booking…" if busy else "Confirm Booking")

    def _confirm(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status.clear()
        user_id, showtime_id, seats = self.user.id, self.checkout.showtime.id, self.checkout.seats
        run_in_background(
            self,
            lambda: self.app.bookings.create_booking(user_id, showtime_id, seats),
            self._on_booked,
            self._on_failed,
        )

    def _on_booked(self, booking: BookingDetails) -> None:
        self.app.session.clear_booking_state()
        self.app.show_confirmation(booking.id)

    def _on_failed(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status.error(user_message_for(exc))
        if isinstance(exc, (SeatConflictError, ShowtimeUnavailableError)):
            # Retrying the same request cannot succeed; the user must choose again.
            self.app.session.pending_checkout = None
            if isinstance(exc, SeatConflictError):
                self.selection.discard(exc.seats)
            self.confirm_button.state(["disabled"])

    def _back_to_seats(self) -> None:
        if not self.busy:
            self.app.show_seating(self.selection.showtime.id)

    def _return_to_movies(self) -> None:
        if not self.busy:
            self.app.session.clear_booking_state()
            self.app.show_movies()


# --- Confirmation ---------------------------------------------------------------

class ConfirmationView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User, booking_id: int) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        try:
            booking = app.bookings.get_booking(user.id, booking_id)
        except EXPECTED_ERRORS as exc:
            screen_title(self, "Booking").pack(fill="x", pady=(0, styles.SPACE_MD))
            message_panel(self, "Booking could not be loaded", user_message_for(exc), error=True).pack(fill="x")
            return
        self.booking = booking

        hero = ttk.Frame(self, style="App.TFrame")
        hero.pack(fill="x", pady=(0, styles.SPACE_LG))
        tk.Label(hero, text=CHECK_GLYPH, font=(styles.FONT_ICON[0], 22), background=styles.ACCENT,
                 foreground=styles.ON_ACCENT, width=3, height=1, pady=10).pack(side="left", anchor="n")
        heading = ttk.Frame(hero, style="App.TFrame")
        heading.pack(side="left", padx=(styles.SPACE_LG, 0))
        screen_title(heading, "You're all set", eyebrow="Booking confirmed",
                     subtitle="Your seats are reserved. Enjoy the show!").pack(anchor="w")

        card = ttk.Frame(self, style="Panel.TFrame", padding=styles.SPACE_LG)
        card.pack(fill="x")
        ttk.Label(card, text="BOOKING REFERENCE", style="PanelEyebrow.TLabel").pack(anchor="w")
        ttk.Label(card, text=booking.reference, style="PanelReference.TLabel").pack(anchor="w")
        detail_grid(card, [
            ("Movie", booking.movie_title),
            ("Showtime", f"{format_showtime(booking.starts_at)}  ·  {booking.auditorium}"),
            ("Seats", ", ".join(booking.seat_labels)),
            ("Tickets", str(booking.ticket_count)),
            ("Total", format_peso(booking.total_amount)),
        ], wraplength=640).pack(fill="x", pady=(styles.SPACE_MD, 0))

        actions = ttk.Frame(card, style="Panel.TFrame")
        actions.pack(anchor="w", pady=(styles.SPACE_LG, 0))
        for text, style, command in (
            ("View Receipt", "Accent.TButton", lambda: app.show_receipt(booking.id, "confirmation")),
            ("Save Receipt to File", "Secondary.TButton",
             lambda: save_receipt_with_dialog(self, app, booking)),
            ("View My Bookings", "Secondary.TButton", app.show_bookings),
            ("Return to Movies", "Secondary.TButton", app.show_movies),
        ):
            ttk.Button(actions, text=text, style=style, cursor="hand2", command=command).pack(
                side="left", padx=(0, styles.SPACE_SM))


# --- Booking history ------------------------------------------------------------

class BookingsView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user = user

        screen_title(self, "My Bookings", eyebrow="Tickets",
                     subtitle="Upcoming bookings are listed first, followed by past and canceled ones."
                     ).pack(fill="x", pady=(0, styles.SPACE_SM))

        try:
            bookings = app.bookings.list_bookings(user.id)
        except EXPECTED_ERRORS as exc:
            message_panel(self, "Bookings could not be loaded", user_message_for(exc),
                          error=True).pack(fill="x", pady=(styles.SPACE_MD, 0))
            return
        if not bookings:
            box = message_panel(self, "No bookings yet",
                                "When you book tickets, they will appear here with their receipts.")
            box.pack(fill="x", pady=(styles.SPACE_MD, 0))
            ttk.Button(box, text="Browse movies", style="Accent.TButton", cursor="hand2",
                       command=app.show_movies).pack(anchor="w", pady=(styles.SPACE_MD, 0))
            return

        now = app.catalog.now()
        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True, pady=(styles.SPACE_MD, 0))
        scroll.body.columnconfigure(0, weight=1)
        for index, booking in enumerate(bookings):
            self._booking_card(scroll.body, booking, now).grid(
                row=index, column=0, sticky="ew", pady=(0, styles.SPACE_SM))

    def _booking_card(self, parent: ttk.Frame, booking: BookingDetails, now) -> ttk.Frame:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 0, styles.SPACE_LG, 0))
        card.columnconfigure(1, weight=1)

        # Ticket-stub date block
        stub = tk.Frame(card, background=styles.BG_RAISED)
        stub.grid(row=0, column=0, sticky="ns", padx=(0, styles.SPACE_LG))
        for text, font, color, pad in (
            (f"{booking.starts_at:%b}".upper(), styles.FONT_EYEBROW, styles.TEXT_MUTED, (14, 0)),
            (str(booking.starts_at.day), (styles.FONT_DISPLAY[0], 24, "bold"), styles.TEXT_PRIMARY, 0),
            (format_show_time(booking.starts_at), styles.FONT_EYEBROW, styles.TEXT_MUTED, (0, 14)),
        ):
            tk.Label(stub, text=text, font=font, background=styles.BG_RAISED, foreground=color,
                     width=9).pack(pady=pad)

        info = ttk.Frame(card, style="Panel.TFrame", padding=(0, styles.SPACE_MD))
        info.grid(row=0, column=1, sticky="w")
        top = ttk.Frame(info, style="Panel.TFrame")
        top.pack(anchor="w")
        ttk.Label(top, text=booking.movie_title, style="PanelHeading.TLabel").pack(side="left")
        status = booking.display_status(now)
        ttk.Label(top, text=status.upper(), style=BADGE_STYLES.get(status, "BadgeUpcoming.TLabel")).pack(
            side="left", padx=(styles.SPACE_SM, 0))
        ttk.Label(top, text=booking.reference, style="PanelMono.TLabel").pack(
            side="left", padx=(styles.SPACE_MD, 0))

        ttk.Label(info, text=f"{format_showtime(booking.starts_at)}  ·  {booking.auditorium}",
                  style="PanelField.TLabel").pack(anchor="w", pady=(styles.SPACE_XS, 0))
        tickets = f"{booking.ticket_count} ticket{'s' if booking.ticket_count != 1 else ''}"
        ttk.Label(info, text=f"Seats {', '.join(booking.seat_labels)}  ·  {tickets}  ·  "
                             f"{format_peso(booking.total_amount)}",
                  style="PanelBody.TLabel", wraplength=640, justify="left").pack(anchor="w")
        ttk.Label(info, text=f"Booked {format_local_datetime(booking.created_at)}",
                  style="PanelHint.TLabel").pack(anchor="w")

        actions = ttk.Frame(card, style="Panel.TFrame")
        actions.grid(row=0, column=2, sticky="e")
        ttk.Button(actions, text="View Receipt", style="Secondary.TButton", cursor="hand2",
                   command=lambda: self.app.show_receipt(booking.id, "bookings")).pack(fill="x")
        if booking.can_cancel(now):
            ttk.Button(actions, text="Cancel Booking", style="Link.TButton", cursor="hand2",
                       command=lambda: self._cancel(booking)).pack(pady=(styles.SPACE_SM, 0))
        return card

    def _cancel(self, booking: BookingDetails) -> None:
        confirmed = messagebox.askyesno(
            "Cancel booking",
            f"Cancel booking {booking.reference} for {booking.movie_title} on "
            f"{format_showtime(booking.starts_at)}?\n\nSeats {', '.join(booking.seat_labels)} will be "
            "released for other customers. This cannot be undone.",
            icon="warning", parent=self,
        )
        if not confirmed:
            return
        try:
            canceled = self.app.bookings.cancel_booking(self.user.id, booking.id)
        except BookingError as exc:
            messagebox.showerror("Booking not canceled", str(exc), parent=self)
            self.app.show_bookings()  # the booking may have changed; show its current state
            return
        except EXPECTED_ERRORS as exc:
            messagebox.showerror("Booking not canceled", user_message_for(exc), parent=self)
            return
        self.app.show_bookings()
        self.app.toast(f"Booking {canceled.reference} was canceled and its seats were released.")


# --- Receipt ----------------------------------------------------------------------

class ReceiptView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User, booking_id: int,
                 back_to: str = "bookings") -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        back: Callable[[], None] = (
            (lambda: app.show_confirmation(booking_id)) if back_to == "confirmation" else app.show_bookings
        )
        back_text = "← Back to confirmation" if back_to == "confirmation" else "← Back to My Bookings"
        screen_title(self, "Receipt", back_text, back, eyebrow="Tickets").pack(
            fill="x", pady=(0, styles.SPACE_LG))

        try:
            booking = app.bookings.get_booking(user.id, booking_id)
        except EXPECTED_ERRORS as exc:
            message_panel(self, "Receipt could not be loaded", user_message_for(exc), error=True).pack(fill="x")
            return

        body = ttk.Frame(self, style="App.TFrame")
        body.pack(fill="both", expand=True)
        text = tk.Text(body, width=50, font=styles.FONT_MONO, background=styles.PAPER,
                       foreground=styles.ON_ACCENT, relief="flat", padx=styles.SPACE_LG + 4,
                       pady=styles.SPACE_LG, highlightthickness=0, wrap="none",
                       selectbackground=styles.ACCENT, selectforeground=styles.ON_ACCENT)
        text.insert("1.0", render_receipt(booking))
        text.configure(state="disabled")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="y")
        scrollbar.pack(side="left", fill="y")

        side = ttk.Frame(body, style="App.TFrame")
        side.pack(side="left", fill="both", expand=True, padx=(styles.SPACE_LG, 0))
        card = panel(side, "Keep a copy", "Save this receipt as a text file. The default "
                     "folder is the app's receipts folder.", wraplength=280)
        card.pack(fill="x")
        ttk.Button(card, text="Save Receipt to File", style="Accent.TButton", cursor="hand2",
                   command=lambda: save_receipt_with_dialog(self, app, booking)).pack(
            fill="x", pady=(styles.SPACE_MD, 0))
