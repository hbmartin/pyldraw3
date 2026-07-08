"""Property-based round-trip tests: parse(serialize(x)) == x."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ldraw.colour import Colour
from ldraw.geometry import Matrix, Vector
from ldraw.lines import (
    Comment,
    Line,
    MetaCommand,
    OptionalLine,
    Quadrilateral,
    Triangle,
)
from ldraw.part import HANDLERS, colour_from_str, parse_ldraw_line
from ldraw.pieces import Piece
from ldraw.serialization import format_ldraw_colour, format_ldraw_number

FINITE = st.floats(allow_nan=False, allow_infinity=False)
COORDS = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9)
VECTORS = st.builds(Vector, COORDS, COORDS, COORDS)
MATRICES = st.lists(
    st.lists(COORDS, min_size=3, max_size=3),
    min_size=3,
    max_size=3,
).map(Matrix)
CODED_COLOURS = st.integers(min_value=0, max_value=511).map(Colour)
DIRECT_COLOURS = st.integers(min_value=0, max_value=0xFF_FF_FF).map(
    lambda value: Colour(rgb=f"#{value:06X}", alpha=255),
)
PART_NAMES = st.from_regex(r"[0-9A-Za-z]{1,10}", fullmatch=True)
# The tokenizing parser collapses whitespace, so text is built from single words.
WORDS = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
)
TEXTS = st.lists(WORDS, min_size=1, max_size=5).map(" ".join)

NUMBER_SHAPE = re.compile(r"-?\d+(?:\.\d*[1-9])?")


@given(FINITE)
def test_format_ldraw_number_round_trip(value: float) -> None:
    formatted = format_ldraw_number(value)

    # The zero/integer-snap branches err by at most ZERO_TOLERANCE (1e-12).
    # In the decimal branch, correct rounding to 12 places gives
    # |formatted - value| <= 0.5e-12, and re-parsing picks the nearest double
    # to the decimal string, which is at least as close as value itself, so
    # the total error stays within 1e-12.
    assert abs(float(formatted) - value) <= 1e-12
    assert NUMBER_SHAPE.fullmatch(formatted)


@given(CODED_COLOURS)
def test_coded_colour_round_trip(colour: Colour) -> None:
    parsed = colour_from_str(format_ldraw_colour(colour))

    assert isinstance(parsed, int)
    assert Colour(parsed) == colour
    assert colour == parsed
    assert hash(Colour(parsed)) == hash(colour)


@given(DIRECT_COLOURS)
def test_direct_colour_round_trip(colour: Colour) -> None:
    field = format_ldraw_colour(colour)
    parsed = colour_from_str(field)

    assert isinstance(parsed, Colour)
    assert parsed == colour
    assert hash(parsed) == hash(colour)
    assert format_ldraw_colour(parsed) == field


@given(st.lists(st.integers(0, 0xFF_FF_FF), min_size=2, max_size=2, unique=True))
def test_distinct_direct_colours_are_unequal(values: list[int]) -> None:
    first, second = (Colour(rgb=f"#{value:06X}", alpha=255) for value in values)

    assert first != second
    assert format_ldraw_colour(first) != format_ldraw_colour(second)


@given(
    colour=st.one_of(CODED_COLOURS, DIRECT_COLOURS),
    position=VECTORS,
    matrix=MATRICES,
    part=PART_NAMES,
)
def test_piece_round_trip(
    colour: Colour,
    position: Vector,
    matrix: Matrix,
    part: str,
) -> None:
    fields = Piece(colour, position, matrix, part).to_ldraw().split()
    parsed = HANDLERS[fields[0]](fields[1:])

    assert isinstance(parsed, Piece)
    assert parsed.colour == colour
    assert parsed.part == part
    assert parsed.suffix == ".dat"
    for actual, expected in zip(
        (parsed.position.x, parsed.position.y, parsed.position.z),
        (position.x, position.y, position.z),
        strict=True,
    ):
        assert actual == pytest.approx(expected, abs=1e-12)
    for actual, expected in zip(
        parsed.matrix.flatten(),
        matrix.flatten(),
        strict=True,
    ):
        assert actual == pytest.approx(expected, abs=1e-12)


@given(
    colour=st.one_of(CODED_COLOURS, DIRECT_COLOURS),
    points=st.lists(
        VECTORS,
        min_size=4,
        max_size=4,
    ),
)
def test_geometry_lines_round_trip(colour: Colour, points: list[Vector]) -> None:
    for obj in (
        Line(colour, points[0], points[1]),
        Triangle(colour, points[0], points[1], points[2]),
        Quadrilateral(colour, *points),
        OptionalLine(colour, *points),
    ):
        parsed = parse_ldraw_line(obj.to_ldraw())

        assert type(parsed) is type(obj)
        assert isinstance(parsed, Line | Triangle | Quadrilateral | OptionalLine)
        assert parsed.colour == colour
        for actual_point, expected_point in zip(
            parsed.points,
            obj.points,
            strict=True,
        ):
            for actual, expected in zip(
                (actual_point.x, actual_point.y, actual_point.z),
                (expected_point.x, expected_point.y, expected_point.z),
                strict=True,
            ):
                assert actual == pytest.approx(expected, abs=1e-12)


@given(TEXTS)
def test_comment_round_trip(text: str) -> None:
    assert parse_ldraw_line(Comment(text).to_ldraw()) == Comment(text)


@given(meta_type=WORDS, text=TEXTS)
def test_meta_command_round_trip(meta_type: str, text: str) -> None:
    command = MetaCommand(meta_type, text)

    assert parse_ldraw_line(command.to_ldraw()) == command
