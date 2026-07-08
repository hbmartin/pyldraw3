"""Colour definitions for the Python ldraw package."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RGB_HEX_RE = re.compile(r"[0-9A-F]{6}")
_ALPHA_HEX_RE = re.compile(r"[0-9A-F]{4}|[0-9A-F]{8}")
_SHORTHAND_LENGTH = 3


def normalized_rgb_hex(rgb: str) -> str:
    """Normalize an ``#RRGGBB`` (or ``#RGB`` shorthand) string to six hex digits."""
    hex_digits = rgb.removeprefix("#").upper()
    if len(hex_digits) == _SHORTHAND_LENGTH:  # shorthand such as "0F0"
        hex_digits = "".join(digit * 2 for digit in hex_digits)
    if _RGB_HEX_RE.fullmatch(hex_digits):
        return hex_digits
    if _ALPHA_HEX_RE.fullmatch(hex_digits):
        message = (
            f"rgb value {rgb!r} includes an alpha channel; LDraw direct colours "
            "cannot encode alpha — use a six-digit #RRGGBB value and an LDraw "
            "colour code for transparency"
        )
        raise ValueError(message)
    message = f"Invalid rgb value for a direct colour: {rgb!r}"
    raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Colour:
    """A colour, uniquely identified by a code."""

    code: int | None = None
    name: str | None = None
    rgb: str | None = None
    alpha: int | None = None
    colour_attributes: list[str] | None = None

    def __post_init__(self) -> None:
        # A code-less colour can only ever serialize as a direct colour, so a
        # malformed rgb value should fail here rather than at write-out time.
        if self.code is None and self.rgb is not None:
            normalized_rgb_hex(self.rgb)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Colour):
            return self.code == other.code
        return self.code == other

    def __hash__(self) -> int:
        return hash(self.code)
