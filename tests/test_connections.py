"""Physical connection inference, metadata, compatibility, and snapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ldraw.connection_metadata import LDCadShadowLibrary
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    GenericProfile,
    SectionShape,
    connection_residual,
    connections_compatible,
    snap_transform,
)
from ldraw.geometry import Identity, Matrix, Vector, YAxis
from ldraw.inspection import inspect_model
from ldraw.model import parse_model
from ldraw.parts import Parts

if TYPE_CHECKING:
    from pathlib import Path

_IDENTITY = "1 0 0 0 1 0 0 0 1"
_FLIP_Y = "1 0 0 0 -1 0 0 0 -1"


def _connection_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    files = {
        "p/clip5.dat": ("0 Clip Primitive\n2 24 -8 -4 -8 8 4 8\n"),
        "p/peghole.dat": ("0 Technic Pin Hole End\n2 24 -8 0 -8 8 2 8\n"),
        "p/connect2.dat": ("0 Technic Pin\n2 24 -6 -20 -6 6 0 6\n"),
        "p/axlehol8.dat": ("0 Technic Axle Hole End\n2 24 -6 0 -6 6 2 6\n"),
        "p/clh4.dat": ("0 Click Lock Hinge Half Dual Finger\n2 24 -6 -8 -6 6 8 6\n"),
        "p/clh1.dat": (
            "0 Click Lock Hinge Single Finger for Bricks\n2 24 -6 -8 -6 6 8 6\n"
        ),
        "parts/bar1.dat": ("0 Bar 3L\n0 Name: bar1.dat\n2 24 -4 0 -4 4 60 4\n"),
        "parts/clipper.dat": (f"0 Minifig Clip\n1 16 0 0 0 {_IDENTITY} clip5.dat\n"),
        "parts/inline.dat": (
            "0 Bar with Inline Metadata\n"
            "0 !LDCAD SNAP_CLEAR\n"
            "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 20] "
            "[center=true] [slide=true] [id=inline-bar]\n"
            "2 24 -4 -10 -4 4 10 4\n"
        ),
        "parts/beam.dat": (
            "0 Technic Brick with Pin Hole\n"
            f"1 16 0 0 0 {_IDENTITY} peghole.dat\n"
            f"1 16 0 20 0 {_FLIP_Y} peghole.dat\n"
        ),
        "parts/pin.dat": (f"0 Technic Pin\n1 16 0 20 0 {_IDENTITY} connect2.dat\n"),
        "parts/axle.dat": (f"0 Technic Axle 2\n1 16 0 0 0 {_IDENTITY} axlehol8.dat\n"),
        "parts/axlehole.dat": (
            "0 Technic Brick with Axle Hole\n"
            f"1 16 0 0 0 {_IDENTITY} axlehol8.dat\n"
            f"1 16 0 20 0 {_FLIP_Y} axlehol8.dat\n"
        ),
        "parts/hinge1.dat": (
            f"0 Hinge Click Finger\n1 16 0 0 0 {_IDENTITY} clh4.dat\n"
        ),
        "parts/hinge2.dat": (
            f"0 Hinge Click Finger Mate\n1 16 0 0 0 {_IDENTITY} clh1.dat\n"
        ),
        "parts/hingepair.dat": (
            "0 Hinge Click Dual Finger Pair\n"
            f"1 16 -5.75 0 0 {_IDENTITY} clh4.dat\n"
            f"1 16 5.75 0 0 {_IDENTITY} clh4.dat\n"
        ),
        "parts/rim.dat": ("0 Wheel Rim 20 x 30\n2 24 -15 -5 -15 15 5 15\n"),
        "parts/tyre.dat": ("0 Tyre 20 x 30\n2 24 -18 -6 -18 18 6 18\n"),
        "parts/wheelc01.dat": (
            "0 Wheel Rim 20 x 30 with Tyre 20 x 30\n"
            f"1 16 0 0 0 {_IDENTITY} rim.dat\n"
            f"1 16 0 0 0 {_IDENTITY} tyre.dat\n"
        ),
    }
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (root / "parts.lst").write_text(
        "bar1.dat Bar 3L\n"
        "clipper.dat Minifig Clip\n"
        "inline.dat Bar with Inline Metadata\n"
        "beam.dat Technic Brick with Pin Hole\n"
        "pin.dat Technic Pin\n"
        "axle.dat Technic Axle 2\n"
        "axlehole.dat Technic Brick with Axle Hole\n"
        "hinge1.dat Hinge Click Finger\n"
        "hinge2.dat Hinge Click Finger Mate\n"
        "hingepair.dat Hinge Click Dual Finger Pair\n"
        "rim.dat Wheel Rim 20 x 30\n"
        "tyre.dat Tyre 20 x 30\n"
        "wheelc01.dat Wheel Rim 20 x 30 with Tyre 20 x 30\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text(
        "clip5.dat Clip Primitive\n"
        "peghole.dat Technic Pin Hole End\n"
        "connect2.dat Technic Pin\n"
        "axlehol8.dat Technic Axle Hole End\n"
        "clh4.dat Click Lock Hinge Half Dual Finger\n"
        "clh1.dat Click Lock Hinge Single Finger for Bricks\n",
        encoding="utf-8",
    )
    return Parts(root / "parts.lst")


def _one(parts: Parts, code: str, kind: ConnectionKind) -> ConnectionFeature:
    return next(feature for feature in parts.connections(code) if feature.kind is kind)


def test_infers_bar_clip_pin_hole_axle_and_hinge_semantics(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)

    bar = _one(parts, "bar1", ConnectionKind.BAR)
    clip = _one(parts, "clipper", ConnectionKind.CLIP)
    assert connections_compatible(bar, clip)
    assert bar.source is ConnectionSource.HEURISTIC
    assert clip.source is ConnectionSource.PRIMITIVE
    assert clip.freedoms == {
        ConnectionFreedom.ROTATE,
        ConnectionFreedom.SLIDE,
    }

    hole = _one(parts, "beam", ConnectionKind.PIN_HOLE)
    pin = _one(parts, "pin", ConnectionKind.PIN)
    assert hole.feature_id == "peghole:through"
    assert hole.position == Vector(0, 10, 0)
    assert hole.length == pytest.approx(20)
    assert connections_compatible(pin, hole)

    axle = _one(parts, "axle", ConnectionKind.AXLE)
    axle_hole = _one(parts, "axlehole", ConnectionKind.AXLE_HOLE)
    assert axle.profile.primary_shape is SectionShape.AXLE
    assert axle_hole.profile.primary_shape is SectionShape.AXLE
    assert axle.freedoms == {ConnectionFreedom.SLIDE}
    assert connections_compatible(axle, axle_hole)

    quarter_turned = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Identity().rotate(90, YAxis),
    )
    diagonally_turned = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Identity().rotate(45, YAxis),
    )
    assert connection_residual(
        quarter_turned, axle_hole
    ).roll_alignment == pytest.approx(1)
    assert connection_residual(
        diagonally_turned, axle_hole
    ).roll_alignment == pytest.approx(2**-0.5)
    assert snap_transform(quarter_turned, axle_hole).matrix.flatten() == pytest.approx(
        Identity().flatten(),
        abs=1e-12,
    )
    degenerate = axle.transformed(
        position=Vector(0, 0, 0),
        matrix=Matrix([[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
    )
    assert degenerate.confidence == 0
    assert degenerate.radial == Vector(0, 0, 0)
    assert not connections_compatible(degenerate, axle_hole)
    with pytest.raises(ValueError, match="radius tolerance"):
        connections_compatible(axle, axle_hole, radius_tolerance=-1)

    first_hinge = _one(parts, "hinge1", ConnectionKind.HINGE)
    second_hinge = _one(parts, "hinge2", ConnectionKind.HINGE)
    assert first_hinge.profile.detents == tuple(index * 22.5 for index in range(9))
    assert first_hinge.freedoms == {ConnectionFreedom.DISCRETE_ROTATE}
    assert connections_compatible(first_hinge, second_hinge)
    assert not connections_compatible(first_hinge, first_hinge)
    hinge_pair = tuple(
        feature
        for feature in parts.connections("hingepair")
        if feature.kind is ConnectionKind.HINGE
    )
    assert len(hinge_pair) == 1
    assert hinge_pair[0].feature_id == "clh4:complete"


def test_derives_tyre_rim_pairs_and_marks_complete_shortcut_occupied(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    assert parts.compatible_tyres("rim") == ("tyre",)
    assert parts.compatible_rims("tyre") == ("rim",)
    relation = parts.tyre_rim_compatibility[0]
    assert (relation.first, relation.second, relation.evidence) == (
        "rim",
        "tyre",
        "wheelc01",
    )

    rim = _one(parts, "rim", ConnectionKind.RIM_SEAT)
    tyre = _one(parts, "tyre", ConnectionKind.TYRE_BEAD)
    assert rim.compatible_parts == ("tyre",)
    assert tyre.compatible_parts == ("rim",)
    assert connections_compatible(rim, tyre)

    assembly = parts.connections("wheelc01")
    fitted = tuple(
        feature
        for feature in assembly
        if feature.kind in {ConnectionKind.RIM_SEAT, ConnectionKind.TYRE_BEAD}
    )
    assert len(fitted) == 2
    assert all(feature.occupied for feature in fitted)
    assert {feature.occupied_by for feature in fitted} == {"wheelc01"}
    assert not connections_compatible(fitted[0], fitted[1])


def test_shadow_metadata_can_clear_include_grid_and_supersede_inference(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    shadow = tmp_path / "shadow"
    (shadow / "parts").mkdir(parents=True)
    (shadow / "p").mkdir()
    (shadow / "parts" / "bar1.dat").write_text(
        "0 !LDCAD SNAP_CLEAR\n"
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 60] "
        "[center=true] [slide=true] [id=main]\n",
        encoding="utf-8",
    )
    (shadow / "p" / "common.dat").write_text(
        "0 !LDCAD SNAP_GEN [gender=F] [group=test] [id=socket]\n",
        encoding="utf-8",
    )
    (shadow / "parts" / "clipper.dat").write_text(
        "0 !LDCAD SNAP_CLEAR\n"
        "0 !LDCAD SNAP_INCL [ref=common.dat] [grid=C 2 C 1 20 0]\n",
        encoding="utf-8",
    )

    assert _one(parts, "bar1", ConnectionKind.BAR).source is ConnectionSource.HEURISTIC
    parts.add_connection_shadow(shadow)

    bar_connections = parts.connections("bar1")
    assert len(bar_connections) == 1
    assert bar_connections[0].feature_id == "main"
    assert bar_connections[0].source is ConnectionSource.LDCAD_SHADOW
    included = parts.connections("clipper")
    assert len(included) == 2
    assert {feature.position.x for feature in included} == {-10, 10}
    assert all(feature.owner_code == "clipper" for feature in included)

    direct = LDCadShadowLibrary(shadow).connections_for("bar1")
    assert direct.clear_all is True
    assert direct.diagnostics == ()


def test_inline_ldcad_metadata_is_consumed_without_a_shadow_library(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    connections = parts.connections("inline")

    assert len(connections) == 1
    assert connections[0].feature_id == "inline-bar"
    assert connections[0].kind is ConnectionKind.BAR
    assert connections[0].source is ConnectionSource.LDCAD_INLINE


def test_overrides_are_authoritative_and_invalidate_cached_geometry(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    override = ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=ConnectionRole.FEMALE,
        position=Vector(1, 2, 3),
        frame=Identity(),
        profile=GenericProfile("custom"),
        group="custom",
    )

    assert _one(parts, "bar1", ConnectionKind.BAR)
    parts.set_connection_overrides("bar1", (override,), replace_existing=True)

    connections = parts.connections("bar1")
    assert len(connections) == 1
    assert connections[0].source is ConnectionSource.OVERRIDE
    assert connections[0].owner_code == "bar1"
    assert connections[0].position == Vector(1, 2, 3)

    parts.clear_connection_overrides("bar1")
    assert _one(parts, "bar1", ConnectionKind.BAR).source is ConnectionSource.HEURISTIC


def test_world_contacts_and_ranked_snap_candidates(tmp_path: Path) -> None:
    parts = _connection_parts(tmp_path)
    aligned = parse_model(
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n1 16 0 30 0 {_IDENTITY} clipper.dat\n",
    )
    aligned_inspection = inspect_model(aligned, parts)

    contacts = aligned_inspection.connection_contacts()
    assert len(contacts) == 1
    assert {contacts[0].first.kind, contacts[0].second.kind} == {
        ConnectionKind.BAR,
        ConnectionKind.CLIP,
    }
    assert contacts[0].residual.distance == pytest.approx(0)

    separated = parse_model(
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n1 16 20 30 0 {_IDENTITY} clipper.dat\n",
    )
    inspection = inspect_model(separated, parts)
    assert inspection.connection_contacts() == ()

    candidates = inspection.snap_candidates(1, fixed=0)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.residual.distance == pytest.approx(20)
    assert candidate.transform.position == Vector(0, 30, 0)
    assert candidate.transform.matrix == Identity()

    with pytest.raises(IndexError, match="no occurrence"):
        inspection.snap_candidates(99)
    with pytest.raises(ValueError, match="limit"):
        inspection.snap_candidates(1, limit=-1)
    with pytest.raises(ValueError, match="tolerance"):
        inspection.connection_contacts(tolerance=-1)
    with pytest.raises(ValueError, match="angular_tolerance"):
        inspection.connection_contacts(angular_tolerance=-1)
