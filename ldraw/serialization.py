"""Serialization helpers for LDraw output."""

from __future__ import annotations

ZERO_TOLERANCE = 1e-12
MAX_DECIMAL_PLACES = 12


def format_ldraw_number(value: float) -> str:
    """Format a numeric LDraw field using compact decimal notation."""
    number = float(value)
    if abs(number) <= ZERO_TOLERANCE:
        return "0"

    nearest_integer = round(number)
    if abs(number - nearest_integer) <= ZERO_TOLERANCE:
        return str(nearest_integer)

    return f"{number:.{MAX_DECIMAL_PLACES}f}".rstrip("0").rstrip(".")
