"""Visual identity: colors, fonts, spacing, and ttk style configuration.

Widgets should reference the named ttk styles defined in :func:`apply_theme`
(e.g. ``"Heading.TLabel"``) instead of hard-coding colors or fonts.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from utils.branding import APP_NAME, APP_TAGLINE

__all__ = ["APP_NAME", "APP_TAGLINE", "apply_theme", "center_window"]
WINDOW_TITLE = f"{APP_NAME} — Cinema Ticket Booking"
WINDOW_SIZE = (1100, 700)
WINDOW_MIN_SIZE = (1000, 660)

# Colors
BG_APP = "#1c1c1f"          # charcoal window background
BG_SURFACE = "#111113"      # header / content surfaces
BG_SURFACE_ALT = "#26262a"  # raised panels
BORDER = "#34343a"
ACCENT = "#e50914"          # cinema red
ACCENT_DARK = "#a3070f"
TEXT_PRIMARY = "#ffffff"
TEXT_MUTED = "#9a9aa3"
TEXT_FAINT = "#6b6b74"      # placeholder hints
TEXT_SUCCESS = "#4ade80"
TEXT_ERROR = "#f87171"
TEXT_DISABLED = "#5c5c64"

# Seat states (tk.Button colors; ttk buttons cannot be recolored per widget easily)
SEAT_AVAILABLE = "#4a4a52"
SEAT_AVAILABLE_HOVER = "#62626c"
SEAT_SELECTED = ACCENT
SEAT_SELECTED_HOVER = ACCENT_DARK
SEAT_BOOKED = "#2a2a2e"
SEAT_BOOKED_TEXT = "#55555c"

# Typography (Segoe UI ships with Windows; Tk falls back gracefully elsewhere)
FONT_FAMILY = "Segoe UI"
FONT_BRAND = (FONT_FAMILY, 20, "bold")
FONT_DISPLAY = (FONT_FAMILY, 28, "bold")
FONT_HEADING = (FONT_FAMILY, 14, "bold")
FONT_BODY = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_NAV = (FONT_FAMILY, 11, "bold")
FONT_SEAT = (FONT_FAMILY, 9, "bold")
FONT_MONO = ("Consolas", 11)
FONT_REFERENCE = ("Consolas", 18, "bold")

# Spacing scale (pixels)
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 40


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Configure the window background and all named ttk styles."""
    root.configure(background=BG_APP)
    style = ttk.Style(root)
    # "clam" honors custom background colors on Windows; "vista" does not.
    style.theme_use("clam")

    style.configure(".", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_BODY)

    style.configure("App.TFrame", background=BG_APP)
    style.configure("Surface.TFrame", background=BG_SURFACE)
    style.configure("Panel.TFrame", background=BG_SURFACE_ALT)
    style.configure("Accent.TFrame", background=ACCENT)

    style.configure("Brand.TLabel", background=BG_SURFACE, foreground=TEXT_PRIMARY, font=FONT_BRAND)
    style.configure("BrandAccent.TLabel", background=BG_SURFACE, foreground=ACCENT, font=FONT_BRAND)

    style.configure("Display.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_DISPLAY)
    style.configure("Tagline.TLabel", background=BG_APP, foreground=ACCENT, font=FONT_HEADING)
    style.configure("Body.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_BODY)

    style.configure("PanelHeading.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_HEADING)
    style.configure("PanelBody.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_MUTED,
                    font=FONT_BODY)

    style.configure("Footer.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED, font=FONT_SMALL)

    # Forms (rendered on Panel surfaces)
    style.configure("PanelField.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_BODY)
    style.configure("PanelValue.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_HEADING)
    style.configure("PanelHint.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_FAINT,
                    font=FONT_SMALL)
    style.configure("PanelError.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_ERROR,
                    font=FONT_SMALL)
    style.configure("PanelSuccess.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_SUCCESS,
                    font=FONT_BODY)
    style.configure("PanelFailure.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_ERROR,
                    font=FONT_BODY)
    style.configure(
        "TEntry",
        fieldbackground=BG_SURFACE, foreground=TEXT_PRIMARY, insertcolor=TEXT_PRIMARY,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(SPACE_SM, 6),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
        fieldbackground=[("readonly", BG_SURFACE_ALT)],
    )

    # Buttons
    style.configure(
        "Accent.TButton", background=ACCENT, foreground=TEXT_PRIMARY, font=FONT_NAV,
        borderwidth=0, focusthickness=0, padding=(SPACE_MD, SPACE_SM),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", BORDER), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
        foreground=[("disabled", TEXT_DISABLED)],
    )
    style.configure(
        "Secondary.TButton", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY, font=FONT_BODY,
        bordercolor=BORDER, lightcolor=BG_SURFACE_ALT, darkcolor=BG_SURFACE_ALT,
        focusthickness=0, padding=(SPACE_MD, 6),
    )
    style.map("Secondary.TButton", background=[("active", BORDER)],
              foreground=[("disabled", TEXT_DISABLED)])
    # Text-style links. width=0 overrides clam's 11-character minimum so links size to their text.
    for name, surface in (("Link.TButton", BG_SURFACE_ALT), ("AppLink.TButton", BG_APP)):
        style.configure(name, background=surface, foreground=ACCENT, font=FONT_BODY,
                        borderwidth=0, focusthickness=0, padding=0, width=0)
        style.map(name, background=[("active", surface), ("disabled", surface)],
                  foreground=[("disabled", TEXT_DISABLED), ("active", TEXT_PRIMARY)])

    # Header navigation
    style.configure("NavLink.TButton", background=BG_SURFACE, foreground=TEXT_PRIMARY,
                    font=FONT_NAV, borderwidth=0, focusthickness=0, padding=0, width=0)
    style.map("NavLink.TButton", background=[("active", BG_SURFACE)],
              foreground=[("active", ACCENT)])
    style.configure("NavCurrent.TLabel", background=BG_SURFACE, foreground=ACCENT, font=FONT_NAV)
    style.configure("HeaderUser.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED,
                    font=FONT_SMALL)
    style.configure("Header.TButton", background=BG_SURFACE, foreground=TEXT_PRIMARY,
                    font=FONT_SMALL, bordercolor=BORDER, lightcolor=BG_SURFACE,
                    darkcolor=BG_SURFACE, focusthickness=0, padding=(SPACE_MD, SPACE_XS))
    style.map("Header.TButton", background=[("active", ACCENT_DARK)],
              bordercolor=[("active", ACCENT_DARK)])

    # Catalog, showtimes, and seating
    style.configure("Heading.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_HEADING)
    style.configure("Meta.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_BODY)
    style.configure("Price.TLabel", background=BG_APP, foreground=ACCENT, font=FONT_HEADING)
    style.configure("PanelPrice.TLabel", background=BG_SURFACE_ALT, foreground=ACCENT,
                    font=FONT_HEADING)
    style.configure("PanelTotal.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=(FONT_FAMILY, 20, "bold"))
    style.configure("PanelBadge.TLabel", background=BORDER, foreground=TEXT_PRIMARY,
                    font=FONT_SMALL, padding=(SPACE_SM, 2))
    style.configure("Screen.TLabel", background=BORDER, foreground=TEXT_MUTED,
                    font=(FONT_FAMILY, 9, "bold"), anchor="center", padding=(0, SPACE_XS))
    style.configure("RowLabel.TLabel", background=BG_APP, foreground=TEXT_FAINT, font=FONT_SEAT,
                    anchor="center")
    style.configure("Legend.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_SMALL)
    style.configure("Divider.TFrame", background=BORDER)
    style.configure(
        "Vertical.TScrollbar", background=BG_SURFACE_ALT, troughcolor=BG_APP,
        bordercolor=BG_APP, lightcolor=BG_SURFACE_ALT, darkcolor=BG_SURFACE_ALT,
        arrowcolor=TEXT_MUTED,
    )
    style.map("Vertical.TScrollbar", background=[("active", BORDER)])

    # Bookings and receipts
    style.configure("PanelReference.TLabel", background=BG_SURFACE_ALT, foreground=ACCENT,
                    font=FONT_REFERENCE)
    style.configure("PanelMono.TLabel", background=BG_SURFACE_ALT, foreground=ACCENT,
                    font=(FONT_MONO[0], 11, "bold"))
    style.configure("Success.TLabel", background=BG_APP, foreground=TEXT_SUCCESS, font=FONT_HEADING)
    for name, background, foreground in (
        ("BadgeUpcoming.TLabel", "#14532d", TEXT_SUCCESS),
        ("BadgeCompleted.TLabel", BORDER, TEXT_MUTED),
        ("BadgeCanceled.TLabel", "#4c0d0d", TEXT_ERROR),
    ):
        style.configure(name, background=background, foreground=foreground,
                        font=(FONT_FAMILY, 9, "bold"), padding=(SPACE_SM, 2))
    return style


def center_window(root: tk.Tk, width: int, height: int) -> None:
    """Size the window and center it on the primary screen."""
    x = max((root.winfo_screenwidth() - width) // 2, 0)
    y = max((root.winfo_screenheight() - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")
