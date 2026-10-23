"""CineRojo application entry point.

Run with ``python main.py`` from any working directory. Python places this
file's folder on ``sys.path``, and the database location is resolved relative
to the project, so the current directory does not matter.

Log messages go to the console and to ``data/cinerojo.log``. No passwords,
hashes, or salts are ever logged.
"""

from __future__ import annotations

import logging
import logging.handlers
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from database import initialize_database
from database.connection import DATA_DIR
from services.auth_service import AuthService
from services.session import Session
from ui import styles
from ui.app import App

logger = logging.getLogger("cinerojo")

LOG_FILE = DATA_DIR / "cinerojo.log"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Log to the console and to a small rotating file next to the database."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=512_000, backupCount=2, encoding="utf-8"))
    except OSError as exc:
        print(f"Logging to file disabled: {exc}", file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=handlers)


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
    configure_logging()
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
