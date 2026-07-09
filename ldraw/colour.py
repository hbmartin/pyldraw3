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


OPAQUE_ALPHA = 255


@dataclass(frozen=True, slots=True)
class Colour:
    """A colour, identified by a code, or by rgb/alpha for direct colours.

    ``rgb`` is canonicalized on construction to ``#RRGGBB`` — a leading
    ``#``, six uppercase hex digits — whatever form it was given in;
    malformed values raise ``ValueError``.
    """

    code: int | None = None
    name: str | None = None
    rgb: str | None = None
    alpha: int | None = None
    colour_attributes: list[str] | None = None

    def __post_init__(self) -> None:
        # Canonicalizing here gives rgb a single invariant everywhere and
        # fails on malformed values at construction rather than write-out.
        if self.rgb is not None:
            object.__setattr__(self, "rgb", f"#{normalized_rgb_hex(self.rgb)}")

    @property
    def is_solid(self) -> bool:
        """Whether this colour is plain opaque paint — no alpha, no finish.

        Judged from the data on this instance: full alpha (or none given)
        and no colour attributes (``CHROME``, ``GLITTER``, ``LUMINANCE``,
        …). Colours from a parts catalog carry both fields; a bare
        ``Colour(code=...)`` placeholder carries neither and so reads as
        solid — look the code up in ``Parts.colours_by_code`` to judge the
        real palette entry.
        """
        opaque = self.alpha is None or self.alpha == OPAQUE_ALPHA
        return opaque and not self.colour_attributes

    @property
    def display_label(self) -> str:
        """Human-readable label for UI lists and inspectors."""
        if self.name is not None:
            return self.name.replace("_", " ")
        if self.code is not None:
            return f"Colour {self.code}"
        if self.rgb is not None:
            return self.rgb
        return "Unknown colour"

    @property
    def swatch_rgb(self) -> str | None:
        """RGB hex value suitable for colour swatches, when known."""
        return self.rgb

    @property
    def swatch_alpha(self) -> int:
        """Alpha channel suitable for colour swatches."""
        return OPAQUE_ALPHA if self.alpha is None else self.alpha

    @property
    def is_transparent(self) -> bool:
        """Whether this colour has a non-opaque alpha value."""
        return self.swatch_alpha < OPAQUE_ALPHA

    def _direct_key(self) -> tuple[str | None, int]:
        return self.rgb, OPAQUE_ALPHA if self.alpha is None else self.alpha

    def __eq__(self, other: object) -> bool:
        match other:
            case Colour() if self.code is None and other.code is None:
                return self._direct_key() == other._direct_key()
            case Colour():
                return self.code == other.code
            case int():
                return self.code == other
            case _:
                return NotImplemented

    def __hash__(self) -> int:
        if self.code is None:
            return hash(self._direct_key())
        return hash(self.code)
