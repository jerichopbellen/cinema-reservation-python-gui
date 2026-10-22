"""Display formatting helpers."""

from __future__ import annotations


def format_peso(centavos: int) -> str:
    """Format integer centavos as Philippine pesos, e.g. ``35000 -> '₱350.00'``."""
    sign = "-" if centavos < 0 else ""
    pesos, cents = divmod(abs(centavos), 100)
    return f"{sign}₱{pesos:,}.{cents:02d}"
