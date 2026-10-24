"""Visual identity ("Screening Room"): colors, fonts, spacing, and ttk styles.

A strict black-and-white palette with one acid-yellow accent reserved for
selection and primary actions. Headlines use a heavy grotesque, body text the
Windows 11 UI font, and labels, prices, and references a monospace face.

Widgets reference the named ttk styles defined in :func:`apply_theme`
(e.g. ``"Heading.TLabel"``) instead of hard-coding colors or fonts. Font
families are resolved against what is installed when the theme is applied,
so the app degrades to older Windows fonts when newer ones are missing.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from utils.branding import APP_NAME, APP_TAGLINE

__all__ = ["APP_NAME", "APP_TAGLINE", "apply_theme", "center_window"]
WINDOW_TITLE = APP_NAME
WINDOW_SIZE = (1280, 800)
WINDOW_MIN_SIZE = (1180, 720)
SIDEBAR_WIDTH = 236

# Colors
BG_APP = "#0B0B0B"          # ground
BG_SURFACE = "#111111"      # sidebar
BG_SURFACE_ALT = "#1A1A1A"  # cards and panels
BG_RAISED = "#242424"       # secondary buttons, hover
BORDER = "#2E2E2E"
BORDER_STRONG = "#3A3A3A"
ACCENT = "#D4F74A"          # acid: selection and primary actions only
ACCENT_DARK = "#BCDD34"
ON_ACCENT = "#0B0B0B"
PAPER = "#F2F2F2"           # posters and receipts
TEXT_PRIMARY = "#F2F2F2"
TEXT_MUTED = "#A0A0A0"
TEXT_FAINT = "#828282"
TEXT_ERROR = "#FF6B6B"
TEXT_DISABLED = "#5A5A5A"

# Seat states (tk.Button colors; ttk buttons cannot be recolored per widget easily)
SEAT_AVAILABLE = BORDER_STRONG
SEAT_AVAILABLE_HOVER = "#4A4A4A"
SEAT_SELECTED = ACCENT
SEAT_SELECTED_HOVER = ACCENT_DARK
SEAT_BOOKED = BG_APP
SEAT_BOOKED_TEXT = TEXT_DISABLED

# Typography: (preferred family, fallbacks…). Resolved by apply_theme().
_DISPLAY_FAMILIES = ("Segoe UI Black", "Segoe UI")
_BODY_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
_SEMIBOLD_FAMILIES = ("Segoe UI Variable Display Semib", "Segoe UI Semibold", "Segoe UI")
_MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")
_ICON_FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

FONT_FAMILY = _BODY_FAMILIES[-1]
FONT_DISPLAY = (_DISPLAY_FAMILIES[-1], 30, "bold")
FONT_HEADING = (_SEMIBOLD_FAMILIES[-1], 14)
FONT_BODY = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_NAV = (_SEMIBOLD_FAMILIES[-1], 11)
FONT_BUTTON = (_SEMIBOLD_FAMILIES[-1], 11)
FONT_EYEBROW = (_MONO_FAMILIES[-1], 9)
FONT_SEAT = (_MONO_FAMILIES[-1], 9, "bold")
FONT_MONO = (_MONO_FAMILIES[-1], 10)
FONT_PRICE = (_MONO_FAMILIES[-1], 12, "bold")
FONT_REFERENCE = (_MONO_FAMILIES[-1], 20, "bold")
FONT_TOTAL = (_DISPLAY_FAMILIES[-1], 22, "bold")
FONT_ICON = (_ICON_FAMILIES[-1], 12)

# Icon glyphs (Segoe Fluent Icons / Segoe MDL2 Assets code points)
ICON_HOME = "\uE80F"
ICON_MOVIES = "\uE714"
ICON_BOOKINGS = "\uE787"
ICON_PROFILE = "\uE77B"
ICON_LOGOUT = "\uF3B1"
ICON_ADMIN = "\uE713"

# Spacing scale (pixels, 4/8-based)
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 40


def _first_available(families: tuple[str, ...], installed: set[str]) -> str:
    return next((family for family in families if family in installed), families[-1])


def _resolve_fonts(root: tk.Misc) -> None:
    """Swap the font tuples above to the best families installed on this machine."""
    global FONT_FAMILY, FONT_DISPLAY, FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_NAV
    global FONT_BUTTON, FONT_EYEBROW, FONT_SEAT, FONT_MONO, FONT_PRICE, FONT_REFERENCE
    global FONT_TOTAL, FONT_ICON
    installed = set(tkfont.families(root))
    display = _first_available(_DISPLAY_FAMILIES, installed)
    body = _first_available(_BODY_FAMILIES, installed)
    semibold = _first_available(_SEMIBOLD_FAMILIES, installed)
    mono = _first_available(_MONO_FAMILIES, installed)
    icon = _first_available(_ICON_FAMILIES, installed)

    FONT_FAMILY = body
    FONT_DISPLAY = (display, 30, "bold")
    FONT_HEADING = (semibold, 14)
    FONT_BODY = (body, 11)
    FONT_SMALL = (body, 9)
    FONT_NAV = (semibold, 11)
    FONT_BUTTON = (semibold, 11)
    FONT_EYEBROW = (mono, 9)
    FONT_SEAT = (mono, 9, "bold")
    FONT_MONO = (mono, 10)
    FONT_PRICE = (mono, 12, "bold")
    FONT_REFERENCE = (mono, 20, "bold")
    FONT_TOTAL = (display, 22, "bold")
    FONT_ICON = (icon, 12)


def apply_theme(root: tk.Tk) -> ttk.Style:
    """Resolve fonts, then configure the window background and all named ttk styles."""
    _resolve_fonts(root)
    root.configure(background=BG_APP)
    style = ttk.Style(root)
    # "clam" honors custom background colors on Windows; "vista" does not.
    style.theme_use("clam")

    style.configure(".", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_BODY)

    # Surfaces
    style.configure("App.TFrame", background=BG_APP)
    style.configure("Surface.TFrame", background=BG_SURFACE)
    style.configure("Panel.TFrame", background=BG_SURFACE_ALT)
    style.configure("Paper.TFrame", background=PAPER)
    style.configure("Accent.TFrame", background=ACCENT)
    style.configure("Danger.TFrame", background=TEXT_ERROR)
    style.configure("Divider.TFrame", background=BORDER)

    # Screen typography (on the app ground)
    style.configure("Display.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_DISPLAY)
    style.configure("Eyebrow.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_EYEBROW)
    style.configure("Heading.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_HEADING)
    style.configure("Tagline.TLabel", background=BG_APP, foreground=ACCENT, font=FONT_MONO)
    style.configure("Body.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_BODY)
    style.configure("Meta.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_BODY)
    style.configure("Price.TLabel", background=BG_APP, foreground=TEXT_PRIMARY, font=FONT_PRICE)

    # Panel typography
    style.configure("PanelHeading.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_HEADING)
    style.configure("PanelDisplay.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=(FONT_DISPLAY[0], 26, "bold"))
    style.configure("PanelEyebrow.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_MUTED,
                    font=FONT_EYEBROW)
    style.configure("PanelBody.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_MUTED,
                    font=FONT_BODY)
    style.configure("PanelField.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_BODY)
    style.configure("PanelValue.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_HEADING)
    style.configure("PanelHint.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_FAINT,
                    font=FONT_SMALL)
    style.configure("PanelError.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_ERROR,
                    font=FONT_SMALL)
    style.configure("PanelSuccess.TLabel", background=BG_SURFACE_ALT, foreground=ACCENT,
                    font=FONT_BODY)
    style.configure("PanelFailure.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_ERROR,
                    font=FONT_BODY)
    style.configure("PanelPrice.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_PRICE)
    style.configure("PanelTotal.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_TOTAL)
    style.configure("PanelReference.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_REFERENCE)
    style.configure("PanelMono.TLabel", background=BG_SURFACE_ALT, foreground=TEXT_MUTED,
                    font=FONT_MONO)

    # Inputs
    style.configure(
        "TEntry",
        fieldbackground=BG_APP, foreground=TEXT_PRIMARY, insertcolor=ACCENT,
        bordercolor=BORDER_STRONG, lightcolor=BG_APP, darkcolor=BG_APP, padding=(10, 8),
        selectbackground=ACCENT, selectforeground=ON_ACCENT,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", ACCENT), ("hover", TEXT_FAINT)],
        lightcolor=[("focus", ACCENT)],
    )

    # Dropdowns (read-only comboboxes) and their pop-up lists
    style.configure(
        "TCombobox", fieldbackground=BG_APP, background=BG_RAISED, foreground=TEXT_PRIMARY,
        arrowcolor=TEXT_PRIMARY, bordercolor=BORDER_STRONG, lightcolor=BG_APP, darkcolor=BG_APP,
        padding=(10, 8), selectbackground=BG_APP, selectforeground=TEXT_PRIMARY,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", BG_APP)], foreground=[("readonly", TEXT_PRIMARY)],
        selectbackground=[("readonly", BG_APP)], selectforeground=[("readonly", TEXT_PRIMARY)],
        bordercolor=[("focus", ACCENT), ("hover", TEXT_FAINT)], background=[("active", BORDER)],
    )
    root.option_add("*TCombobox*Listbox.background", BG_SURFACE_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)
    root.option_add("*TCombobox*Listbox.font", FONT_BODY)

    # Buttons
    style.configure(
        "Accent.TButton", background=ACCENT, foreground=ON_ACCENT, font=FONT_BUTTON,
        borderwidth=0, focusthickness=0, padding=(SPACE_LG - 4, 10),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", BORDER), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
        foreground=[("disabled", TEXT_DISABLED)],
    )
    style.configure(
        "Secondary.TButton", background=BG_RAISED, foreground=TEXT_PRIMARY, font=FONT_BUTTON,
        bordercolor=BORDER_STRONG, lightcolor=BG_RAISED, darkcolor=BG_RAISED,
        focusthickness=0, padding=(SPACE_LG - 4, 9),
    )
    style.map("Secondary.TButton",
              background=[("disabled", BG_SURFACE_ALT), ("pressed", BORDER_STRONG), ("active", BORDER)],
              bordercolor=[("active", TEXT_FAINT)],
              foreground=[("disabled", TEXT_DISABLED)])
    # Same look, tighter padding and no minimum width, for buttons inside table rows.
    style.configure("Compact.TButton", background=BG_RAISED, foreground=TEXT_PRIMARY, font=FONT_NAV,
                    bordercolor=BORDER_STRONG, lightcolor=BG_RAISED, darkcolor=BG_RAISED,
                    focusthickness=0, padding=(SPACE_MD - 2, 6), width=0)
    style.map("Compact.TButton",
              background=[("pressed", BORDER_STRONG), ("active", BORDER)],
              bordercolor=[("active", TEXT_FAINT)])
    # Text-style links. width=0 overrides clam's 11-character minimum so links size to their text.
    for name, surface in (("Link.TButton", BG_SURFACE_ALT), ("AppLink.TButton", BG_APP)):
        style.configure(name, background=surface, foreground=ACCENT, font=FONT_NAV,
                        borderwidth=0, focusthickness=0, padding=0, width=0)
        style.map(name, background=[("active", surface), ("disabled", surface)],
                  foreground=[("disabled", TEXT_DISABLED), ("active", TEXT_PRIMARY)])

    # Showtime tiles: the whole tile is the button
    style.configure("Showtime.TButton", background=BG_SURFACE_ALT, foreground=TEXT_PRIMARY,
                    font=FONT_BUTTON, bordercolor=BORDER, lightcolor=BG_SURFACE_ALT,
                    darkcolor=BG_SURFACE_ALT, focusthickness=0, padding=(SPACE_MD, 14), justify="center")
    style.map("Showtime.TButton", background=[("pressed", BORDER), ("active", BG_RAISED)],
              bordercolor=[("active", ACCENT), ("focus", ACCENT)])

    # Sidebar
    style.configure("SideEyebrow.TLabel", background=BG_SURFACE, foreground=TEXT_FAINT, font=FONT_EYEBROW)
    style.configure("SideUser.TLabel", background=BG_SURFACE, foreground=TEXT_PRIMARY, font=FONT_NAV)
    style.configure("SideMeta.TLabel", background=BG_SURFACE, foreground=TEXT_MUTED, font=FONT_MONO)
    style.configure("Avatar.TLabel", background=BORDER_STRONG, foreground=TEXT_PRIMARY,
                    font=FONT_BUTTON, anchor="center", width=3, padding=(0, 6))

    # Auth hero (paper panel)
    style.configure("PaperDisplay.TLabel", background=PAPER, foreground=ON_ACCENT,
                    font=(FONT_DISPLAY[0], 44, "bold"))
    style.configure("PaperBody.TLabel", background=PAPER, foreground="#3A3A3A", font=FONT_BODY)
    style.configure("PaperEyebrow.TLabel", background=PAPER, foreground="#4A4A4A", font=FONT_EYEBROW)

    # Seating
    style.configure("Screen.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_EYEBROW,
                    anchor="center", padding=(0, SPACE_XS))
    style.configure("RowLabel.TLabel", background=BG_APP, foreground=TEXT_FAINT, font=FONT_SEAT,
                    anchor="center")
    style.configure("Legend.TLabel", background=BG_APP, foreground=TEXT_MUTED, font=FONT_MONO)
    style.configure(
        "Vertical.TScrollbar", background=BG_RAISED, troughcolor=BG_APP, bordercolor=BG_APP,
        lightcolor=BG_RAISED, darkcolor=BG_RAISED, arrowcolor=TEXT_MUTED, gripcount=0,
    )
    style.map("Vertical.TScrollbar", background=[("active", BORDER_STRONG)])

    # Booking status badges: acid = upcoming, steel = completed, red outline tone = canceled
    for name, background, foreground in (
        ("BadgeUpcoming.TLabel", ACCENT, ON_ACCENT),
        ("BadgeCompleted.TLabel", BORDER_STRONG, TEXT_PRIMARY),
        ("BadgeCanceled.TLabel", "#3A1515", TEXT_ERROR),
    ):
        style.configure(name, background=background, foreground=foreground,
                        font=FONT_SEAT, padding=(SPACE_SM, 2))

    # Toasts
    style.configure("Toast.TFrame", background=BG_RAISED)
    style.configure("Toast.TLabel", background=BG_RAISED, foreground=TEXT_PRIMARY, font=FONT_BODY)
    style.configure("ToastError.TLabel", background=BG_RAISED, foreground=TEXT_ERROR, font=FONT_BODY)
    return style


def center_window(root: tk.Tk, width: int, height: int) -> None:
    """Size the window (shrinking it to fit small screens) and center it."""
    width = min(width, root.winfo_screenwidth() - 40)
    height = min(height, root.winfo_screenheight() - 80)
    x = max((root.winfo_screenwidth() - width) // 2, 0)
    y = max((root.winfo_screenheight() - height) // 3, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")

