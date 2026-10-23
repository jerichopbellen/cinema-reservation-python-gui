"""Login and registration screens: a paper "poster" panel beside the form."""

from __future__ import annotations

from tkinter import ttk
from typing import TYPE_CHECKING

from services.auth_service import PASSWORD_RULES, USERNAME_RULES, User
from ui import brand, styles
from ui.widgets import Form, FormField, StatusMessage, run_in_background, user_message_for

if TYPE_CHECKING:
    from ui.app import App


class _AuthLayout(ttk.Frame):
    """Full-window split: brand poster on the left, the form (``self.card``) centered on the right."""

    def __init__(self, master: ttk.Frame, eyebrow: str, title: str, subtitle: str) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.columnconfigure(0, weight=5, uniform="auth")
        self.columnconfigure(1, weight=6, uniform="auth")
        self.rowconfigure(0, weight=1)

        hero = ttk.Frame(self, style="Paper.TFrame", padding=(56, 48))
        hero.grid(row=0, column=0, sticky="nsew")
        brand.logo(hero, background=styles.PAPER, foreground=styles.ON_ACCENT, large=True,
                   tagline_color="#4A4A4A").pack(anchor="w")
        ttk.Label(hero, text="OFFLINE  ·  YOUR DATA STAYS ON THIS COMPUTER",
                  style="PaperEyebrow.TLabel").pack(side="bottom", anchor="w")
        ttk.Label(hero, text="Browse films, pick seats on a live map, and keep every ticket in one place.",
                  style="PaperBody.TLabel", wraplength=380, justify="left").pack(
            side="bottom", anchor="w", pady=(0, styles.SPACE_XL))
        ttk.Label(hero, text="Your seat\nis waiting.", style="PaperDisplay.TLabel",
                  justify="left").pack(side="bottom", anchor="w", pady=(0, styles.SPACE_MD))

        holder = ttk.Frame(self, style="Panel.TFrame")
        holder.grid(row=0, column=1, sticky="nsew")
        self.card = ttk.Frame(holder, style="Panel.TFrame")
        self.card.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(self.card, text=eyebrow.upper(), style="PanelEyebrow.TLabel").pack(anchor="w")
        ttk.Label(self.card, text=title, style="PanelDisplay.TLabel").pack(anchor="w")
        ttk.Label(self.card, text=subtitle, style="PanelBody.TLabel").pack(
            anchor="w", pady=(2, styles.SPACE_MD))


class LoginView(_AuthLayout):
    def __init__(self, master: ttk.Frame, app: App, *, message: str = "", username: str = "") -> None:
        super().__init__(master, "Welcome back", "Log in", "Sign in to book and manage your tickets.")
        self.app = app

        notice = StatusMessage(self.card)
        if message:
            notice.success(message)
            notice.pack(anchor="w", pady=(styles.SPACE_SM, 0))

        fields = {
            "username": FormField(self.card, "Username", width=40),
            "password": FormField(self.card, "Password", secret=True, width=40),
        }
        for field in fields.values():
            field.pack(fill="x", pady=(styles.SPACE_SM, 0))

        status = StatusMessage(self.card)
        status.pack(anchor="w", pady=(styles.SPACE_XS, 0))
        button = ttk.Button(self.card, text="Log in", style="Accent.TButton", cursor="hand2")
        button.pack(fill="x", pady=(styles.SPACE_SM, styles.SPACE_MD))

        self.form = Form(fields, status, button, busy_text="Logging in…")
        self.form.bind_submit(self._submit)
        self._notice = notice

        link_row = ttk.Frame(self.card, style="Panel.TFrame")
        link_row.pack(anchor="w")
        ttk.Label(link_row, text="New here?", style="PanelBody.TLabel").pack(side="left")
        ttk.Button(link_row, text="Create an account", style="Link.TButton", cursor="hand2",
                   command=app.show_register).pack(side="left", padx=(styles.SPACE_XS, 0))

        fields["username"].set(username)
        (fields["password"] if username else fields["username"]).entry.focus_set()

    def _submit(self) -> None:
        if not self.form.begin():
            return
        self._notice.clear()
        values = self.form.values()
        run_in_background(
            self,
            lambda: self.app.auth.authenticate(values["username"], values["password"]),
            self._on_success,
            self._on_error,
        )

    def _on_success(self, user: User) -> None:
        self.app.login(user)

    def _on_error(self, exc: Exception) -> None:
        self.form.end()
        # Never point at a specific field: the message must not reveal which part was wrong.
        self.form.status.error(user_message_for(exc))
        self.form.fields["password"].clear()
        self.form.fields["password"].entry.focus_set()


class RegisterView(_AuthLayout):
    def __init__(self, master: ttk.Frame, app: App) -> None:
        super().__init__(master, "New here", "Create an account", "All fields are required.")
        self.app = app

        # Two-column grid keeps the form short enough for the default window height.
        grid = ttk.Frame(self.card, style="Panel.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1, uniform="register")
        field_options = {"width": 30, "wraplength": 280}
        fields = {
            "full_name": FormField(grid, "Full name", **field_options),
            "username": FormField(grid, "Username", hint=USERNAME_RULES, **field_options),
            "password": FormField(grid, "Password", hint=PASSWORD_RULES, secret=True, **field_options),
            "confirm_password": FormField(grid, "Confirm password", secret=True, **field_options),
        }
        for index, field in enumerate(fields.values()):
            field.grid(row=index // 2, column=index % 2, sticky="new",
                       padx=(0 if index % 2 == 0 else styles.SPACE_MD, 0), pady=(styles.SPACE_SM, 0))

        status = StatusMessage(self.card, wraplength=600)
        status.pack(anchor="w", pady=(styles.SPACE_XS, 0))
        button = ttk.Button(self.card, text="Create Account", style="Accent.TButton", cursor="hand2")
        button.pack(fill="x", pady=(styles.SPACE_SM, styles.SPACE_MD))

        self.form = Form(fields, status, button, busy_text="Creating account…")
        self.form.bind_submit(self._submit)

        link_row = ttk.Frame(self.card, style="Panel.TFrame")
        link_row.pack(anchor="w")
        ttk.Label(link_row, text="Already have an account?", style="PanelBody.TLabel").pack(side="left")
        ttk.Button(link_row, text="Log in", style="Link.TButton", cursor="hand2",
                   command=app.show_login).pack(side="left", padx=(styles.SPACE_XS, 0))

        fields["full_name"].entry.focus_set()

    def _submit(self) -> None:
        if not self.form.begin():
            return
        values = self.form.values()
        run_in_background(
            self,
            lambda: self.app.auth.register(
                values["full_name"], values["username"], values["password"],
                values["confirm_password"],
            ),
            self._on_success,
            self._on_error,
        )

    def _on_success(self, user: User) -> None:
        self.app.show_login(message=f"Account created for {user.username}. Please log in.",
                            username=user.username)

    def _on_error(self, exc: Exception) -> None:
        self.form.end()
        self.form.show_error(exc)
