"""Tests for pieces functionality."""

import pytest

from ldraw.colour import Colour
from ldraw.figure import Person
from ldraw.geometry import Identity, Vector, YAxis
from ldraw.pieces import Group, Piece
from ldraw.serialization import format_ldraw_number

White = Colour(15, "White", "#FFFFFF", 255, [])
Yellow = Colour(14, "Yellow", "#F2CD37", 255, [])
Light_Grey = Colour(7, "Light_Grey", "#9BA19D", 255, [])
Black = Colour(0, "Black", "#05131D", 255, [])
Brick1X1 = "3005"
HelmetClassic = "3842b"
Flipper = "2599"
CameraMovie = "30148"


def test_add_piece() -> None:
    group1 = Group()
    group2 = Group()
    piece = Piece(White, Vector(0, 0, 0), Identity(), Brick1X1, group=group1)

    assert piece in group1.pieces
    assert piece not in group2.pieces

    group2.add_piece(piece)

    assert piece in group2.pieces
    assert piece not in group1.pieces


def test_format_ldraw_number_compacts_values() -> None:
    assert format_ldraw_number(40.0) == "40"
    assert format_ldraw_number(0.125000000000) == "0.125"
    assert format_ldraw_number(1e-13) == "0"
    assert format_ldraw_number(1.2345678901234) == "1.234567890123"


def test_piece_to_ldraw_and_str_are_compact() -> None:
    piece = Piece(
        White,
        Vector(40.0, 0.125000000000, 1e-13),
        Identity().rotate(90, YAxis),
        Brick1X1,
    )

    expected = "1 15 40 0.125 0 0 0 -1 0 1 0 1 0 0 3005.DAT"
    assert piece.to_ldraw() == expected
    assert str(piece) == expected
    assert not repr(piece).startswith("1 ")


def test_group_to_ldraw_applies_transform() -> None:
    group = Group(position=Vector(10, 0, 0))
    Piece(White, Vector(40, 0, 0), Identity(), Brick1X1, group=group)

    assert group.to_ldraw() == "1 15 50 0 0 1 0 0 0 1 0 0 0 1 3005.DAT"
    assert str(group) == group.to_ldraw()


def test_add_piece_to_same_group_twice_is_noop() -> None:
    group = Group()
    piece = Piece(White, Vector(0, 0, 0), Identity(), Brick1X1, group=group)

    group.add_piece(piece)

    assert group.pieces == [piece]


def test_group_copy_is_independent() -> None:
    group = Group(position=Vector(10, 0, 0))
    piece = Piece(White, Vector(40, 0, 0), Identity(), Brick1X1, group=group)

    duplicate = group.copy()
    duplicate.position = Vector(20, 0, 0)

    assert duplicate.to_ldraw() == "1 15 60 0 0 1 0 0 0 1 0 0 0 1 3005.DAT"
    assert group.to_ldraw() == "1 15 50 0 0 1 0 0 0 1 0 0 0 1 3005.DAT"
    assert piece in group.pieces
    assert duplicate.pieces[0] is not piece
    assert duplicate.pieces[0].group is duplicate


def test_piece_serializes_direct_colour() -> None:
    piece = Piece(
        Colour(rgb="#00ff00", alpha=255),
        Vector(0, 0, 0),
        Identity(),
        Brick1X1,
    )

    assert piece.to_ldraw() == "1 0x200FF00 0 0 0 1 0 0 0 1 0 0 0 1 3005.DAT"


def test_piece_rejects_colour_without_code_or_rgb() -> None:
    piece = Piece(Colour(), Vector(0, 0, 0), Identity(), Brick1X1)

    with pytest.raises(ValueError, match="neither a code nor an rgb value"):
        piece.to_ldraw()


@pytest.fixture
def figure():
    return Person(Vector(0, 0, -10))


@pytest.fixture
def full_figure(figure):
    figure.left_arm(Yellow, -45)
    figure.left_hand(Yellow, 10)
    figure.right_arm(Yellow, -45)
    figure.right_hand(Yellow, 10)
    figure.left_leg(Yellow, -10)
    figure.right_leg(Yellow, -10)
    return figure


def test_add_hat_valid_head(figure) -> None:
    assert figure.hat(White, HelmetClassic) is None


def test_add_hat_no_head(figure) -> None:
    assert figure.head(Yellow, 30) is not None
    assert figure.hat(White, HelmetClassic) is not None


def test_add_lh_item_nopart(figure, full_figure) -> None:
    assert full_figure.left_hand_item(Light_Grey, Vector(0, 0, -12), -15) is None
    assert (
        full_figure.left_hand_item(Light_Grey, Vector(0, 0, -12), -15, CameraMovie)
        is not None
    )


def test_add_rh_item_nopart(figure, full_figure) -> None:
    assert full_figure.right_hand_item(Light_Grey, Vector(0, 0, -12), -15) is None
    assert (
        full_figure.right_hand_item(Light_Grey, Vector(0, 0, -12), -15, CameraMovie)
        is not None
    )


def test_add_ls_item_nopart(figure, full_figure) -> None:
    assert full_figure.left_shoe(Black, 10) is None
    assert full_figure.left_shoe(Black, 10, Flipper) is not None


def test_add_rs_item_nopart(figure, full_figure) -> None:
    assert full_figure.right_shoe(Black, 10) is None
    assert full_figure.right_shoe(Black, 10, Flipper) is not None
