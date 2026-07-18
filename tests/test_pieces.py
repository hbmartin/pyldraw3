"""Tests for pieces functionality."""

import pytest

import ldraw.figure as figure_mod
from ldraw.colour import Colour
from ldraw.figure import Person, dependent_piece
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

    expected = "1 15 40 0.125 0 0 0 1 0 1 0 -1 0 0 3005.dat"
    assert piece.to_ldraw() == expected
    assert str(piece) == expected
    assert not repr(piece).startswith("1 ")


def test_group_to_ldraw_applies_transform() -> None:
    group = Group(position=Vector(10, 0, 0))
    Piece(White, Vector(40, 0, 0), Identity(), Brick1X1, group=group)

    assert group.to_ldraw() == "1 15 50 0 0 1 0 0 0 1 0 0 0 1 3005.dat"
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

    assert duplicate.to_ldraw() == "1 15 60 0 0 1 0 0 0 1 0 0 0 1 3005.dat"
    assert group.to_ldraw() == "1 15 50 0 0 1 0 0 0 1 0 0 0 1 3005.dat"
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

    assert piece.to_ldraw() == "1 0x200FF00 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat"


def test_piece_rejects_colour_without_code_or_rgb() -> None:
    piece = Piece(Colour(), Vector(0, 0, 0), Identity(), Brick1X1)

    with pytest.raises(ValueError, match="neither a code nor an rgb value"):
        piece.to_ldraw()


def test_piece_expands_shorthand_direct_colour() -> None:
    piece = Piece(Colour(rgb="#0f0"), Vector(0, 0, 0), Identity(), Brick1X1)

    assert piece.to_ldraw() == "1 0x200FF00 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat"


def test_piece_rejects_translucent_direct_colour() -> None:
    piece = Piece(
        Colour(rgb="#00ff00", alpha=128),
        Vector(0, 0, 0),
        Identity(),
        Brick1X1,
    )

    with pytest.raises(ValueError, match="translucent direct colour"):
        piece.to_ldraw()


def test_malformed_direct_colour_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="Invalid rgb value"):
        Piece(Colour(rgb="not-a-colour"), Vector(0, 0, 0), Identity(), Brick1X1)


def test_piece_suffix_defaults_to_dat() -> None:
    piece = Piece(White, Vector(0, 0, 0), Identity(), Brick1X1)

    assert piece.suffix == ".dat"
    assert piece.reference == "3005.dat"
    assert piece.to_ldraw().endswith(" 3005.dat")
    assert "suffix='.dat'" in repr(piece)


def test_piece_custom_suffix() -> None:
    piece = Piece(White, Vector(0, 0, 0), Identity(), "body", suffix=".LDR")

    assert piece.reference == "body.LDR"
    assert piece.to_ldraw() == "1 15 0 0 0 1 0 0 0 1 0 0 0 1 body.LDR"


def test_group_copy_preserves_suffix() -> None:
    group = Group()
    Piece(White, Vector(0, 0, 0), Identity(), "body", group=group, suffix=".LDR")

    duplicate = group.copy()

    assert duplicate.pieces[0].suffix == ".LDR"


def test_piece_place_defaults() -> None:
    piece = Piece.place(Brick1X1)

    assert piece.to_ldraw() == "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3005.dat"
    assert piece.group is None


def test_piece_place_explicit_arguments() -> None:
    group = Group()
    piece = Piece.place(
        Brick1X1,
        colour=White,
        position=Vector(10, 0, 0),
        matrix=Identity().rotate(90, YAxis),
        group=group,
    )

    assert piece.to_ldraw() == "1 15 10 0 0 0 0 1 0 1 0 -1 0 0 3005.dat"
    assert piece in group.pieces


def test_piece_place_custom_suffix() -> None:
    piece = Piece.place("body", suffix=".LDR")

    assert piece.reference == "body.LDR"
    assert piece.to_ldraw() == "1 16 0 0 0 1 0 0 0 1 0 0 0 1 body.LDR"


def test_piece_place_splits_existing_extension_with_default_suffix() -> None:
    piece = Piece.place("body.ldr", suffix=".dat")

    assert piece.reference == "body.ldr"
    assert piece.to_ldraw() == "1 16 0 0 0 1 0 0 0 1 0 0 0 1 body.ldr"


def test_piece_place_does_not_double_matching_suffix() -> None:
    assert Piece.place("car.ldr", suffix=".ldr").reference == "car.ldr"
    assert Piece.place("CAR.LDR", suffix=".ldr").reference == "CAR.LDR"
    assert Piece.place("my.body", suffix=".ldr").reference == "my.body.ldr"


def test_piece_preserves_suffix_case() -> None:
    piece = Piece(White, Vector(0, 0, 0), Identity(), "body", suffix=".ldr")

    assert piece.suffix == ".ldr"
    assert piece.reference == "body.ldr"


def test_piece_place_preserves_reference_case() -> None:
    piece = Piece.place("3040B.DAT")

    assert piece.reference == "3040B.DAT"


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ("body.ldr", "body.ldr"),
        ("BODY.LDR", "BODY.LDR"),
        ("s\\3001s01.dat", "s\\3001s01.dat"),
    ],
)
def test_piece_place_uses_existing_extension(part: str, expected: str) -> None:
    piece = Piece.place(part)

    assert piece.reference == expected
    assert piece.to_ldraw() == f"1 16 0 0 0 1 0 0 0 1 0 0 0 1 {expected}"


def test_piece_place_accepts_int_colour() -> None:
    piece = Piece.place(Brick1X1, colour=4)

    assert piece.colour == Colour(code=4)


@pytest.fixture
def figure() -> Person:
    return Person(Vector(0, 0, -10))


@pytest.fixture
def full_figure(figure: Person) -> Person:
    figure.left_arm(Yellow, -45)
    figure.left_hand(Yellow, 10)
    figure.right_arm(Yellow, -45)
    figure.right_hand(Yellow, 10)
    figure.left_leg(Yellow, -10)
    figure.right_leg(Yellow, -10)
    return figure


def test_add_hat_valid_head(figure: Person) -> None:
    assert figure.hat(White, HelmetClassic) is None


def test_add_hat_no_head(figure: Person) -> None:
    assert figure.head(Yellow, 30) is not None
    assert figure.hat(White, HelmetClassic) is not None


def test_add_lh_item_nopart(figure: Person, full_figure: Person) -> None:
    assert full_figure.left_hand_item(Light_Grey, Vector(0, 0, -12), -15) is None
    assert (
        full_figure.left_hand_item(Light_Grey, Vector(0, 0, -12), -15, CameraMovie)
        is not None
    )


def test_add_rh_item_nopart(figure: Person, full_figure: Person) -> None:
    assert full_figure.right_hand_item(Light_Grey, Vector(0, 0, -12), -15) is None
    assert (
        full_figure.right_hand_item(Light_Grey, Vector(0, 0, -12), -15, CameraMovie)
        is not None
    )


def test_add_ls_item_nopart(figure: Person, full_figure: Person) -> None:
    assert full_figure.left_shoe(Black, 10) is None
    assert full_figure.left_shoe(Black, 10, Flipper) is not None


def test_add_rs_item_nopart(figure: Person, full_figure: Person) -> None:
    assert full_figure.right_shoe(Black, 10) is None
    assert full_figure.right_shoe(Black, 10, Flipper) is not None


def test_hat_sits_at_head_position(figure: Person) -> None:
    head = figure.head(Yellow)
    hat = figure.hat(White)

    assert hat is not None
    assert hat.part == figure_mod.Hat
    assert hat.position == head.position
    assert hat.position is not head.position
    assert hat.matrix == head.matrix


def test_default_leg_and_hip_parts_are_plain_codes(figure: Person) -> None:
    assert figure.hips(Yellow).part == figure_mod.Hips == "3815"
    assert figure.left_leg(Yellow).part == figure_mod.LegLeft == "3817"
    assert figure.right_leg(Yellow).part == figure_mod.LegRight == "3816"
    assert figure.head(Yellow).part == figure_mod.Head == "3626b"


def test_dependent_piece_propagates_inner_key_errors() -> None:
    class Exploding(Person):
        @dependent_piece("head")
        def boom(self, _head: Piece) -> Piece:
            message = "inner failure"
            raise KeyError(message)

    person = Exploding()
    assert person.boom() is None

    person.head(Yellow)
    with pytest.raises(KeyError, match="inner failure"):
        person.boom()
