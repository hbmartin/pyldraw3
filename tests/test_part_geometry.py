"""Tests for part bounding boxes and stud queries."""

import logging
from pathlib import Path

import pytest

from ldraw.errors import NoGeometryError, PartNotFoundError
from ldraw.geometry import Vector
from ldraw.model import Model
from ldraw.model_summary import ModelSummary, model_bounds
from ldraw.parts import PartReferenceKind, Parts
from ldraw.pieces import Piece

PARTS_LST = """\
9001.dat                       Test Brick
9002.dat                       Empty Part
9003.dat                       Cyclic Part
9005.dat                       Stud Group User
9006.dat                       Optional Line Part
9007.dat                       Uppercase Ref
9008.dat                       Sideways Stud Part
9009.dat                       Rotated Stud Group
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
    "parts/9008.dat": (
        "0 Sideways Stud Part\n"
        "1 16 0 -4 0 1 0 0 0 1 0 0 0 1 stud.dat\n"
        "1 16 0 0 -10 1 0 0 0 0 -1 0 1 0 stud.dat\n"
    ),
    "parts/9009.dat": (
        "0 Rotated Stud Group\n1 16 0 0 0 1 0 0 0 0 -1 0 1 0 stug2.dat\n"
    ),
}


@pytest.fixture
def geometry_parts(tmp_path: Path) -> Parts:
    ldraw_dir = tmp_path / "ldraw"
    for name, content in FILES.items():
        target = ldraw_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (ldraw_dir / "parts.lst").write_text(PARTS_LST)
    (ldraw_dir / "p.lst").write_text(
        "stud.dat                       Stud\n"
        "stud4.dat                      Stud Tube Open\n"
        "stug2.dat                      Stud Group 2 x 1\n",
    )
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
    assert by_name["stud"].up == Vector(0, -1, 0)
    assert by_name["stud"].is_top_stud
    assert by_name["stud"].description == "Stud"
    assert by_name["stud4"].position == Vector(10, 0, 0)
    assert not by_name["stud4"].is_top_stud

    assert geometry_parts.stud_positions("9001") == (Vector(-10, 0, 0),)


def test_sideways_stud_is_not_a_top_stud(geometry_parts: Parts) -> None:
    studs = geometry_parts.studs("9008")

    by_position = {
        (stud.position.x, stud.position.y, stud.position.z): stud for stud in studs
    }
    assert set(by_position) == {(0, -4, 0), (0, 0, -10)}
    sideways = by_position[(0, 0, -10)]
    assert sideways.up == Vector(0, 0, -1)
    assert not sideways.is_top_stud
    assert by_position[(0, -4, 0)].is_top_stud

    assert geometry_parts.stud_positions("9008") == (Vector(0, -4, 0),)


def test_orientation_composes_through_nested_subfiles(geometry_parts: Parts) -> None:
    studs = geometry_parts.studs("9009")

    assert len(studs) == 2
    assert all(stud.up == Vector(0, 0, -1) for stud in studs)
    assert geometry_parts.stud_positions("9009") == ()


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


def test_references_for_reports_typed_direct_references(
    geometry_parts: Parts,
) -> None:
    refs = geometry_parts.references_for("9001")
    by_code = {ref.code: ref for ref in refs}

    assert by_code["stud"].kind is PartReferenceKind.PRIMITIVE
    assert by_code["stud"].description == "Stud"
    assert by_code["stud"].parent_code == "9001"
    assert by_code["stud"].depth == 1
    assert by_code["s/9001s01"].kind is PartReferenceKind.SUBPART
    assert by_code["s/9001s01"].description == "Test Brick Side"
    assert by_code["missing"].kind is PartReferenceKind.UNKNOWN
    assert by_code["missing"].description is None
    assert by_code["missing"].reference == "missing.dat"


def test_references_for_recurses_and_stops_at_cycles(
    geometry_parts: Parts,
) -> None:
    refs = geometry_parts.references_for("9005", recursive=True)

    assert [(ref.parent_code, ref.code, ref.depth) for ref in refs] == [
        ("9005", "stug2", 1),
        ("stug2", "stud", 2),
        ("stug2", "stud", 2),
    ]
    assert len(geometry_parts.references_for("9003", recursive=True)) == 1


def test_model_summary_and_model_bounds_report_geometry_and_skips(
    geometry_parts: Parts,
) -> None:
    model = Model(
        objects=[
            Piece.place("9001", colour=4, position=Vector(10, 0, 0)),
            Piece.place("9002", colour=16),
        ],
    )

    summary = ModelSummary.from_model(model, geometry_parts)

    assert summary.bounds is not None
    assert summary.bounds.min == Vector(-10, -4, -10)
    assert summary.bounds.max == Vector(30, 24, 10)
    assert summary.origin_bounds is not None
    assert summary.origin_bounds.min == Vector(0, 0, 0)
    assert summary.origin_bounds.max == Vector(10, 0, 0)
    assert summary.part_counts == {"9001": 1, "9002": 1}
    assert summary.colour_usage == {4: 1, 16: 1}
    assert summary.occurrence_count == 2
    assert summary.skipped_geometry[0].part == "9002"
    assert "no drawable geometry" in summary.skipped_geometry[0].reason
    assert summary.size_ldu == Vector(40, 28, 20)
    assert summary.size_mm is not None
    assert summary.size_mm.x == pytest.approx(16)
    assert summary.size_mm.y == pytest.approx(11.2)
    assert summary.size_mm.z == pytest.approx(8)
    assert model_bounds(model, geometry_parts) == summary.bounds


def test_empty_model_summary_has_no_bounds(geometry_parts: Parts) -> None:
    summary = ModelSummary.from_model(Model(), geometry_parts)

    assert summary.bounds is None
    assert summary.origin_bounds is None
    assert summary.size_ldu is None
    assert summary.size_mm is None
