"""Display formatting helpers."""

from __future__ import annotations

import datetime as dt

DB_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_local_date(utc_timestamp: str) -> str:
    """Format a UTC database timestamp as a local date, e.g. ``'October 24, 2026'``."""
    moment = dt.datetime.strptime(utc_timestamp, DB_TIMESTAMP_FORMAT).replace(tzinfo=dt.timezone.utc)
    local = moment.astimezone()
    return f"{local:%B} {local.day}, {local.year}"


def format_local_datetime(utc_timestamp: str, *, with_year: bool = True) -> str:
    """Format a UTC database timestamp in local time, e.g. ``'Oct 24, 2026, 3:05 PM'``.

    ``with_year=False`` gives the compact ``'Oct 24, 3:05 PM'`` for dense tables.
    """
    moment = dt.datetime.strptime(utc_timestamp, DB_TIMESTAMP_FORMAT).replace(tzinfo=dt.timezone.utc)
    local = moment.astimezone()
    year = f" {local.year}," if with_year else ""
    return f"{local:%b} {local.day},{year} {format_show_time(local)}"


def format_duration(minutes: int) -> str:
    """Format a running time, e.g. ``118 -> '1h 58m'``."""
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def format_show_date(moment: dt.date) -> str:
    """Format a show date, e.g. ``'Sat, Oct 24, 2026'``."""
    return f"{moment:%a, %b} {moment.day}, {moment.year}"


def format_show_time(moment: dt.datetime | dt.time) -> str:
    """Format a show time in 12-hour form, e.g. ``'8:15 PM'``."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def format_showtime(moment: dt.datetime) -> str:
    """Format a show date and time together, e.g. ``'Sat, Jan 5, 2030  ·  8:15 PM'``."""
    return f"{format_show_date(moment.date())}  ·  {format_show_time(moment)}"


def truncate(text: str, limit: int) -> str:
    """Shorten ``text`` to at most ``limit`` characters, ending with an ellipsis if cut."""
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def format_peso(centavos: int) -> str:
    """Format integer centavos as Philippine pesos, e.g. ``35000 -> '₱350.00'``."""
    sign = "-" if centavos < 0 else ""
    pesos, cents = divmod(abs(centavos), 100)
    return f"{sign}₱{pesos:,}.{cents:02d}"
