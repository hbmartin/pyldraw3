"""Tests for utility functions."""

from ldraw.utils import clean, safe_identifier, split_reference


def test_split_reference_preserves_case() -> None:
    assert split_reference("3001.dat") == ("3001", ".dat")
    assert split_reference("3040B.DAT") == ("3040B", ".DAT")
    assert split_reference("car body.ldr") == ("car body", ".ldr")
    assert split_reference("body") == ("body", "")


def test_clean() -> None:
    assert clean("%unclean") == "_unclean"
    assert clean("Brick 1   x 3") == "Brick_1x3"
    assert clean("Brick 1x3") == "Brick_1x3"
    assert clean("Brick 1x   3") == "Brick_1x_3"

    assert clean("Brick%%%%1") == "Brick_1"


def test_safe_identifier() -> None:
    assert safe_identifier("Brick2X4") == "Brick2X4"
    assert safe_identifier("2X2Brick") == "P2X2Brick"
    assert safe_identifier("None") == "None_"
    assert safe_identifier("") is None
