"""Plain-text receipts generated from saved bookings.

Receipts are rendered from a :class:`~services.booking_service.BookingDetails`
loaded from the database after the booking committed, so they always reflect
saved data. A saved receipt file is a snapshot of the booking when it was
generated; the database, not the file, is the source of truth for status.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from database.connection import PROJECT_ROOT
from services.booking_service import BookingDetails
from utils.branding import APP_NAME
from utils.formatting import format_local_datetime, format_peso, format_show_date, format_show_time

RECEIPTS_DIR = PROJECT_ROOT / "receipts"
RECEIPT_WIDTH = 46


def receipt_filename(reference: str) -> str:
    """A filesystem-safe name derived from the booking reference."""
    safe = re.sub(r"[^A-Za-z0-9-]", "", reference) or "booking"
    return f"receipt_{safe}.txt"


def render_receipt(booking: BookingDetails, generated_at: dt.datetime | None = None) -> str:
    """Return the receipt text for a saved booking."""
    generated_at = generated_at or dt.datetime.now()
    rule = "=" * RECEIPT_WIDTH
    thin = "-" * RECEIPT_WIDTH

    def line(label: str, value: str) -> str:
        return f"{label:<18}{value}"

    lines = [
        rule,
        APP_NAME.upper().center(RECEIPT_WIDTH),
        "Official Booking Receipt".center(RECEIPT_WIDTH),
        rule,
        line("Booking reference", booking.reference),
        line("Status", booking.status.upper()),
        line("Customer", booking.customer_name),
        line("Booked on", format_local_datetime(booking.created_at)),
        thin,
        line("Movie", booking.movie_title),
        line("Date", format_show_date(booking.starts_at.date())),
        line("Time", format_show_time(booking.starts_at)),
        line("Auditorium", booking.auditorium),
        line("Seats", ", ".join(booking.seat_labels)),
        thin,
        line("Tickets", str(booking.ticket_count)),
        line("Price per ticket", format_peso(booking.price_per_ticket)),
        line("TOTAL", format_peso(booking.total_amount)),
        rule,
    ]
    if booking.is_canceled:
        lines.append("This booking was canceled. Seats were released.")
    lines += [
        f"Generated {generated_at:%b} {generated_at.day}, {generated_at.year}, "
        f"{format_show_time(generated_at)}.",
        "This receipt is a snapshot; check My Bookings",
        "in the app for the current booking status.",
        f"Thank you for choosing {APP_NAME}!",
    ]
    return "\n".join(lines) + "\n"


def save_receipt(booking: BookingDetails, path: Path | str | None = None,
                 generated_at: dt.datetime | None = None) -> Path:
    """Write the receipt to ``path`` (default: the receipts folder) and return the path.

    Raises ``OSError`` if the file cannot be written.
    """
    target = Path(path) if path is not None else RECEIPTS_DIR / receipt_filename(booking.reference)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_receipt(booking, generated_at), encoding="utf-8")
    return target
