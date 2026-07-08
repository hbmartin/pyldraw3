"""Colour definitions for the Python ldraw package."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Colour:
    """A colour, uniquely identified by a code."""

    code: int | None = None
    name: str | None = None
    rgb: str | None = None
    alpha: int | None = None
    colour_attributes: list[str] | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Colour):
            return self.code == other.code
        return self.code == other

    def __hash__(self) -> int:
        return hash(self.code)
