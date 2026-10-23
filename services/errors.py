"""Exception types shared by all services."""

from __future__ import annotations


class UserFacingError(Exception):
    """An expected failure whose message is safe and helpful to show in the UI."""
