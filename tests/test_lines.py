"""Tests for lines.py serialization."""

import pytest

from ldraw.colour import Colour
from ldraw.geometry import Vector
from ldraw.lines import (
    Comment,
    Line,
    MetaCommand,
    OptionalLine,
    Quadrilateral,
    Triangle,
)
from ldraw.part import parse_ldraw_line

MAIN = Colour(code=16)
P1 = Vector(0, 0, 0)
P2 = Vector(1, 1, 1)
P3 = Vector(2, 2, 2)
P4 = Vector(3, 3, 3)


def test_line_to_ldraw() -> None:
    line = Line(MAIN, P1, P2)
    assert line.to_ldraw() == "2 16 0 0 0 1 1 1"
    assert str(line) == line.to_ldraw()


def test_triangle_to_ldraw() -> None:
    triangle = Triangle(MAIN, P1, P2, P3)
    assert triangle.to_ldraw() == "3 16 0 0 0 1 1 1 2 2 2"
    assert str(triangle) == triangle.to_ldraw()


def test_quadrilateral_to_ldraw() -> None:
    quad = Quadrilateral(MAIN, P1, P2, P3, P4)
    assert quad.to_ldraw() == "4 16 0 0 0 1 1 1 2 2 2 3 3 3"
    assert str(quad) == quad.to_ldraw()


def test_optional_line_to_ldraw() -> None:
    optional = OptionalLine(MAIN, P1, P2, P3, P4)
    assert optional.to_ldraw() == "5 16 0 0 0 1 1 1 2 2 2 3 3 3"
    assert str(optional) == optional.to_ldraw()
    assert optional.points == [P1, P2, P3, P4]


def test_comment_to_ldraw() -> None:
    assert Comment("A comment").to_ldraw() == "0 A comment"
    assert Comment("").to_ldraw() == "0"
    assert str(Comment("A comment")) == "0 A comment"


def test_meta_command_to_ldraw() -> None:
    assert MetaCommand("CATEGORY", "Brick").to_ldraw() == "0 !CATEGORY Brick"
    assert MetaCommand("LICENSE", "").to_ldraw() == "0 !LICENSE"
    assert str(MetaCommand("CATEGORY", "Brick")) == "0 !CATEGORY Brick"


@pytest.mark.parametrize(
    "obj",
    [
        Line(MAIN, Vector(0.125, -1, 40.0), P2),
        Triangle(MAIN, P1, P2, P3),
        Quadrilateral(MAIN, P1, P2, P3, P4),
        OptionalLine(MAIN, P1, P2, P3, P4),
        Comment("BFC CERTIFY CCW"),
        Comment(""),
        MetaCommand("CATEGORY", "Brick"),
        MetaCommand("LICENSE", ""),
    ],
)
def test_round_trip(obj: object) -> None:
    assert parse_ldraw_line(obj.to_ldraw()) == obj  # type: ignore[attr-defined]


def test_direct_colour_round_trips() -> None:
    line = Line(Colour(rgb="#00FF00", alpha=255), P1, P2)
    parsed = parse_ldraw_line(line.to_ldraw())

    assert isinstance(parsed, Line)
    assert parsed.colour == line.colour
    assert parsed.colour.rgb == "#00FF00"
