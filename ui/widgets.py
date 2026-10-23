"""Reusable widgets and helpers shared by the screens."""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from services.errors import UserFacingError
from ui import styles

logger = logging.getLogger(__name__)

DATABASE_ERROR_MESSAGE = "Something went wrong while accessing the database. Please try again."
UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred. Please try again."

# Failures a screen can explain to the user. Anything else is a programming
# defect and is left to propagate to the Tk error handler installed by App.
EXPECTED_ERRORS: tuple[type[Exception], ...] = (UserFacingError, sqlite3.Error)


def wrap_to_container(label: ttk.Label, container: tk.Misc | None = None, margin: int = 0) -> None:
    """Keep ``label`` wrapped to its container's current width instead of a fixed pixel width."""
    container = container or label.master

    def on_resize(event: tk.Event) -> None:
        width = event.width - margin
        if width > 40:
            label.configure(wraplength=width)

    container.bind("<Configure>", on_resize, add="+")


def run_in_background(widget: tk.Misc, task: Callable[[], Any],
                      on_success: Callable[[Any], None],
                      on_error: Callable[[Exception], None]) -> None:
    """Run ``task`` on a worker thread and deliver its result on the Tk thread.

    Keeps the window responsive during slow work such as password hashing.
    Callbacks are skipped if ``widget`` was destroyed in the meantime (for
    example, the user navigated away or closed the window).
    """
    results: queue.SimpleQueue[tuple[bool, Any]] = queue.SimpleQueue()

    def worker() -> None:
        try:
            results.put((True, task()))
        except Exception as exc:  # delivered to on_error on the Tk thread
            results.put((False, exc))

    def poll() -> None:
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            ok, value = results.get_nowait()
        except queue.Empty:
            widget.after(40, poll)
            return
        (on_success if ok else on_error)(value)

    threading.Thread(target=worker, daemon=True).start()
    widget.after(40, poll)


def user_message_for(exc: Exception) -> str:
    """Return a safe message for the UI, logging anything that is not a user error."""
    if isinstance(exc, UserFacingError):
        return str(exc)
    if isinstance(exc, sqlite3.Error):
        logger.error("Database operation failed", exc_info=exc)
        return DATABASE_ERROR_MESSAGE
    logger.error("Unexpected error", exc_info=exc)
    return UNEXPECTED_ERROR_MESSAGE


class FormField(ttk.Frame):
    """A labeled entry with a single line below it for a hint or an error."""

    def __init__(self, master: tk.Misc, label: str, *, hint: str = "", secret: bool = False,
                 width: int = 36, wraplength: int = 340) -> None:
        super().__init__(master, style="Panel.TFrame")
        self._hint = hint
        self.var = tk.StringVar()

        ttk.Label(self, text=label, style="PanelField.TLabel").pack(anchor="w")
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, show="•" if secret else "")
        self.entry.pack(fill="x", pady=(styles.SPACE_XS, 2))
        # The message line is only packed while it has text, so fields without hints stay compact.
        self._message = ttk.Label(self, style="PanelHint.TLabel", wraplength=wraplength,
                                  justify="left")
        wrap_to_container(self._message, self)
        self.clear_error()

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def clear(self) -> None:
        self.var.set("")

    def show_error(self, message: str) -> None:
        self._set_message(message, "PanelError.TLabel")

    def clear_error(self) -> None:
        self._set_message(self._hint, "PanelHint.TLabel")

    def _set_message(self, text: str, style: str) -> None:
        self._message.configure(text=text, style=style)
        if text:
            self._message.pack(anchor="w")
        else:
            self._message.pack_forget()


class StatusMessage(ttk.Label):
    """A one-line success/error message inside a panel."""

    def __init__(self, master: tk.Misc, wraplength: int = 340) -> None:
        super().__init__(master, text="", style="PanelSuccess.TLabel",
                         wraplength=wraplength, justify="left")

    def success(self, message: str) -> None:
        self.configure(text=message, style="PanelSuccess.TLabel")

    def error(self, message: str) -> None:
        self.configure(text=message, style="PanelFailure.TLabel")

    def clear(self) -> None:
        self.configure(text="")


class Form:
    """Groups fields with a submit button so errors and busy state are handled uniformly."""

    def __init__(self, fields: dict[str, FormField], status: StatusMessage,
                 button: ttk.Button, busy_text: str) -> None:
        self.fields = fields
        self.status = status
        self.button = button
        self._idle_text = str(button.cget("text"))
        self._busy_text = busy_text
        self.busy = False

    def values(self) -> dict[str, str]:
        return {name: field.get() for name, field in self.fields.items()}

    def begin(self) -> bool:
        """Enter the busy state. Returns False if a submission is already running."""
        if self.busy:
            return False
        self.busy = True
        self.button.state(["disabled"])
        self.button.configure(text=self._busy_text)
        self.status.clear()
        for field in self.fields.values():
            field.clear_error()
        return True

    def end(self) -> None:
        self.busy = False
        self.button.state(["!disabled"])
        self.button.configure(text=self._idle_text)

    def show_error(self, exc: Exception) -> None:
        """Show ``exc`` next to its field when it names one, otherwise in the status line."""
        message = user_message_for(exc)
        field = self.fields.get(getattr(exc, "field", ""))
        if field is not None:
            field.show_error(message)
            field.entry.focus_set()
        else:
            self.status.error(message)

    def bind_submit(self, callback: Callable[[], None]) -> None:
        """Submit on Return from any field, and on button click."""
        self.button.configure(command=callback)
        for field in self.fields.values():
            field.entry.bind("<Return>", lambda _event: callback())


def panel(master: tk.Misc, title: str, subtitle: str = "", wraplength: int = 340) -> ttk.Frame:
    """Create a padded Panel frame with a heading and optional muted subtitle."""
    frame = ttk.Frame(master, style="Panel.TFrame", padding=styles.SPACE_LG)
    ttk.Label(frame, text=title, style="PanelHeading.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PanelBody.TLabel", wraplength=wraplength,
                  justify="left").pack(anchor="w", pady=(styles.SPACE_XS, 0))
    return frame


def screen_title(master: tk.Misc, title: str, back_text: str = "",
                 back_command: Callable[[], None] | None = None, *,
                 subtitle: str = "", eyebrow: str = "") -> ttk.Frame:
    """The standard screen header: back link, small mono eyebrow, large title, muted subtitle."""
    header = ttk.Frame(master, style="App.TFrame")
    if back_command is not None:
        ttk.Button(header, text=back_text, style="AppLink.TButton", cursor="hand2",
                   command=back_command).pack(anchor="w", pady=(0, styles.SPACE_MD))
    if eyebrow:
        ttk.Label(header, text=eyebrow.upper(), style="Eyebrow.TLabel").pack(anchor="w")
    ttk.Label(header, text=title, style="Display.TLabel", wraplength=820, justify="left").pack(anchor="w")
    if subtitle:
        ttk.Label(header, text=subtitle, style="Meta.TLabel", wraplength=820, justify="left").pack(
            anchor="w", pady=(2, 0))
    return header


def message_panel(master: tk.Misc, title: str, message: str, *, error: bool = False) -> ttk.Frame:
    """A panel for empty states and load failures."""
    frame = ttk.Frame(master, style="Panel.TFrame", padding=styles.SPACE_LG)
    ttk.Label(frame, text=title, style="PanelHeading.TLabel").pack(anchor="w")
    ttk.Label(frame, text=message, style="PanelFailure.TLabel" if error else "PanelBody.TLabel",
              wraplength=640, justify="left").pack(anchor="w", pady=(styles.SPACE_XS, 0))
    return frame


class ScrollFrame(ttk.Frame):
    """A vertically scrollable area. Add children to :attr:`body`.

    The scrollbar only appears when the content is taller than the visible area,
    and the mouse wheel scrolls while the pointer is anywhere over the frame,
    including over its child widgets.
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, style="App.TFrame")
        self._canvas = tk.Canvas(self, background=styles.BG_APP, highlightthickness=0, borderwidth=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)

        self.body = ttk.Frame(self._canvas, style="App.TFrame")
        self._window = self._canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_resize)
        self._canvas.bind("<Configure>", self._on_resize)
        # <Enter>/<Leave> also fire when the pointer crosses into child widgets, so
        # bind once and check containment instead of rebinding on every crossing.
        self.bind_all("<MouseWheel>", self._on_wheel)

    def _on_resize(self, _event: tk.Event) -> None:
        self._canvas.itemconfigure(self._window, width=self._canvas.winfo_width())
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        overflowing = self.body.winfo_reqheight() > self._canvas.winfo_height()
        if overflowing and not self._scrollbar.winfo_ismapped():
            self._scrollbar.pack(side="right", fill="y", before=self._canvas)
        elif not overflowing and self._scrollbar.winfo_ismapped():
            self._scrollbar.pack_forget()
            self._canvas.yview_moveto(0)

    def _contains_pointer(self, event: tk.Event) -> bool:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                return True
            widget = widget.master
        return False

    def _on_wheel(self, event: tk.Event) -> None:
        if self._scrollbar.winfo_ismapped() and self._contains_pointer(event):
            self._canvas.yview_scroll(int(-event.delta / 120), "units")

    def destroy(self) -> None:
        self.unbind_all("<MouseWheel>")
        super().destroy()


class NavItem(tk.Frame):
    """A sidebar row: icon glyph and label, with hover and an acid marker when active.

    Built from plain tk widgets because ttk cannot mix two fonts in one button.
    It is keyboard-focusable and activates with Return or Space like a button.
    """

    def __init__(self, master: tk.Misc, icon: str, text: str, command: Callable[[], None], *,
                 active: bool = False) -> None:
        self._idle_bg = styles.BG_SURFACE_ALT if active else styles.BG_SURFACE
        super().__init__(master, background=self._idle_bg, cursor="hand2", takefocus=1,
                         highlightthickness=1, highlightbackground=self._idle_bg,
                         highlightcolor=styles.ACCENT)
        self.text = text
        self._command = command
        self._active = active
        self._marker = tk.Frame(self, width=3, background=styles.ACCENT if active else self._idle_bg)
        self._marker.pack(side="left", fill="y")
        self._icon = tk.Label(self, text=icon, font=styles.FONT_ICON, background=self._idle_bg,
                              foreground=styles.ACCENT if active else styles.TEXT_MUTED)
        self._icon.pack(side="left", padx=(styles.SPACE_MD - 3, styles.SPACE_SM), pady=10)
        self._label = tk.Label(self, text=text, font=styles.FONT_NAV, background=self._idle_bg,
                               foreground=styles.TEXT_PRIMARY if active else styles.TEXT_MUTED)
        self._label.pack(side="left", pady=10)
        for widget in (self, self._icon, self._label):
            widget.bind("<Button-1>", lambda _e: self.invoke())
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))
        self.bind("<Return>", lambda _e: self.invoke())
        self.bind("<space>", lambda _e: self.invoke())

    def invoke(self) -> None:
        self._command()

    def _hover(self, inside: bool) -> None:
        try:
            background = styles.BG_SURFACE_ALT if inside else self._idle_bg
            for widget in (self, self._icon, self._label):
                widget.configure(background=background)
            self._label.configure(foreground=styles.TEXT_PRIMARY if inside or self._active
                                  else styles.TEXT_MUTED)
            if not self._active:
                self._marker.configure(background=background)
        except tk.TclError:
            pass  # the item was destroyed by the navigation it triggered
