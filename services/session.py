"""In-memory session state for the signed-in user.

Only the public :class:`~services.auth_service.User` record is kept; passwords,
hashes, and salts never enter the session. Nothing is persisted to disk, so
closing the application always ends the session.
"""

from __future__ import annotations

from services.auth_service import User


class NotAuthenticatedError(Exception):
    """Raised when an authenticated-only action is attempted without a session."""


class Session:
    """Tracks which user, if any, is currently logged in."""

    def __init__(self) -> None:
        self._user: User | None = None

    @property
    def user(self) -> User | None:
        return self._user

    @property
    def user_id(self) -> int | None:
        return self._user.id if self._user else None

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None

    def login(self, user: User) -> None:
        self._user = user

    def update_user(self, user: User) -> None:
        """Refresh cached details (e.g. after a name change) for the same signed-in user."""
        if self._user is None or self._user.id != user.id:
            raise NotAuthenticatedError("Cannot update details for a user who is not signed in.")
        self._user = user

    def require_user(self) -> User:
        if self._user is None:
            raise NotAuthenticatedError("Please log in to continue.")
        return self._user

    def logout(self) -> None:
        self._user = None
