"""The Cinemalaya logo: an acid ticket stub with a bold "C", beside the wordmark.

Everything is drawn with Tk primitives (no image files). The stub's side
notches are circles filled with the surrounding background color, so the logo
must be told what it sits on.
"""

from __future__ import annotations

import math
import tkinter as tk

from ui import styles
from utils.branding import APP_NAME

TAGLINE = "TICKETS · SEATS"


def ticket_stub(master: tk.Misc, size: int, background: str) -> tk.Canvas:
    """The square acid stub with notched sides and a bold "C"."""
    canvas = tk.Canvas(master, width=size, height=size, background=background,
                       highlightthickness=0, borderwidth=0)
    canvas.create_rectangle(0, 0, size, size, fill=styles.ACCENT, width=0)
    notch = max(size // 8, 3)
    middle = size / 2
    for x in (0, size):
        canvas.create_oval(x - notch, middle - notch, x + notch, middle + notch,
                           fill=background, width=0)
    canvas.create_text(middle, middle + 1, text="C", fill=styles.ON_ACCENT,
                       font=(styles.FONT_DISPLAY[0], -int(size * 0.56), "bold"))
    return canvas


def logo(master: tk.Misc, *, background: str, foreground: str, large: bool = False,
         tagline_color: str | None = None) -> tk.Frame:
    """Stub plus wordmark. The large version (login screen) adds the mono tagline."""
    frame = tk.Frame(master, background=background)
    ticket_stub(frame, 52 if large else 26, background).pack(side="left")
    words = tk.Frame(frame, background=background)
    words.pack(side="left", padx=(14 if large else 10, 0))
    tk.Label(words, text=APP_NAME.upper(), background=background, foreground=foreground,
             font=(styles.FONT_DISPLAY[0], 24 if large else 13, "bold"),
             padx=0, pady=0, borderwidth=0).pack(anchor="w")
    if large:
        # Tk has no letter-spacing, so the tracking is written into the text.
        tk.Label(words, text=" ".join(TAGLINE),
                 background=background, foreground=tagline_color or styles.TEXT_MUTED,
                 font=styles.FONT_EYEBROW, padx=0, pady=0, borderwidth=0).pack(anchor="w")
    return frame


def app_icon(root: tk.Misc, size: int = 32) -> tk.PhotoImage:
    """The window icon: the ticket stub drawn pixel by pixel on black."""
    margin = size // 10
    notch = size / 10
    middle = (size - 1) / 2
    ring_outer, ring_inner = size * 0.27, size * 0.15
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            color = styles.BG_APP
            inside = margin <= x < size - margin and margin <= y < size - margin
            notched = any(math.hypot(x - edge, y - middle) <= notch
                          for edge in (margin - 0.5, size - margin - 0.5))
            if inside and not notched:
                color = styles.ACCENT
                distance = math.hypot(x - middle, y - middle)
                opening = x > middle and abs(y - middle) < size * 0.11
                if ring_inner <= distance <= ring_outer and not opening:
                    color = styles.ON_ACCENT
            row.append(color)
        rows.append("{" + " ".join(row) + "}")
    icon = tk.PhotoImage(master=root, width=size, height=size)
    icon.put(" ".join(rows))
    return icon
