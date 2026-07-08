"""Serialization helpers for LDraw output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ldraw.colour import normalized_rgb_hex

if TYPE_CHECKING:
    from ldraw.colour import Colour

ZERO_TOLERANCE = 1e-12
MAX_DECIMAL_PLACES = 12
OPAQUE_ALPHA = 255


def format_ldraw_colour(colour: Colour) -> str:
    """Format a colour as an LDraw colour field.

    A colour with a code serializes to that code. A code-less colour serializes
    as an opaque direct colour (``0x2RRGGBB``); because LDraw direct colours
    cannot encode transparency, a translucent code-less colour cannot be
    represented and raises ``ValueError``.
    """
    if colour.code is not None:
        return str(colour.code)
    if colour.rgb is not None:
        if colour.alpha is not None and colour.alpha != OPAQUE_ALPHA:
            message = (
                "Cannot serialize a translucent direct colour "
                f"(alpha={colour.alpha}); assign an LDraw colour code instead: "
                f"{colour!r}"
            )
            raise ValueError(message)
        return f"0x2{normalized_rgb_hex(colour.rgb)}"
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
