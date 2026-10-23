"""Screen manager for the single application window.

Exactly one screen is shown at a time. Switching screens destroys the previous
screen's widgets, so password fields and stale profile data never linger.
Authenticated screens go through :meth:`App._show_protected`, which redirects
to the login screen when there is no active session.
"""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from services.auth_service import AuthService, User, UserNotFoundError
from services.session import Session
from ui import styles
from ui.auth_views import LoginView, RegisterView
from ui.main_view import HomeView
from ui.profile_view import ProfileView
from ui.widgets import DATABASE_ERROR_MESSAGE

logger = logging.getLogger(__name__)

PLACEHOLDER_SECTIONS = ("Movies", "My Bookings")


class App:
    """Owns the root window's header, content area, and footer, and handles navigation."""

    def __init__(self, root: tk.Tk, auth: AuthService, session: Session, db_path: Path) -> None:
        self.root = root
        self.auth = auth
        self.session = session
        self.db_path = db_path

        self._header = ttk.Frame(root, style="Surface.TFrame")
        self._header.pack(fill="x")
        ttk.Frame(root, style="Accent.TFrame", height=3).pack(fill="x")
        self._build_footer()
        self._content = ttk.Frame(root, style="App.TFrame")
        self._content.pack(fill="both", expand=True)

        self._screen: ttk.Frame | None = None
        self._current = ""

    # --- Public navigation ----------------------------------------------------

    def show_login(self, message: str = "", username: str = "") -> None:
        self._show("login", lambda parent: LoginView(parent, self, message=message, username=username))

    def show_register(self) -> None:
        self._show("register", lambda parent: RegisterView(parent, self))

    def show_home(self) -> None:
        self._show_protected("home", lambda parent, user: HomeView(parent, self, user))

    def show_profile(self) -> None:
        self._show_protected("profile", lambda parent, user: ProfileView(parent, self, user))

    def login(self, user: User) -> None:
        self.session.login(user)
        self.show_home()

    def logout(self, message: str = "You have been logged out.") -> None:
        self.session.logout()
        self.show_login(message=message)

    def on_user_updated(self, user: User) -> None:
        """Refresh session and header after the signed-in user's details change."""
        self.session.update_user(user)
        self._render_header()

    # --- Internals ------------------------------------------------------------

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
            messagebox.showerror(styles.APP_NAME, DATABASE_ERROR_MESSAGE, parent=self.root)
            return
        self.session.update_user(user)
        self._show(name, lambda parent: build(parent, user))

    def _show(self, name: str, build: Callable[[ttk.Frame], ttk.Frame]) -> None:
        if self._screen is not None:
            self._screen.destroy()
        self._current = name
        self._render_header()
        self._screen = build(self._content)
        self._screen.pack(fill="both", expand=True)

    def _render_header(self) -> None:
        for child in self._header.winfo_children():
            child.destroy()
        bar = ttk.Frame(self._header, style="Surface.TFrame",
                        padding=(styles.SPACE_LG, styles.SPACE_MD))
        bar.pack(fill="x")

        brand = ttk.Frame(bar, style="Surface.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="CINE", style="Brand.TLabel").pack(side="left")
        ttk.Label(brand, text="ROJO", style="BrandAccent.TLabel").pack(side="left")

        user = self.session.user
        if user is None:
            return

        account = ttk.Frame(bar, style="Surface.TFrame")
        account.pack(side="right", padx=(styles.SPACE_XL, 0))
        ttk.Label(account, text=f"Signed in as {user.full_name}", style="HeaderUser.TLabel").pack(
            side="left", padx=(0, styles.SPACE_MD)
        )
        ttk.Button(account, text="Log out", style="Header.TButton",
                   command=self.logout, cursor="hand2").pack(side="left")

        nav = ttk.Frame(bar, style="Surface.TFrame")
        nav.pack(side="right")
        self._nav_link(nav, "Home", "home", self.show_home)
        for section in PLACEHOLDER_SECTIONS:
            item = ttk.Frame(nav, style="Surface.TFrame")
            item.pack(side="left", padx=(styles.SPACE_LG, 0))
            ttk.Label(item, text=section, style="Nav.TLabel").pack(anchor="e")
            ttk.Label(item, text="coming soon", style="NavHint.TLabel").pack(anchor="e")
        self._nav_link(nav, "My Profile", "profile", self.show_profile)

    def _nav_link(self, parent: ttk.Frame, text: str, name: str, command: Callable[[], None]) -> None:
        if self._current == name:
            widget: ttk.Widget = ttk.Label(parent, text=text, style="NavCurrent.TLabel")
        else:
            widget = ttk.Button(parent, text=text, style="NavLink.TButton", command=command,
                                cursor="hand2")
        widget.pack(side="left", padx=(styles.SPACE_LG, 0))

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root, style="Surface.TFrame",
                           padding=(styles.SPACE_LG, styles.SPACE_SM))
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text=f"© {styles.APP_NAME} · Sample data is fictional",
                  style="Footer.TLabel").pack(side="left")
        ttk.Label(footer, text="Offline · Data stored on this computer",
                  style="Footer.TLabel").pack(side="right")
