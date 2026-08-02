"""Physical connection inference, metadata, compatibility, and snapping."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest

from ldraw.connection_metadata import LDCadShadowLibrary, parse_ldcad_commands
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    CylindricalProfile,
    FingerProfile,
    GenericProfile,
    SectionShape,
    connection_residual,
    connections_compatible,
    snap_transform,
)
from ldraw.diagnostics import DiagnosticCode
from ldraw.geometry import Identity, Matrix, Vector, YAxis
from ldraw.inspection import inspect_model
from ldraw.model import parse_model
from ldraw.part_geometry import part_connections
from ldraw.parts import Parts

if TYPE_CHECKING:
    from pathlib import Path

    from ldraw.part import Part

_IDENTITY = "1 0 0 0 1 0 0 0 1"
_FLIP_Y = "1 0 0 0 -1 0 0 0 -1"


@dataclass(eq=False)
class _PartLibraryAdapter:
    _backing: Parts

    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part:
        return self._backing.part(description=description, code=code)


class _RimOnlyCompatibilityLibrary(_PartLibraryAdapter):
    def compatible_tyres(self, rim_code: str) -> tuple[str, ...]:
        return ("tyre",) if rim_code == "rim" else ()


class _TyreOnlyCompatibilityLibrary(_PartLibraryAdapter):
    def compatible_rims(self, tyre_code: str) -> tuple[str, ...]:
        return ("rim",) if tyre_code == "tyre" else ()


def _connection_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    files = {
        "p/clip5.dat": ("0 Clip Primitive\n2 24 -8 -4 -8 8 4 8\n"),
        "p/peghole.dat": ("0 Technic Pin Hole End\n2 24 -8 0 -8 8 2 8\n"),
        "p/connect2.dat": ("0 Technic Pin\n2 24 -6 -20 -6 6 0 6\n"),
        "p/axlehol8.dat": ("0 Technic Axle Hole End\n2 24 -6 0 -6 6 2 6\n"),
        "p/npeghol.dat": ("0 Technic Pin Hole Negative End\n2 24 -8 0 -8 8 2 8\n"),
        "p/clh4.dat": ("0 Click Lock Hinge Half Dual Finger\n2 24 -6 -8 -6 6 8 6\n"),
        "p/clh1.dat": (
            "0 Click Lock Hinge Single Finger for Bricks\n2 24 -6 -8 -6 6 8 6\n"
        ),
        "parts/bar1.dat": ("0 Bar 3L\n0 Name: bar1.dat\n2 24 -4 0 -4 4 60 4\n"),
        "parts/blank.dat": ("0 Blank Tile\n2 24 -10 0 -10 10 4 10\n"),
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
        "parts/nbeam.dat": (
            "0 Technic Brick with Negative Pin Hole\n"
            f"1 16 0 0 0 {_IDENTITY} npeghol.dat\n"
            f"1 16 0 20 0 {_FLIP_Y} npeghol.dat\n"
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
        "blank.dat Blank Tile\n"
        "clipper.dat Minifig Clip\n"
        "inline.dat Bar with Inline Metadata\n"
        "beam.dat Technic Brick with Pin Hole\n"
        "nbeam.dat Technic Brick with Negative Pin Hole\n"
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
        "npeghol.dat Technic Pin Hole Negative End\n"
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
    assert isinstance(axle.profile, CylindricalProfile)
    assert isinstance(axle_hole.profile, CylindricalProfile)
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
    assert isinstance(first_hinge.profile, FingerProfile)
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

    by_object = inspection.snap_candidates(
        inspection.occurrences[1],
        fixed=inspection.occurrences[0],
    )
    assert len(by_object) == 1
    assert by_object[0].moving_occurrence.index == 1

    with pytest.raises(IndexError, match="no occurrence"):
        inspection.snap_candidates(99)
    with pytest.raises(ValueError, match="limit"):
        inspection.snap_candidates(1, limit=-1)
    with pytest.raises(ValueError, match="does not belong"):
        inspection.snap_candidates(aligned_inspection.occurrences[1])
    with pytest.raises(TypeError, match="OccurrenceGeometry or integer"):
        inspection.snap_candidates(cast("int", "1"))
    with pytest.raises(ValueError, match="tolerance"):
        inspection.connection_contacts(tolerance=-1)
    with pytest.raises(ValueError, match="angular_tolerance"):
        inspection.connection_contacts(angular_tolerance=-1)


def test_connection_contacts_skip_blank_and_far_apart_occurrences(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    model = parse_model(
        f"1 16 0 0 0 {_IDENTITY} blank.dat\n"
        f"1 16 0 0 0 {_IDENTITY} bar1.dat\n"
        f"1 16 2000 0 0 {_IDENTITY} clipper.dat\n",
    )

    inspection = inspect_model(model, parts)

    assert inspection.occurrences[0].connections == ()
    assert inspection.connection_contacts() == ()


def test_snap_transform_never_reflects_mirrored_feature_frames(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)
    mirror = Matrix([[-1, 0, 0], [0, 1, 0], [0, 0, 1]])

    axle = _one(parts, "axle", ConnectionKind.AXLE)
    axle_hole = _one(parts, "axlehole", ConnectionKind.AXLE_HOLE)
    mirrored_axle = axle.transformed(position=Vector(0, 0, 0), matrix=mirror)
    assert mirrored_axle.frame.det() == pytest.approx(-1)
    assert mirrored_axle.confidence == axle.confidence
    transform = snap_transform(mirrored_axle, axle_hole)
    assert transform.matrix.det() == pytest.approx(1)
    snapped = mirrored_axle.transformed(
        position=transform.position,
        matrix=transform.matrix,
    )
    assert snapped.position == axle_hole.position
    assert abs(snapped.axis.dot(axle_hole.axis)) == pytest.approx(1)

    bar = _one(parts, "bar1", ConnectionKind.BAR)
    clip = _one(parts, "clipper", ConnectionKind.CLIP)
    mirrored_bar = bar.transformed(position=Vector(0, 0, 0), matrix=mirror)
    assert snap_transform(mirrored_bar, clip).matrix.det() == pytest.approx(1)


def test_snap_transform_rejects_non_orthonormal_feature_frames() -> None:
    feature = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=R 4 8]"],
    ).features[0]
    invalid_frames = (
        Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]),
        Matrix([[1, 0.5, 0], [0, 1, 0], [0, 0, 1]]),
        Matrix([[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
    )

    for frame in invalid_frames:
        with pytest.raises(
            ValueError, match="moving feature frame must be orthonormal"
        ):
            snap_transform(replace(feature, frame=frame), feature)
        with pytest.raises(
            ValueError, match="target feature frame must be orthonormal"
        ):
            snap_transform(feature, replace(feature, frame=frame))


def test_negative_peghole_endpoints_merge_into_through_hole(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    hole = _one(parts, "nbeam", ConnectionKind.PIN_HOLE)

    assert hole.feature_id == "npeghol:through"
    assert hole.position == Vector(0, 10, 0)
    assert hole.length == pytest.approx(20)


def test_leading_flexible_section_is_reported_as_invalid() -> None:
    result = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=_L 4 8 A 6 20]"],
    )

    assert result.features == ()
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.code is DiagnosticCode.CONNECTION_METADATA_INVALID
    assert "adjacent rigid section" in diagnostic.message


def test_flexible_section_with_flexible_neighbour_is_reported_as_invalid() -> None:
    result = parse_ldcad_commands(
        "bar1",
        ["SNAP_CYL [gender=M] [secs=R 4 8 L_ 4 8 _L 4 8 R 4 8]"],
    )

    assert result.features == ()
    assert len(result.diagnostics) == 1
    assert "adjacent rigid section" in result.diagnostics[0].message


def test_inline_include_without_shadow_library_reports_diagnostic() -> None:
    result = parse_ldcad_commands("bar1", ["SNAP_INCL [ref=common.dat]"])

    assert result.features == ()
    assert len(result.diagnostics) == 1
    assert "SNAP_INCL" in result.diagnostics[0].message


def test_zip_shadow_library_resolves_nested_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "shadow.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "shadow/parts/bar1.dat",
            "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 60] [center=true] [id=main]\n",
        )

    library = LDCadShadowLibrary(archive_path)

    result = library.connections_for("bar1")
    assert [feature.feature_id for feature in result.features] == ["main"]
    assert result.features[0].source is ConnectionSource.LDCAD_SHADOW
    assert library.connections_for("missing").features == ()


def test_one_sided_tyre_rim_compatibility_adapters_are_preserved(
    tmp_path: Path,
) -> None:
    parts = _connection_parts(tmp_path)

    rim = next(
        feature
        for feature in part_connections(_RimOnlyCompatibilityLibrary(parts), "rim")
        if feature.kind is ConnectionKind.RIM_SEAT
    )
    tyre = next(
        feature
        for feature in part_connections(_TyreOnlyCompatibilityLibrary(parts), "tyre")
        if feature.kind is ConnectionKind.TYRE_BEAD
    )

    assert rim.compatible_parts == ("tyre",)
    assert tyre.compatible_parts == ("rim",)
    assert rim.source is ConnectionSource.SHORTCUT
    assert tyre.source is ConnectionSource.SHORTCUT


def test_generic_features_mate_only_within_a_shared_group() -> None:
    left = ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=ConnectionRole.MALE,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=GenericProfile("towball"),
        group="towball",
    )
    right = replace(left, role=ConnectionRole.FEMALE)

    assert connections_compatible(left, right)
    assert not connections_compatible(left, replace(right, group="pantograph"))
    assert not connections_compatible(left, replace(right, group=None))
