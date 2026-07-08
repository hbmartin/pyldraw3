"""Mini-figure construction classes for the ldraw Python package."""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, TypeVar

from ldraw.colour import Colour
from ldraw.geometry import Identity, Matrix, Vector, XAxis, YAxis, ZAxis
from ldraw.pieces import Group, Piece

if TYPE_CHECKING:
    from collections.abc import Callable

R = TypeVar("R")
ColourInput = Colour | int
Number = int | float


def dependent_piece(
    dep: str,
) -> Callable[[Callable[..., R]], Callable[..., R | None]]:
    """Mark a piece method as dependent on another piece existing."""

    def decorator(fn: Callable[..., R]) -> Callable[..., R | None]:
        @wraps(fn)
        def wrapped(self: Person, *args: object, **kwargs: object) -> R | None:
            try:
                dependent_object = self.pieces_info[dep]
                return fn(self, dependent_object, *args, **kwargs)
            except KeyError:
                return None

        return wrapped

    return decorator


Airtanks = "3838"
HipsAndLegs = "3815c01"
Hips = "3815b"
ArmLeft = "3819"
ArmRight = "3818"
Hand = "3820"
LegLeft = "3817b"
LegRight = "3816b"
Torso = "973"
Head = HeadWithSwSmirkAndBrownEyebrowsPattern = "3626bps5"


class Person:
    """Representation of a LEGO minifigure."""

    def __init__(
        self,
        position: Vector | None = None,
        matrix: Matrix | None = None,
        group: Group | None = None,
    ) -> None:
        self.position = position if position is not None else Vector(0, 0, 0)
        self.matrix = matrix if matrix is not None else Identity()
        self.pieces_info: dict[str, Piece] = {}
        self.group = group

    def head(
        self,
        colour: ColourInput,
        angle: Number = 0,
        part: str = Head,
    ) -> Piece:
        """Add a head."""
        displacement = self.matrix * Vector(0, -24, 0)
        piece = Piece(
            colour,
            self.position + displacement,
            self.matrix * Identity().rotate(angle, YAxis),
            part,
            self.group,
        )
        self.pieces_info["head"] = piece
        return piece

    @dependent_piece("head")
    def hat(self, head: Piece, colour: ColourInput, part: str = "3901") -> Piece:
        """Add a hat piece to the figure's head."""
        displacement = head.position + head.matrix * Vector(0, 0, 0)
        return Piece(colour, displacement, head.matrix, part, self.group)

    def torso(self, colour: ColourInput, part: str = Torso) -> Piece:
        """Add a torso piece."""
        return Piece(colour, self.position, self.matrix, part, self.group)

    def backpack(
        self,
        colour: ColourInput,
        displacement: Vector | None = None,
        part: str = Airtanks,
    ) -> Piece:
        """Add a backpack."""
        offset = (
            self.matrix
            * (displacement if displacement is not None else Vector(0, 0, 0))
        )
        return Piece(
            colour,
            self.position + offset,
            self.matrix,
            part,
            self.group,
        )

    def hips_and_legs(self, colour: ColourInput, part: str = HipsAndLegs) -> Piece:
        """Add combined hips and legs."""
        displacement = self.matrix * Vector(0, 32, 0)
        return Piece(
            colour,
            self.position + displacement,
            self.matrix,
            part,
            self.group,
        )

    def hips(self, colour: ColourInput, part: str = Hips) -> Piece:
        """Add hips."""
        displacement = self.matrix * Vector(0, 32, 0)
        return Piece(
            colour,
            self.position + displacement,
            self.matrix,
            part,
            self.group,
        )

    def left_arm(
        self,
        colour: ColourInput,
        angle: Number = 0,
        part: str = ArmLeft,
    ) -> Piece:
        """Add a left arm."""
        displacement = self.matrix * Vector(15, 8, 0)
        matrix = (
            self.matrix
            * Identity().rotate(-10, ZAxis)
            * Identity().rotate(angle, XAxis)
        )
        piece = Piece(
            colour,
            self.position + displacement,
            matrix,
            part,
            self.group,
        )
        self.pieces_info["left arm"] = piece
        return piece

    @dependent_piece("left arm")
    def left_hand(
        self,
        left_arm: Piece,
        colour: ColourInput,
        angle: Number = 0,
        part: str = Hand,
    ) -> Piece:
        """Add a left hand piece to the figure's left arm."""
        displacement = left_arm.position + left_arm.matrix * Vector(4, 17, -9)
        matrix = (
            left_arm.matrix
            * Identity().rotate(40, XAxis)
            * Identity().rotate(angle, ZAxis)
        )
        piece = Piece(colour, displacement, matrix, part, self.group)
        self.pieces_info["left hand"] = piece
        return piece

    @dependent_piece("left hand")
    def left_hand_item(
        self,
        left_hand: Piece,
        colour: ColourInput,
        displacement: Vector,
        angle: Number = 0,
        part: str | None = None,
    ) -> Piece | None:
        """Add an item to the left hand."""
        if not part:
            return None
        displaced = left_hand.position + left_hand.matrix * displacement
        matrix = (
            left_hand.matrix
            * Identity().rotate(10, XAxis)
            * Identity().rotate(angle, YAxis)
        )
        return Piece(colour, displaced, matrix, part, self.group)

    def right_arm(
        self,
        colour: ColourInput,
        angle: Number = 0,
        part: str = ArmRight,
    ) -> Piece:
        """Add a right arm."""
        displacement = self.matrix * Vector(-15, 8, 0)
        matrix = (
            self.matrix
            * Identity().rotate(10, ZAxis)
            * Identity().rotate(angle, XAxis)
        )
        piece = Piece(
            colour,
            self.position + displacement,
            matrix,
            part,
            self.group,
        )
        self.pieces_info["right arm"] = piece
        return piece

    @dependent_piece("right arm")
    def right_hand(
        self,
        right_arm: Piece,
        colour: ColourInput,
        angle: Number = 0,
        part: str = Hand,
    ) -> Piece:
        """Add a right hand piece to the figure's right arm."""
        displacement = right_arm.position + right_arm.matrix * Vector(-4, 17, -9)
        matrix = (
            right_arm.matrix
            * Identity().rotate(40, XAxis)
            * Identity().rotate(angle, ZAxis)
        )
        piece = Piece(colour, displacement, matrix, part, self.group)
        self.pieces_info["right hand"] = piece
        return piece

    @dependent_piece("right hand")
    def right_hand_item(
        self,
        right_hand: Piece,
        colour: ColourInput,
        displacement: Vector,
        angle: Number = 0,
        part: str | None = None,
    ) -> Piece | None:
        """Add a right hand item."""
        if not part:
            return None
        displaced = right_hand.position + right_hand.matrix * displacement
        matrix = (
            right_hand.matrix
            * Identity().rotate(10, XAxis)
            * Identity().rotate(angle, YAxis)
        )
        return Piece(colour, displaced, matrix, part, self.group)

    def left_leg(
        self,
        colour: ColourInput,
        angle: Number = 0,
        part: str = LegLeft,
    ) -> Piece:
        """Add a left leg."""
        displacement = self.matrix * Vector(0, 44, 0)
        matrix = self.matrix * Identity().rotate(angle, XAxis)
        piece = Piece(
            colour,
            self.position + displacement,
            matrix,
            part,
            self.group,
        )
        self.pieces_info["left leg"] = piece
        return piece

    @dependent_piece("left leg")
    def left_shoe(
        self,
        left_leg: Piece,
        colour: ColourInput,
        angle: Number = 0,
        part: str | None = None,
    ) -> Piece | None:
        """Add a shoe on the left."""
        if not part:
            return None
        displacement = left_leg.position + left_leg.matrix * Vector(10, 28, 0)
        matrix = left_leg.matrix * Identity().rotate(angle, YAxis)
        return Piece(colour, displacement, matrix, part, self.group)

    def right_leg(
        self,
        colour: ColourInput,
        angle: Number = 0,
        part: str = LegRight,
    ) -> Piece:
        """Add a right leg."""
        displacement = self.matrix * Vector(0, 44, 0)
        matrix = self.matrix * Identity().rotate(angle, XAxis)
        piece = Piece(
            colour,
            self.position + displacement,
            matrix,
            part,
            self.group,
        )
        self.pieces_info["right leg"] = piece
        return piece

    @dependent_piece("right leg")
    def right_shoe(
        self,
        right_leg: Piece,
        colour: ColourInput,
        angle: Number = 0,
        part: str | None = None,
    ) -> Piece | None:
        """Add a shoe on the right."""
        if not part:
            return None
        displacement = right_leg.position + right_leg.matrix * Vector(-10, 28, 0)
        matrix = right_leg.matrix * Identity().rotate(angle, YAxis)
        return Piece(colour, displacement, matrix, part, self.group)
