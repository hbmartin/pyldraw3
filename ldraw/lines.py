"""Classes for lines in parts paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ldraw.colour import Colour
    from ldraw.geometry import Vector


@dataclass(slots=True)
class OptionalLine:
    """An optional line."""

    colour: Colour
    point1: Vector
    point2: Vector
    point3: Vector
    point4: Vector


@dataclass(slots=True)
class Quadrilateral:
    """A quadrilateral."""

    colour: Colour
    point1: Vector
    point2: Vector
    point3: Vector
    point4: Vector

    @property
    def points(self) -> list[Vector]:
        """Return the points array."""
        return [self.point1, self.point2, self.point3, self.point4]


@dataclass(slots=True)
class Line:
    """A 3D line."""

    colour: Colour
    point1: Vector
    point2: Vector

    @property
    def points(self) -> list[Vector]:
        """Return the points array."""
        return [self.point1, self.point2]


@dataclass(slots=True)
class Triangle:
    """A triangle."""

    colour: Colour
    point1: Vector
    point2: Vector
    point3: Vector

    @property
    def points(self) -> list[Vector]:
        """Return the points array."""
        return [self.point1, self.point2, self.point3]


@dataclass(frozen=True, slots=True)
class MetaCommand:
    """A metacommand."""

    type: str
    text: str


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment."""

    text: str
