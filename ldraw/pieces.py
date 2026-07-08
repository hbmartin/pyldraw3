"""Classes representing pieces and groups for the ldraw Python package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from ldraw.colour import Colour
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.serialization import format_ldraw_number

if TYPE_CHECKING:
    from collections.abc import Iterable


def _as_colour(colour: Colour | int) -> Colour:
    if isinstance(colour, Colour):
        return colour
    return Colour(code=colour)


@dataclass(slots=True, eq=False, init=False)
class Piece:
    """A part with a defined colour, position, and rotation."""

    colour: Colour
    position: Vector
    matrix: Matrix
    part: str
    group: Group | None = None

    def __init__(
        self,
        colour: Colour | int,
        position: Vector,
        matrix: Matrix,
        part: str,
        group: Group | None = None,
    ) -> None:
        self.colour = _as_colour(colour)
        self.position = position
        self.matrix = matrix
        self.part = part.upper()
        self.group = group
        if self.group is not None and self not in self.group.pieces:
            self.group.add_piece(self)

    def _transformed(self) -> tuple[Vector, Matrix]:
        if self.group is None:
            return self.position, self.matrix
        position = self.group.position + self.group.matrix * self.position
        matrix = self.group.matrix * self.matrix
        return position, matrix

    def to_ldraw(self) -> str:
        """Serialize this piece to an LDraw type 1 line."""
        position, matrix = self._transformed()
        fields: Iterable[int | float] = (
            position.x,
            position.y,
            position.z,
            *matrix.flatten(),
        )
        values = " ".join(format_ldraw_number(value) for value in fields)
        return f"1 {self.colour.code} {values} {self.part}.DAT"

    def __str__(self) -> str:
        return self.to_ldraw()

    def __repr__(self) -> str:
        return (
            f"Piece(colour={self.colour!r}, position={self.position!r}, "
            f"matrix={self.matrix!r}, part={self.part!r})"
        )


@dataclass(slots=True, eq=False)
class Group:
    """A group of pieces."""

    position: Vector = field(default_factory=lambda: Vector(0, 0, 0))
    matrix: Matrix = field(default_factory=Identity)
    pieces: list[Piece] = field(default_factory=list)

    def to_ldraw(self) -> str:
        """Serialize all pieces in this group to LDraw lines."""
        return "\n".join(piece.to_ldraw() for piece in self.pieces)

    def __str__(self) -> str:
        return self.to_ldraw()

    def __repr__(self) -> str:
        return (
            f"Group(position={self.position!r}, matrix={self.matrix!r}, "
            f"pieces={len(self.pieces)})"
        )

    def add_piece(self, piece: Piece) -> None:
        """Add a piece to the group."""
        if piece.group is not None and piece.group != self:
            piece.group.remove_piece(piece)
        if piece not in self.pieces:
            self.pieces.append(piece)
        piece.group = self

    def remove_piece(self, piece: Piece) -> None:
        """Remove a piece from the group."""
        self.pieces.remove(piece)
        piece.group = None

    def copy(self) -> Self:
        """Return a shallow copy of group transforms and piece references."""
        return type(self)(
            position=self.position.copy(),
            matrix=self.matrix.copy(),
            pieces=list(self.pieces),
        )
