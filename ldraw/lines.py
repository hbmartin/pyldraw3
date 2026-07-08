"""Classes for lines in parts paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.serialization import format_ldraw_colour, format_ldraw_number

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.colour import Colour
    from ldraw.geometry import Vector


def _geometry_to_ldraw(line_type: int, colour: Colour, points: Iterable[Vector]) -> str:
    coords = " ".join(
        format_ldraw_number(coord)
        for point in points
        for coord in (point.x, point.y, point.z)
    )
    return f"{line_type} {format_ldraw_colour(colour)} {coords}"


@dataclass(slots=True)
class OptionalLine:
    """An optional line."""

    colour: Colour
    point1: Vector
    point2: Vector
    point3: Vector
    point4: Vector

    @property
    def points(self) -> list[Vector]:
        """Return the points array."""
        return [self.point1, self.point2, self.point3, self.point4]

    def to_ldraw(self) -> str:
        """Serialize this optional line to an LDraw type 5 line."""
        return _geometry_to_ldraw(line_type=5, colour=self.colour, points=self.points)

    def __str__(self) -> str:
        return self.to_ldraw()


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

    def to_ldraw(self) -> str:
        """Serialize this quadrilateral to an LDraw type 4 line."""
        return _geometry_to_ldraw(line_type=4, colour=self.colour, points=self.points)

    def __str__(self) -> str:
        return self.to_ldraw()


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

    def to_ldraw(self) -> str:
        """Serialize this line to an LDraw type 2 line."""
        return _geometry_to_ldraw(line_type=2, colour=self.colour, points=self.points)

    def __str__(self) -> str:
        return self.to_ldraw()


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

    def to_ldraw(self) -> str:
        """Serialize this triangle to an LDraw type 3 line."""
        return _geometry_to_ldraw(line_type=3, colour=self.colour, points=self.points)

    def __str__(self) -> str:
        return self.to_ldraw()


@dataclass(frozen=True, slots=True)
class MetaCommand:
    """A metacommand."""

    type: str
    text: str

    def to_ldraw(self) -> str:
        """Serialize this meta-command to an LDraw type 0 line."""
        if not self.text:
            return f"0 !{self.type}"
        return f"0 !{self.type} {self.text}"

    def __str__(self) -> str:
        return self.to_ldraw()


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment."""

    text: str

    def to_ldraw(self) -> str:
        """Serialize this comment to an LDraw type 0 line."""
        if not self.text:
            return "0"
        return f"0 {self.text}"

    def __str__(self) -> str:
        return self.to_ldraw()
