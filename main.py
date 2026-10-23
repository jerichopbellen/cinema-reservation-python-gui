"""CineRojo application entry point.

Run with ``python main.py`` from any working directory. Python places this
file's folder on ``sys.path``, and the database location is resolved relative
to the project, so the current directory does not matter.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from database import initialize_database
from services.auth_service import AuthService
from services.session import Session
from ui import styles
from ui.app import App

logger = logging.getLogger("cinerojo")


def enable_windows_dpi_awareness() -> None:
    """Render crisp text on high-DPI Windows displays. No-op on other platforms."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError) as exc:
        logger.debug("Could not enable DPI awareness: %s", exc)


def build_app(db_path: Path) -> App:
    """Create the themed root window and show the login screen."""
    root = tk.Tk()
    root.title(styles.WINDOW_TITLE)
    root.minsize(*styles.WINDOW_MIN_SIZE)
    styles.center_window(root, *styles.WINDOW_SIZE)
    styles.apply_theme(root)

    app = App(root, AuthService(db_path), Session(), db_path)
    app.show_login()
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    return app


def show_startup_error(message: str) -> None:
    """Show a modal error dialog when the main window cannot be created."""
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(f"{styles.APP_NAME} could not start", message, parent=root)
    root.destroy()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    enable_windows_dpi_awareness()

    try:
        db_path = initialize_database()
    except (sqlite3.Error, OSError) as exc:
        logger.exception("Database initialization failed")
        show_startup_error(f"The database could not be initialized.\n\n{exc}")
        return 1

    build_app(db_path).root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
