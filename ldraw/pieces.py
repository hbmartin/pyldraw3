"""Classes representing pieces and groups for the ldraw Python package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from ldraw.colour import Colour
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.serialization import format_ldraw_colour, format_ldraw_number
from ldraw.utils import split_reference

if TYPE_CHECKING:
    from collections.abc import Iterable


MAIN_COLOUR_CODE = 16
DEFAULT_SUFFIX = ".DAT"


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
    suffix: str = DEFAULT_SUFFIX

    def __init__(  # noqa: PLR0913 - positional back-compat plus keyword-only suffix
        self,
        colour: Colour | int,
        position: Vector,
        matrix: Matrix,
        part: str,
        group: Group | None = None,
        *,
        suffix: str = DEFAULT_SUFFIX,
    ) -> None:
        self.colour = _as_colour(colour)
        self.position = position
        self.matrix = matrix
        self.part = part.upper()
        self.suffix = suffix
        self.group = None
        if group is not None:
            group.add_piece(self)

    @property
    def reference(self) -> str:
        """The subfile reference this piece serializes to, e.g. ``3001.DAT``."""
        return f"{self.part}{self.suffix}"

    @classmethod
    def place(  # noqa: PLR0913 - keyword-first factory mirrors piece placement fields
        cls,
        part: str,
        *,
        colour: Colour | int = MAIN_COLOUR_CODE,
        position: Vector | None = None,
        matrix: Matrix | None = None,
        group: Group | None = None,
        suffix: str = DEFAULT_SUFFIX,
    ) -> Self:
        """Create a piece keyword-first, defaulting to the origin and identity."""
        if suffix.upper() == DEFAULT_SUFFIX and "." in part:
            part, suffix = split_reference(part)
        return cls(
            colour=colour,
            position=position if position is not None else Vector(0, 0, 0),
            matrix=matrix if matrix is not None else Identity(),
            part=part,
            group=group,
            suffix=suffix,
        )

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
        return f"1 {format_ldraw_colour(self.colour)} {values} {self.reference}"

    def __str__(self) -> str:
        return self.to_ldraw()

    def __repr__(self) -> str:
        return (
            f"Piece(colour={self.colour!r}, position={self.position!r}, "
            f"matrix={self.matrix!r}, part={self.part!r}, suffix={self.suffix!r})"
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
        if piece.group is self:
            return
        if piece.group is not None:
            piece.group.remove_piece(piece)
        self.pieces.append(piece)
        piece.group = self

    def remove_piece(self, piece: Piece) -> None:
        """Remove a piece from the group."""
        self.pieces.remove(piece)
        piece.group = None

    def copy(self) -> Self:
        """Return an independent copy of this group with copies of its pieces."""
        duplicate = type(self)(
            position=self.position.copy(),
            matrix=self.matrix.copy(),
        )
        for piece in self.pieces:
            Piece(
                colour=piece.colour,
                position=piece.position.copy(),
                matrix=piece.matrix.copy(),
                part=piece.part,
                group=duplicate,
                suffix=piece.suffix,
            )
        return duplicate
