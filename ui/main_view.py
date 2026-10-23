"""Home screen shown after login, with shortcuts to the main sections."""

from __future__ import annotations

import datetime as dt
from tkinter import ttk
from typing import TYPE_CHECKING

from services.auth_service import User
from ui import styles

if TYPE_CHECKING:
    from ui.app import App

SECTION_TILES = (
    ("01", "Movies", "Browse now-showing movies and pick a showtime.", "Browse movies"),
    ("02", "My Bookings", "Review your reserved seats, receipts, and cancellations.", "View bookings"),
    ("03", "Profile", "Update your name or change your password.", "Open profile"),
)


def greeting(now: dt.datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    return "Good afternoon" if now.hour < 18 else "Good evening"


class HomeView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL + 8))

        ttk.Label(self, text=greeting(app.catalog.now()).upper(), style="Eyebrow.TLabel").pack(anchor="w")
        name_row = ttk.Frame(self, style="App.TFrame")
        name_row.pack(anchor="w")
        ttk.Label(name_row, text=user.full_name, style="Display.TLabel", wraplength=820,
                  justify="left").pack(side="left")
        ttk.Label(name_row, text=".", style="Display.TLabel", foreground=styles.ACCENT).pack(
            side="left", anchor="s")
        ttk.Label(self, text=styles.APP_TAGLINE, style="Tagline.TLabel").pack(
            anchor="w", pady=(styles.SPACE_XS, styles.SPACE_MD))
        ttk.Label(
            self,
            text=("Browse what's showing, pick your seats on a live seat map, and keep every "
                  "booking and receipt in one place, all stored locally on this computer."),
            style="Body.TLabel", wraplength=680, justify="left",
        ).pack(anchor="w")

        tiles = ttk.Frame(self, style="App.TFrame")
        tiles.pack(fill="x", pady=(styles.SPACE_XL + 8, 0))
        commands = {"Movies": app.show_movies, "My Bookings": app.show_bookings,
                    "Profile": app.show_profile}
        for column, (number, title, blurb, action) in enumerate(SECTION_TILES):
            tiles.columnconfigure(column, weight=1, uniform="tiles")
            tile = ttk.Frame(tiles, style="Panel.TFrame", padding=styles.SPACE_LG)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else styles.SPACE_MD, 0))
            ttk.Label(tile, text=f"{number} /", style="PanelEyebrow.TLabel").pack(anchor="w")
            ttk.Label(tile, text=title, style="PanelHeading.TLabel").pack(anchor="w", pady=(styles.SPACE_SM, 2))
            ttk.Label(tile, text=blurb, style="PanelBody.TLabel", wraplength=270, justify="left").pack(
                anchor="w")
            # One primary action on the screen; the rest are secondary.
            ttk.Button(tile, text=action, cursor="hand2", command=commands[title],
                       style="Accent.TButton" if column == 0 else "Secondary.TButton").pack(
                anchor="w", pady=(styles.SPACE_LG, 0))
