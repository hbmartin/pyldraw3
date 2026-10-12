"""Independently specified mating, engagement, and measurement regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ldraw import Model, Parts, Piece, inspect_model, part_measurements
from ldraw.cli import main
from ldraw.connection_deduplication import deduplicate_interfaces
from ldraw.connection_metadata import parse_ldcad_commands
from ldraw.connection_regions import supported_engagement
from ldraw.connection_types import (
    ConnectionKind,
    CylindricalCaps,
    connection_residual,
)
from ldraw.geometry import Identity, Matrix, Vector

if TYPE_CHECKING:
    from pathlib import Path

IDENTITY = "1 0 0 0 1 0 0 0 1"
FLIP = "1 0 0 0 -1 0 0 0 -1"


@pytest.fixture
def system_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "p" / "stud.dat").write_text(
        "0 Stud\n0 !LDRAW_ORG Primitive\n2 24 -6 -4 -6 6 0 6\n"
    )
    (root / "p" / "stud4.dat").write_text(
        "0 Stud Tube Open\n0 !LDRAW_ORG Primitive\n2 24 -6 -4 -6 6 0 6\n"
    )
    for code, extra in {
        "plate": f"1 16 0 0 0 {IDENTITY} stud.dat\n1 16 0 4 0 {FLIP} stud4.dat\n",
        "inferred": f"1 16 0 4 0 {FLIP} stud4.dat\n",
        "round": "0 !LDCAD SNAP_CYL [gender=F] [pos=0 8 0] "
        "[secs=R 6 4] [id=stud] [caps=B]\n",
        "square": "0 !LDCAD SNAP_CYL [gender=F] [pos=0 8 0] [secs=S 6 8] [caps=B]\n",
        "axle": "0 !LDCAD SNAP_CYL [gender=M] "
        "[secs=A 6 20] [center=true] [caps=none]\n",
        "hole": "0 !LDCAD SNAP_CYL [gender=F] "
        "[secs=R 6 20] [center=true] [caps=none]\n",
        "pin": "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 20] [center=true] [caps=none]\n",
        "cross": "0 !LDCAD SNAP_CYL [gender=F] "
        "[secs=A 6 20] [center=true] [caps=none]\n",
        "mixed": "0 !LDCAD SNAP_CYL [gender=M] "
        "[secs=A 6 10 R 6 10] [center=true] [caps=none] [id=joint]\n",
        "mixedhole": "0 !LDCAD SNAP_CYL [gender=F] "
        "[secs=A 6 10 R 6 10] [center=true] [caps=none] [id=joint]\n",
    }.items():
        (root / "parts" / f"{code}.dat").write_text(
            f"0 {code}\n0 !LDRAW_ORG Part\n2 24 -10 0 -10 10 8 10\n{extra}",
            encoding="utf-8",
        )
    return Parts.from_directory(root, cache=tmp_path / "indexes")


def test_authored_frames_preserve_physical_sections_and_flags() -> None:
    result = parse_ldcad_commands(
        "fixture",
        ["SNAP_CYL [gender=F] [pos=2 10 4] [secs=R 6 4] [caps=B] [slide=false]"],
    )
    female = result.features[0]
    assert female.axis == Vector(0, 1, 0)
    assert female.position == Vector(2, 10, 4)
    assert female.axial_midpoint == Vector(2, 8, 4)
    assert female.profile.caps is CylindricalCaps.B
    assert female.profile.friction is None
    assert female.editor_slide is False
    male = parse_ldcad_commands(
        "fixture",
        ["SNAP_CYL [gender=M] [pos=2 10 4] [secs=R 6 4] [caps=A] [slide=true]"],
    ).features[0]
    assert male.axis == Vector(0, -1, 0)
    assert male.axial_midpoint == female.axial_midpoint
    assert male.profile.friction is None
    assert male.editor_slide is True


@pytest.mark.parametrize("receiver", ["round", "square", "inferred"])
def test_system_snap_application_agrees_with_contacts(
    system_parts: Parts, receiver: str
) -> None:
    model = Model.from_pieces(
        [
            Piece.place("plate", colour=4),
            Piece.place(receiver, colour=2, position=Vector(40, -20, 0)),
        ]
    )
    result = inspect_model(model, system_parts)
    report = result.snap_report(moving=1, fixed=0)
    assert report.candidates
    assert all(item.contact_supported for item in report.candidates)
    candidate = report.candidates[0]
    assert candidate.transform.matrix.det() == pytest.approx(1)
    placed = model.pieces[1]
    placed.position = candidate.transform.position
    placed.matrix = candidate.transform.matrix
    contacts = inspect_model(model, system_parts).connection_contacts()
    assert len(contacts) == 1
    assert contacts[0].residual.penetration > 0
    assert contacts[0].first.axis.dot(contacts[0].second.axis) == pytest.approx(-1)


def test_positive_bearing_engagement_and_pin_cross_rejection(
    system_parts: Parts,
) -> None:
    model = Model.from_pieces([Piece.place("axle"), Piece.place("hole")])
    contacts = inspect_model(model, system_parts).connection_contacts()
    assert len(contacts) == 1
    assert contacts[0].residual.engagement == pytest.approx(20)
    model.pieces[1].position = Vector(0, 20, 0)
    assert inspect_model(model, system_parts).connection_contacts() == ()
    model.pieces[1].position = Vector(0, 19, 0)
    assert inspect_model(model, system_parts).connection_contacts()[
        0
    ].residual.engagement == pytest.approx(1)
    incompatible = Model.from_pieces([Piece.place("pin"), Piece.place("cross")])
    assert inspect_model(incompatible, system_parts).connection_contacts() == ()


def test_mixed_interfaces_preserve_addressable_regions(system_parts: Parts) -> None:
    regions = system_parts.connections("mixed")
    assert [feature.kind for feature in regions] == [
        ConnectionKind.AXLE,
        ConnectionKind.PIN,
    ]
    assert [feature.position.y for feature in regions] == [10, 0]
    assert [feature.feature_id for feature in regions] == [
        "joint:region:0",
        "joint:region:1",
    ]
    model = Model.from_pieces([Piece.place("mixed"), Piece.place("mixedhole")])
    contacts = inspect_model(model, system_parts).connection_contacts()
    assert len(contacts) == 2
    assert all(contact.residual.engagement == pytest.approx(10) for contact in contacts)


def test_blocked_ends_and_equivalent_ports(system_parts: Parts) -> None:
    male = system_parts.connections("pin")[0]
    female = system_parts.connections("hole")[0]
    assert supported_engagement(male, female)
    blocked = replace(female, profile=replace(female.profile, caps=CylindricalCaps.TWO))
    assert not supported_engagement(male, blocked)
    capped = replace(female, profile=replace(female.profile, caps=CylindricalCaps.B))
    assert supported_engagement(male, capped)
    advanced = replace(male, position=male.position + male.axis)
    assert not supported_engagement(advanced, capped)
    equivalent = replace(female, feature_id="duplicate")
    separate = replace(female, position=Vector(20, 0, 0), feature_id="separate")
    assert len(deduplicate_interfaces([female, equivalent, separate])) == 2
    assert (
        connection_residual(male, replace(female, position=Vector(0, 20, 0))).engagement
        == 0
    )


def test_conservative_measurements_and_dependency_cache(
    system_parts: Parts, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    measured = part_measurements(system_parts, "plate")
    assert measured.body_bounds.min.y == 0
    assert measured.body_bounds.max.y == 8
    assert system_parts.geometry("plate").bounds.min.y == -4
    assert measured.stack_height == 8
    assert measured.footprint_studs == ((0, 0),)
    assert not measured.diagnostics
    assert system_parts.measurements("plate") is measured
    unsupported = system_parts.measurements("axle")
    assert unsupported.stack_height is None
    assert unsupported.footprint_studs is None
    system_parts.set_connection_overrides("plate", (), replace_existing=True)
    replacement = system_parts.measurements("plate")
    assert replacement is not measured
    assert replacement.stack_height is None
    assert (
        main(
            [
                "parts",
                "measurements",
                "plate",
                "--library",
                str(system_parts.library_root),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["stack_height"] == 8
    out = tmp_path / "measurements.txt"
    assert (
        main(
            [
                "parts",
                "measurements",
                "plate",
                "--library",
                str(system_parts.library_root),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    assert "body_bounds" in out.read_text()


def test_wide_annular_axes_follow_circular_geometry(system_parts: Parts) -> None:
    root = system_parts.library_root
    (root / "p" / "4-4cyli.dat").write_text("0 Cylinder\n2 24 -1 0 -1 1 1 1\n")
    for code in ("wide-a", "wide-b"):
        (root / "parts" / f"{code}.dat").write_text(
            f"0 Wheel Rim 12 x 11 {code}\n0 !LDRAW_ORG Part\n"
            "2 24 -13 -13 -14 13 13 14\n"
            "1 16 0 0 -14 13 0 0 0 0 13 0 28 0 4-4cyli.dat\n",
        )
    updated = Parts.from_directory(root)
    for code in ("wide-a", "wide-b"):
        rim = next(
            feature
            for feature in updated.connections(code)
            if feature.kind is ConnectionKind.RIM_SEAT
        )
        assert rim.axis == Vector(0, 0, 1)


@pytest.mark.parametrize(
    "matrix", [Identity(), Identity().scale(2, 1, 2), Identity().scale(-1, 1, 1)]
)
def test_rigid_frame_reuse_preserves_general_transform_semantics(
    system_parts: Parts, matrix: Matrix
) -> None:
    from ldraw.connection_placement import place_connections

    features = system_parts.connections("plate")
    position = Vector(10, 20, 30)
    expected = tuple(
        feature.transformed(position=position, matrix=matrix) for feature in features
    )
    actual = place_connections(
        system_parts, code="plate", features=features, position=position, matrix=matrix
    )
    assert actual == expected
    assert (
        place_connections(
            system_parts,
            code="plate",
            features=features,
            position=position,
            matrix=matrix,
        )
        == actual
    )
    distorted = (replace(features[0], frame=Matrix([[1, 0, 0], [0, 0, 0], [0, 0, 1]])),)
    assert place_connections(
        system_parts,
        code="bad",
        features=distorted,
        position=position,
        matrix=Identity(),
    ) == tuple(
        feature.transformed(position=position, matrix=Identity())
        for feature in distorted
    )


def test_embedded_connection_includes_resolve_document_definitions(
    system_parts: Parts,
) -> None:
    from ldraw import parse_model

    model = parse_model(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} custom.dat\n"
        "0 FILE custom.dat\n0 !LDRAW_ORG Part\n2 24 -10 0 -10 10 8 10\n"
        "0 !LDCAD SNAP_INCL [ref=port.dat] [pos=0 8 0]\n"
        "0 FILE port.dat\n0 !LDRAW_ORG Primitive\n"
        "0 !LDCAD SNAP_CYL [gender=F] [secs=S 6 8] [caps=B]\n"
    )
    local = system_parts.with_embedded(model)
    feature = local.connections("custom")[0]
    assert feature.kind is ConnectionKind.STUD_RECEPTACLE
    assert feature.position == Vector(0, 8, 0)
    assert not any(
        "include_not_found" in str(item.code)
        for item in local.geometry("custom").diagnostics
    )
