"""Tests for part bounding boxes and stud queries."""

import logging
from pathlib import Path

import pytest

from ldraw.errors import NoGeometryError, PartNotFoundError
from ldraw.geometry import Vector
from ldraw.parts import Parts

PARTS_LST = """\
9001.dat                       Test Brick
9002.dat                       Empty Part
9003.dat                       Cyclic Part
9005.dat                       Stud Group User
9006.dat                       Optional Line Part
9007.dat                       Uppercase Ref
"""

FILES = {
    "p/stud.dat": (
        "0 Stud\n2 24 -6 0 -6 6 0 6\n4 16 -6 -4 -6 -6 -4 6 6 -4 6 6 -4 -6\n"
    ),
    "p/stud4.dat": ("0 Stud Tube Open\n4 16 -8 0 -8 -8 4 -8 8 4 -8 8 0 -8\n"),
    "p/stug2.dat": (
        "0 Stud Group 2 x 1\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n"
        "1 16 20 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n"
    ),
    "parts/s/9001s01.dat": ("0 Test Brick Side\n3 16 -20 0 10 20 0 10 0 24 10\n"),
    "parts/9001.dat": (
        "0 Test Brick\n"
        "4 16 -20 0 -10 -20 24 -10 20 24 -10 20 0 -10\n"
        "1 16 -10 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n"
        "1 16 10 0 0 1 0 0 0 1 0 0 0 1 stud4.dat\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\9001s01.dat\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 missing.dat\n"
    ),
    "parts/9002.dat": "0 Empty Part\n0 Name: 9002.dat\n",
    "parts/9003.dat": (
        "0 Cyclic Part\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 9003.dat\n2 24 0 0 0 4 0 0\n"
    ),
    "parts/9005.dat": (
        "0 Stud Group User\n1 16 0 0 -40 0 0 1 0 1 0 -1 0 0 stug2.dat\n"
    ),
    "parts/9006.dat": (
        "0 Optional Line Part\n5 24 0 0 0 0 10 0 100 100 100 -100 -100 -100\n"
    ),
    "parts/9007.dat": "0 Uppercase Ref\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 STUD.DAT\n",
}


@pytest.fixture
def geometry_parts(tmp_path: Path) -> Parts:
    ldraw_dir = tmp_path / "ldraw"
    for name, content in FILES.items():
        target = ldraw_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (ldraw_dir / "parts.lst").write_text(PARTS_LST)
    return Parts(ldraw_dir / "parts.lst")


def test_bounding_box_folds_geometry_subparts_and_primitives(
    geometry_parts: Parts,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ldraw"):
        box = geometry_parts.bounding_box("9001")

    assert box.min == Vector(-20, -4, -10)
    assert box.max == Vector(20, 24, 10)
    assert box.size == Vector(40, 28, 20)
    assert "missing" in caplog.text.lower()


def test_studs_reports_kind_and_local_position(geometry_parts: Parts) -> None:
    studs = geometry_parts.studs("9001")

    by_name = {stud.name: stud for stud in studs}
    assert set(by_name) == {"stud", "stud4"}
    assert by_name["stud"].position == Vector(-10, 0, 0)
    assert by_name["stud"].is_top_stud
    assert by_name["stud"].description == "Stud"
    assert by_name["stud4"].position == Vector(10, 0, 0)
    assert not by_name["stud4"].is_top_stud

    assert geometry_parts.stud_positions("9001") == (Vector(-10, 0, 0),)


def test_stud_groups_expand_through_rotations(geometry_parts: Parts) -> None:
    positions = sorted(
        (position.x, position.y, position.z)
        for position in geometry_parts.stud_positions("9005")
    )
    assert positions == [(0, 0, -60), (0, 0, -40)]

    box = geometry_parts.bounding_box("9005")
    assert box.min == Vector(-6, -4, -66)
    assert box.max == Vector(6, 0, -34)


def test_optional_line_control_points_do_not_stretch_the_box(
    geometry_parts: Parts,
) -> None:
    box = geometry_parts.bounding_box("9006")

    assert box.min == Vector(0, 0, 0)
    assert box.max == Vector(0, 10, 0)
    assert box.corners() == tuple(
        Vector(0, y, 0) for _ in range(2) for y in (0, 10) for _ in range(2)
    )


def test_uppercase_references_resolve(geometry_parts: Parts) -> None:
    (stud,) = geometry_parts.studs("9007")

    assert stud.name == "stud"
    assert stud.position == Vector(0, 0, 0)


def test_part_without_geometry_raises(geometry_parts: Parts) -> None:
    with pytest.raises(NoGeometryError, match="9002"):
        geometry_parts.bounding_box("9002")
    assert geometry_parts.studs("9002") == ()


def test_unknown_code_raises_part_not_found(geometry_parts: Parts) -> None:
    with pytest.raises(PartNotFoundError):
        geometry_parts.bounding_box("99999")
    with pytest.raises(PartNotFoundError):
        geometry_parts.studs("99999")


def test_reference_cycles_are_skipped_with_a_warning(
    geometry_parts: Parts,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ldraw"):
        box = geometry_parts.bounding_box("9003")

    assert "cycle" in caplog.text
    assert box.min == Vector(0, 0, 0)
    assert box.max == Vector(4, 0, 0)


def test_local_geometry_is_memoized_per_parts_instance(
    geometry_parts: Parts,
) -> None:
    first = geometry_parts.bounding_box("9001")
    second = geometry_parts.bounding_box("9001")

    assert first == second
    from ldraw.part_geometry import _caches

    assert "stud" in _caches[geometry_parts]
