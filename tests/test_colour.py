"""Tests for colour functionality."""

from ldraw.colour import Colour


def test_colour_equality() -> None:

    c1 = Colour(code=12)
    c2 = Colour(code=12)

    assert c1 == c2
    assert c1 == 12
    assert c2 == 12
    assert c1 == 12
    assert c2 == 12


def test_colour_hash() -> None:
    c1 = Colour(code=12)
    c2 = Colour(code=12)

    assert len({c1, c2}) == 1
