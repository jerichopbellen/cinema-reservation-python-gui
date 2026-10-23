"""Display formatting helpers."""

from __future__ import annotations

import datetime as dt

DB_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_local_date(utc_timestamp: str) -> str:
    """Format a UTC database timestamp as a local date, e.g. ``'October 24, 2026'``."""
    moment = dt.datetime.strptime(utc_timestamp, DB_TIMESTAMP_FORMAT).replace(tzinfo=dt.timezone.utc)
    local = moment.astimezone()
    return f"{local:%B} {local.day}, {local.year}"


def format_peso(centavos: int) -> str:
    """Format integer centavos as Philippine pesos, e.g. ``35000 -> '₱350.00'``."""
    sign = "-" if centavos < 0 else ""
    pesos, cents = divmod(abs(centavos), 100)
    return f"{sign}₱{pesos:,}.{cents:02d}"
