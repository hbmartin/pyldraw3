"""Tests for parts loading functionality."""

from typing import Never
from unittest.mock import patch

import pytest

import ldraw
from ldraw.parts import PartError, Parts


def test_load_parts() -> None:
    p = Parts("tests/test_ldraw/ldraw/parts.lst")
    assert len(p.by_name) == 1
    assert len(p.by_code) == 1
    assert next(iter(p.by_name.values())) == "3001"
    assert next(iter(p.by_name.keys())) == "Brick  2 x  4"
    assert next(iter(p.by_code.keys())) == "3001"
    assert next(iter(p.by_code.values())) == "Brick  2 x  4"

    part = p.part(code="3001")

    assert str(part.path) == "tests/test_ldraw/ldraw/parts/3001.dat"


def test_load_primitives() -> None:
    p = Parts("tests/test_ldraw/ldraw/parts.lst")
    assert len(p.primitives_by_name) == 4
    assert len(p.primitives_by_code) == 4
    assert p.primitives_by_name["Box with 5 Faces and All Edges"] == "box5"
    assert p.primitives_by_code["box5"] == "Box with 5 Faces and All Edges"

    part = p.part(code="box5")

    assert str(part.path) == "tests/test_ldraw/ldraw/p/box5.dat"


@patch.object(ldraw.parts.Parts, "try_load", side_effect=OSError)
def test_cantreadpartslst(mocked) -> None:
    pytest.raises(PartError, lambda: Parts("tests/test_ldraw/ldraw/parts.lst"))
