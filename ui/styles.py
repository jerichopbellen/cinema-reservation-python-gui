"""Visual identity: colors, fonts, spacing, and ttk style configuration.

Widgets should reference the named ttk styles defined in :func:`apply_theme`
(e.g. ``"Heading.TLabel"``) instead of hard-coding colors or fonts.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

APP_NAME = "CineRojo"
APP_TAGLINE = "Your seat is waiting."
WINDOW_TITLE = f"{APP_NAME} — Cinema Ticket Booking"
WINDOW_SIZE = (1100, 700)
WINDOW_MIN_SIZE = (900, 600)

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

# Typography (Segoe UI ships with Windows; Tk falls back gracefully elsewhere)
FONT_FAMILY = "Segoe UI"
FONT_BRAND = (FONT_FAMILY, 20, "bold")
FONT_DISPLAY = (FONT_FAMILY, 28, "bold")
FONT_HEADING = (FONT_FAMILY, 14, "bold")
FONT_BODY = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_NAV = (FONT_FAMILY, 11, "bold")

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
    style.configure("Nav.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED, font=FONT_NAV)
    style.configure("NavHint.TLabel", background=BG_SURFACE, foreground=TEXT_FAINT, font=FONT_SMALL)

    style.configure("Display.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_DISPLAY)
    style.configure("Tagline.TLabel", background=BG_APP, foreground=ACCENT, font=FONT_HEADING)
    style.configure("Body.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_BODY)

    style.configure("PanelHeading.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_HEADING)
    style.configure("PanelBody.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_MUTED,
                    font=FONT_BODY)
    style.configure("Status.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_SUCCESS,
                    font=FONT_HEADING)

    style.configure("Footer.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED, font=FONT_SMALL)
    return style


def center_window(root: tk.Tk, width: int, height: int) -> None:
    """Size the window and center it on the primary screen."""
    x = max((root.winfo_screenwidth() - width) // 2, 0)
    y = max((root.winfo_screenheight() - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")
