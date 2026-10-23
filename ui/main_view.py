"""Home screen shown after login.

My Bookings is a placeholder until its planned stage; the Movies and profile
shortcuts are functional.
"""

from __future__ import annotations

from tkinter import ttk
from typing import TYPE_CHECKING

from services.auth_service import User
from ui import styles
from ui.widgets import panel

if TYPE_CHECKING:
    from ui.app import App

SECTION_CARDS = (
    ("Movies", "Browse now-showing movies and pick a showtime."),
    ("My Bookings", "Review your reserved seats and receipts."),
    ("My Profile", "View your account and update your name or password."),
)


class HomeView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL))

        ttk.Label(self, text=f"Welcome, {user.full_name}", style="Display.TLabel").pack(anchor="w")
        ttk.Label(self, text=styles.APP_TAGLINE, style="Tagline.TLabel").pack(
            anchor="w", pady=(styles.SPACE_XS, styles.SPACE_MD)
        )
        ttk.Label(
            self,
            text=(
                f"{styles.APP_NAME} is a desktop ticket booking system for browsing now-showing "
                "movies, choosing showtimes, reserving seats, and keeping track of your bookings "
                "and receipts — all stored locally on this computer."
            ),
            style="Body.TLabel",
            wraplength=720,
            justify="left",
        ).pack(anchor="w")

        cards = ttk.Frame(self, style="App.TFrame")
        cards.pack(fill="x", pady=(styles.SPACE_XL, 0))
        for column, (title, blurb) in enumerate(SECTION_CARDS):
            cards.columnconfigure(column, weight=1, uniform="cards")
            card = panel(cards, title, blurb, wraplength=260)
            card.grid(row=0, column=column, sticky="nsew",
                      padx=(0 if column == 0 else styles.SPACE_MD, 0))
            action = {"Movies": ("Browse movies", app.show_movies),
                      "My Profile": ("Open profile", app.show_profile)}.get(title)
            if action is not None:
                ttk.Button(card, text=action[0], style="Accent.TButton", cursor="hand2",
                           command=action[1]).pack(anchor="w", pady=(styles.SPACE_MD, 0))
            else:
                ttk.Label(card, text="Coming soon", style="PanelHint.TLabel").pack(
                    anchor="w", pady=(styles.SPACE_MD, 0)
                )
