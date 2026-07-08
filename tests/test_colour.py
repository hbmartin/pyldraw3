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


def test_rgb_is_canonicalized_to_hash_rrggbb() -> None:
    assert Colour(rgb="#00FF00").rgb == "#00FF00"
    assert Colour(rgb="#0f0").rgb == "#00FF00"
    assert Colour(rgb="00ff00").rgb == "#00FF00"


def test_codeless_colour_rejects_malformed_rgb() -> None:
    with pytest.raises(ValueError, match="Invalid rgb value"):
        Colour(rgb="not-a-colour")


def test_codeless_colour_rejects_rgb_with_alpha_channel() -> None:
    with pytest.raises(ValueError, match="alpha channel"):
        Colour(rgb="#00ff0080")
    with pytest.raises(ValueError, match="alpha channel"):
        Colour(rgb="#0f08")


def test_coded_colour_rgb_is_also_canonicalized() -> None:
    coded = Colour(code=15, rgb="#ffffff")
    assert coded.code == 15
    assert coded.rgb == "#FFFFFF"
    with pytest.raises(ValueError, match="Invalid rgb value"):
        Colour(code=15, rgb="not-a-colour")


def test_direct_colour_equality() -> None:
    assert Colour(rgb="#FF0000", alpha=255) == Colour(rgb="#FF0000", alpha=255)
    assert Colour(rgb="#FF0000", alpha=255) != Colour(rgb="#00FF00", alpha=255)
    assert Colour(rgb="#FF0000", alpha=255) != Colour(rgb="#FF0000", alpha=128)
    # A missing alpha means opaque, matching serialization semantics.
    assert Colour(rgb="#FF0000") == Colour(rgb="#FF0000", alpha=255)


def test_direct_colour_equality_normalizes_rgb() -> None:
    assert Colour(rgb="#ff0000") == Colour(rgb="#FF0000")
    assert Colour(rgb="#0f0") == Colour(rgb="#00FF00")


def test_direct_colour_hash() -> None:
    distinct = {Colour(rgb="#FF0000", alpha=255), Colour(rgb="#00FF00", alpha=255)}
    assert len(distinct) == 2
    duplicates = {Colour(rgb="#FF0000"), Colour(rgb="#ff0000", alpha=255)}
    assert len(duplicates) == 1


def test_coded_and_direct_colours_are_unequal() -> None:
    assert Colour(code=15, rgb="#FFFFFF") != Colour(rgb="#FFFFFF")


def test_coded_equality_ignores_metadata() -> None:
    assert Colour(code=15) == Colour(15, "White", "#FFFFFF", 255, [])


def test_colour_not_equal_to_other_types() -> None:
    assert Colour() != None  # noqa: E711 - exercises __eq__, not identity
    assert Colour(rgb="#ABCDEF") != None  # noqa: E711
    assert Colour(code=1) != "1"


def test_is_solid_reflects_alpha_and_attributes() -> None:
    assert Colour(code=4, rgb="#C91A09", alpha=255, colour_attributes=[]).is_solid
    assert Colour(code=16).is_solid
    assert not Colour(code=36, rgb="#C91A09", alpha=128).is_solid
    assert not Colour(code=383, colour_attributes=["CHROME"]).is_solid
    assert not Colour(code=114, alpha=128, colour_attributes=["GLITTER"]).is_solid
