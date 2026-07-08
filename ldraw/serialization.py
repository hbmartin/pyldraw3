"""Serialization helpers for LDraw output."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ldraw.colour import Colour

ZERO_TOLERANCE = 1e-12
MAX_DECIMAL_PLACES = 12


def format_ldraw_colour(colour: Colour) -> str:
    """Format a colour as an LDraw colour field.

    Colours without a code are serialized as direct colours (`0x2RRGGBB`).
    """
    if colour.code is not None:
        return str(colour.code)
    if colour.rgb is not None:
        return f"0x2{colour.rgb.removeprefix('#').upper()}"
    message = f"Colour has neither a code nor an rgb value: {colour!r}"
    raise ValueError(message)


def format_ldraw_number(value: float) -> str:
    """Format a numeric LDraw field using compact decimal notation."""
    number = float(value)
    if abs(number) <= ZERO_TOLERANCE:
        return "0"

    nearest_integer = round(number)
    if abs(number - nearest_integer) <= ZERO_TOLERANCE:
        return str(nearest_integer)

    return f"{number:.{MAX_DECIMAL_PLACES}f}".rstrip("0").rstrip(".")
