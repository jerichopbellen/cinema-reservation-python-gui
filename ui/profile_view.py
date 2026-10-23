"""Profile screen: view account details, edit full name, change password."""

from __future__ import annotations

from tkinter import ttk
from typing import TYPE_CHECKING

from services.auth_service import PASSWORD_RULES, User, UserNotFoundError
from ui import styles
from ui.widgets import Form, FormField, StatusMessage, panel, run_in_background, screen_title
from utils.formatting import format_local_date

if TYPE_CHECKING:
    from ui.app import App


def initials(full_name: str) -> str:
    parts = full_name.split()
    return "".join(part[0] for part in parts[:2]).upper() or "?"


def _action_row(card: ttk.Frame, text: str) -> tuple[ttk.Button, StatusMessage]:
    """A submit button with its status message alongside, to save vertical space."""
    row = ttk.Frame(card, style="Panel.TFrame")
    row.pack(fill="x", pady=(styles.SPACE_MD, 0))
    button = ttk.Button(row, text=text, style="Accent.TButton", cursor="hand2")
    button.pack(side="left")
    status = StatusMessage(row, wraplength=240)
    status.pack(side="left", padx=(styles.SPACE_MD, 0))
    return button, status


class ProfileView(ttk.Frame):
    def __init__(self, master: ttk.Frame, app: App, user: User) -> None:
        super().__init__(master, style="App.TFrame", padding=(styles.SPACE_XL, styles.SPACE_XL - 8))
        self.app = app
        self.user_id = user.id

        screen_title(self, "Profile", eyebrow="Account",
                     subtitle="Manage your name and password.").pack(fill="x", pady=(0, styles.SPACE_LG))

        columns = ttk.Frame(self, style="App.TFrame")
        columns.pack(fill="x")
        columns.columnconfigure((0, 1), weight=1, uniform="profile")
        self._build_details(columns, user).grid(row=0, column=0, sticky="nsew",
                                                padx=(0, styles.SPACE_MD))
        self._build_password(columns).grid(row=0, column=1, sticky="nsew")

    # --- Account details ------------------------------------------------------

    def _build_details(self, parent: ttk.Frame, user: User) -> ttk.Frame:
        card = panel(parent, "Account details")

        identity = ttk.Frame(card, style="Panel.TFrame")
        identity.pack(fill="x", pady=(styles.SPACE_MD, 0))
        self.avatar = ttk.Label(identity, text=initials(user.full_name), style="Avatar.TLabel",
                                font=(styles.FONT_DISPLAY[0], 16, "bold"), width=4, padding=(0, 12))
        self.avatar.pack(side="left")
        names = ttk.Frame(identity, style="Panel.TFrame")
        names.pack(side="left", padx=(styles.SPACE_MD, 0))
        ttk.Label(names, text=f"@{user.username}", style="PanelValue.TLabel").pack(anchor="w")
        ttk.Label(names, text=f"MEMBER SINCE {format_local_date(user.created_at).upper()}",
                  style="PanelEyebrow.TLabel").pack(anchor="w")
        ttk.Label(card, text="Usernames cannot be changed.", style="PanelHint.TLabel").pack(
            anchor="w", pady=(styles.SPACE_SM, 0))

        name_field = FormField(card, "Full name", wraplength=460)
        name_field.set(user.full_name)
        name_field.pack(fill="x", pady=(styles.SPACE_MD, 0))

        button, status = _action_row(card, "Save changes")

        self.details_form = Form({"full_name": name_field}, status, button, busy_text="Saving…")
        self.details_form.bind_submit(self._save_details)
        return card

    def _save_details(self) -> None:
        form = self.details_form
        if not form.begin():
            return
        full_name = form.values()["full_name"]
        run_in_background(
            self,
            lambda: self.app.auth.update_full_name(self.user_id, full_name),
            self._on_details_saved,
            self._on_details_error,
        )

    def _on_details_saved(self, user: User) -> None:
        self.details_form.end()
        self.details_form.fields["full_name"].set(user.full_name)
        self.avatar.configure(text=initials(user.full_name))
        self.app.on_user_updated(user)
        self.app.toast("Your name has been updated.")

    def _on_details_error(self, exc: Exception) -> None:
        if isinstance(exc, UserNotFoundError):
            self.app.logout(message=str(exc))
            return
        self.details_form.end()
        self.details_form.show_error(exc)

    # --- Password -------------------------------------------------------------

    def _build_password(self, parent: ttk.Frame) -> ttk.Frame:
        card = panel(parent, "Change password")
        fields = {
            "current_password": FormField(card, "Current password", secret=True, wraplength=460),
            "new_password": FormField(card, "New password", hint=PASSWORD_RULES, secret=True,
                                      wraplength=460),
            "confirm_password": FormField(card, "Confirm new password", secret=True, wraplength=460),
        }
        for field in fields.values():
            field.pack(fill="x", pady=(styles.SPACE_SM, 0))

        button, status = _action_row(card, "Update password")

        self.password_form = Form(fields, status, button, busy_text="Updating…")
        self.password_form.bind_submit(self._change_password)
        return card

    def _change_password(self) -> None:
        form = self.password_form
        if not form.begin():
            return
        values = form.values()
        run_in_background(
            self,
            lambda: self.app.auth.change_password(
                self.user_id, values["current_password"], values["new_password"],
                values["confirm_password"],
            ),
            self._on_password_changed,
            self._on_password_error,
        )

    def _on_password_changed(self, _result: None) -> None:
        self.password_form.end()
        for field in self.password_form.fields.values():
            field.clear()
        self.app.toast("Your password has been changed.")

    def _on_password_error(self, exc: Exception) -> None:
        if isinstance(exc, UserNotFoundError):
            self.app.logout(message=str(exc))
            return
        self.password_form.end()
        if getattr(exc, "field", "") == "current_password":
            self.password_form.fields["current_password"].clear()
        self.password_form.show_error(exc)
