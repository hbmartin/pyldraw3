"""Tests for colour functionality."""

import pytest

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


def test_codeless_colour_accepts_valid_rgb() -> None:
    assert Colour(rgb="#00FF00").rgb == "#00FF00"
    assert Colour(rgb="#0f0").rgb == "#0f0"


def test_codeless_colour_rejects_malformed_rgb() -> None:
    with pytest.raises(ValueError, match="Invalid rgb value"):
        Colour(rgb="not-a-colour")


def test_codeless_colour_rejects_rgb_with_alpha_channel() -> None:
    with pytest.raises(ValueError, match="alpha channel"):
        Colour(rgb="#00ff0080")
    with pytest.raises(ValueError, match="alpha channel"):
        Colour(rgb="#0f08")


def test_coded_colour_skips_rgb_validation() -> None:
    # Parsed library colours carry a code; their rgb is not revalidated.
    assert Colour(code=15, rgb="#FFFFFF").code == 15
