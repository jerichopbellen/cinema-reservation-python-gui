"""Screen manager for the single application window.

Exactly one screen is shown at a time. Switching screens destroys the previous
screen's widgets, so password fields and stale profile data never linger.
Authenticated screens go through :meth:`App._show_protected`, which redirects
to the login screen when there is no active session. They are framed by a
sidebar with navigation and the signed-in account; the login and registration
screens use the whole window.

Unexpected exceptions raised in Tk callbacks are logged with a traceback and
reported to the user with a plain message; tracebacks are never shown.
"""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from services.auth_service import AuthService, User, UserNotFoundError
from services.booking_service import BookingService
from services.catalog_service import CatalogService
from services.movie_admin_service import MovieAdminService
from services.showtime_admin_service import ShowtimeAdminService
from services.seating_service import SeatingService
from services.session import Session
from ui import brand, styles
from ui.admin_views import (
    AdminMoviesView,
    AdminShowtimeBookingsView,
    AdminShowtimesView,
    MovieFormView,
)
from ui.auth_views import LoginView, RegisterView
from ui.booking_views import BookingsView, CheckoutView, ConfirmationView, ReceiptView
from ui.main_view import HomeView
from ui.movie_views import MoviesView, ShowtimesView
from ui.profile_view import ProfileView, initials
from ui.seating_view import SeatingView
from ui.widgets import DATABASE_ERROR_MESSAGE, UNEXPECTED_ERROR_MESSAGE, NavItem
from utils.formatting import truncate

logger = logging.getLogger(__name__)

MOVIE_SCREENS = ("movies", "showtimes", "seating", "checkout", "confirmation")
BOOKING_SCREENS = ("bookings", "receipt")
ADMIN_SCREENS = ("admin_movies", "movie_form", "admin_showtimes", "showtime_bookings")
SIDEBAR_NAME_LIMIT = 16  # fits beside the avatar at the sidebar's fixed width
TOAST_MILLISECONDS = 3500


class App:
    """Owns the root window's sidebar, content area, and toasts, and handles navigation."""

    def __init__(self, root: tk.Tk, auth: AuthService, session: Session, db_path: Path) -> None:
        self.root = root
        self.auth = auth
        self.session = session
        self.db_path = db_path
        self.catalog = CatalogService(db_path)
        self.seating = SeatingService(db_path, self.catalog)
        self.bookings = BookingService(db_path, self.catalog)
        self.movie_admin = MovieAdminService(db_path, auth)
        self.showtime_admin = ShowtimeAdminService(db_path, auth, now=self.catalog.now)

        self._sidebar = ttk.Frame(root, style="Surface.TFrame", width=styles.SIDEBAR_WIDTH)
        self._sidebar.pack_propagate(False)
        self._divider = ttk.Frame(root, style="Divider.TFrame", width=1)
        self._content = ttk.Frame(root, style="App.TFrame")
        self._content.pack(side="right", fill="both", expand=True)

        self.nav_items: dict[str, NavItem] = {}
        self._screen: ttk.Frame | None = None
        self._current = ""
        self._toast: ttk.Frame | None = None
        self._toast_timer: str | None = None
        root.report_callback_exception = self._on_callback_error

    # --- Public navigation ----------------------------------------------------

    def show_login(self, message: str = "", username: str = "") -> None:
        self._show("login", lambda parent: LoginView(parent, self, message=message, username=username))

    def show_register(self) -> None:
        self._show("register", lambda parent: RegisterView(parent, self))

    def show_home(self) -> None:
        self._show_protected("home", lambda parent, user: HomeView(parent, self, user))

    def show_profile(self) -> None:
        self._show_protected("profile", lambda parent, user: ProfileView(parent, self, user))

    def show_movies(self) -> None:
        self._show_protected("movies", lambda parent, _user: MoviesView(parent, self))

    def show_showtimes(self, movie_id: int) -> None:
        self._show_protected("showtimes", lambda parent, _user: ShowtimesView(parent, self, movie_id))

    def show_seating(self, showtime_id: int) -> None:
        self._show_protected("seating", lambda parent, _user: SeatingView(parent, self, showtime_id))

    def show_checkout(self) -> None:
        self._show_protected("checkout", lambda parent, user: CheckoutView(parent, self, user))

    def show_confirmation(self, booking_id: int) -> None:
        self._show_protected("confirmation",
                             lambda parent, user: ConfirmationView(parent, self, user, booking_id))

    def show_bookings(self) -> None:
        self._show_protected("bookings", lambda parent, user: BookingsView(parent, self, user))

    def show_receipt(self, booking_id: int, back_to: str = "bookings") -> None:
        self._show_protected("receipt",
                             lambda parent, user: ReceiptView(parent, self, user, booking_id, back_to))

    def show_admin_movies(self) -> None:
        self._show_admin("admin_movies", lambda parent, user: AdminMoviesView(parent, self, user))

    def show_movie_form(self, movie_id: int | None = None) -> None:
        self._show_admin("movie_form",
                         lambda parent, user: MovieFormView(parent, self, user, movie_id))

    def show_admin_showtimes(self, movie_id: int) -> None:
        self._show_admin("admin_showtimes",
                         lambda parent, user: AdminShowtimesView(parent, self, user, movie_id))

    def show_showtime_bookings(self, showtime_id: int) -> None:
        self._show_admin("showtime_bookings",
                         lambda parent, user: AdminShowtimeBookingsView(parent, self, user, showtime_id))

    def login(self, user: User) -> None:
        self.session.login(user)
        self.show_home()

    def logout(self, message: str = "You have been logged out.") -> None:
        self.session.logout()
        self.show_login(message=message)

    def on_user_updated(self, user: User) -> None:
        """Refresh session and sidebar after the signed-in user's details change."""
        self.session.update_user(user)
        self._render_sidebar()

    def toast(self, message: str, *, error: bool = False) -> None:
        """Show a brief notification in the bottom-right corner that dismisses itself."""
        self._dismiss_toast()
        toast = ttk.Frame(self.root, style="Toast.TFrame")
        ttk.Frame(toast, style="Danger.TFrame" if error else "Accent.TFrame", width=4).pack(
            side="left", fill="y")
        ttk.Label(toast, text=message, style="ToastError.TLabel" if error else "Toast.TLabel",
                  wraplength=380, justify="left").pack(side="left", padx=styles.SPACE_MD,
                                                        pady=styles.SPACE_MD - 4)
        toast.place(relx=1.0, rely=1.0, x=-styles.SPACE_LG, y=-styles.SPACE_LG, anchor="se")
        toast.lift()
        self._toast = toast
        self._toast_timer = self.root.after(TOAST_MILLISECONDS, self._dismiss_toast)

    # --- Internals ------------------------------------------------------------

    def _dismiss_toast(self) -> None:
        if self._toast_timer is not None:
            self.root.after_cancel(self._toast_timer)
            self._toast_timer = None
        if self._toast is not None:
            self._toast.destroy()
            self._toast = None

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        logger.error("Unhandled error on screen %r", self._current, exc_info=(exc_type, exc, tb))
        messagebox.showerror("Unexpected error", UNEXPECTED_ERROR_MESSAGE, parent=self.root)

    def _show_protected(self, name: str, build: Callable[[ttk.Frame, User], ttk.Frame]) -> None:
        if not self.session.is_authenticated:
            self.show_login(message="Please log in to continue.")
            return
        try:
            # Reload from the database so every protected screen reflects current data.
            user = self.auth.get_user(self.session.require_user().id)
        except UserNotFoundError as exc:
            self.logout(message=str(exc))
            return
        except sqlite3.Error:
            logger.exception("Could not load the signed-in user")
            messagebox.showerror("Could not open screen", DATABASE_ERROR_MESSAGE, parent=self.root)
            return
        self.session.update_user(user)
        self._show(name, lambda parent: build(parent, user))

    def _show_admin(self, name: str, build: Callable[[ttk.Frame, User], ttk.Frame]) -> None:
        """Like _show_protected, but only for administrators (role re-read from the database).

        This only decides what to display; the admin service re-checks the role
        on every operation regardless.
        """
        if self.session.is_authenticated:
            try:
                user = self.auth.get_user(self.session.require_user().id)
            except (UserNotFoundError, sqlite3.Error):
                user = None  # _show_protected reports these properly
            if user is not None and not user.is_admin:
                self.show_home()
                self.toast("Administrator access is required for that screen.", error=True)
                return
        self._show_protected(name, build)

    def _show(self, name: str, build: Callable[[ttk.Frame], ttk.Frame]) -> None:
        if self._screen is not None:
            self._screen.destroy()
        self._current = name
        self._render_sidebar()
        self._screen = build(self._content)
        self._screen.pack(fill="both", expand=True)

    def _render_sidebar(self) -> None:
        for child in self._sidebar.winfo_children():
            child.destroy()
        self.nav_items = {}
        user = self.session.user
        if user is None:
            self._sidebar.pack_forget()
            self._divider.pack_forget()
            return
        if not self._sidebar.winfo_ismapped():
            self._sidebar.pack(side="left", fill="y", before=self._content)
            self._divider.pack(side="left", fill="y", before=self._content)

        header = ttk.Frame(self._sidebar, style="Surface.TFrame", padding=(styles.SPACE_LG, 28))
        header.pack(fill="x")
        brand.logo(header, background=styles.BG_SURFACE, foreground=styles.TEXT_PRIMARY).pack(
            side="left")

        ttk.Label(self._sidebar, text="MENU", style="SideEyebrow.TLabel").pack(
            anchor="w", padx=styles.SPACE_LG, pady=(0, styles.SPACE_SM))
        for icon, text, screens, command in (
            (styles.ICON_HOME, "Home", ("home",), self.show_home),
            (styles.ICON_MOVIES, "Movies", MOVIE_SCREENS, self.show_movies),
            (styles.ICON_BOOKINGS, "My Bookings", BOOKING_SCREENS, self.show_bookings),
            (styles.ICON_PROFILE, "Profile", ("profile",), self.show_profile),
        ):
            item = NavItem(self._sidebar, icon, text, command, active=self._current in screens)
            item.pack(fill="x", padx=styles.SPACE_SM, pady=1)
            self.nav_items[text] = item

        if user.is_admin:
            ttk.Label(self._sidebar, text="ADMIN", style="SideEyebrow.TLabel").pack(
                anchor="w", padx=styles.SPACE_LG, pady=(styles.SPACE_LG, styles.SPACE_SM))
            item = NavItem(self._sidebar, styles.ICON_ADMIN, "Manage Movies", self.show_admin_movies,
                           active=self._current in ADMIN_SCREENS)
            item.pack(fill="x", padx=styles.SPACE_SM, pady=1)
            self.nav_items["Manage Movies"] = item

        footer = ttk.Frame(self._sidebar, style="Surface.TFrame", padding=(styles.SPACE_SM, 0))
        footer.pack(side="bottom", fill="x", pady=(0, styles.SPACE_LG))
        logout = NavItem(footer, styles.ICON_LOGOUT, "Log out", self.logout)
        logout.pack(fill="x", side="bottom")
        self.nav_items["Log out"] = logout

        account = ttk.Frame(footer, style="Surface.TFrame", padding=(styles.SPACE_MD, styles.SPACE_MD))
        account.pack(fill="x", side="bottom")
        ttk.Label(account, text=initials(user.full_name), style="Avatar.TLabel").pack(side="left")
        names = ttk.Frame(account, style="Surface.TFrame")
        names.pack(side="left", padx=(styles.SPACE_SM + 4, 0))
        ttk.Label(names, text=truncate(user.full_name, SIDEBAR_NAME_LIMIT), style="SideUser.TLabel").pack(anchor="w")
        ttk.Label(names, text=f"@{truncate(user.username, SIDEBAR_NAME_LIMIT - 1)}",
                  style="SideMeta.TLabel").pack(anchor="w")
        ttk.Frame(footer, style="Divider.TFrame", height=1).pack(fill="x", side="bottom",
                                                                  padx=styles.SPACE_SM)
