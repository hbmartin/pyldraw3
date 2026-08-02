"""LDCad 1.6 metadata grammar, source, and Studio compatibility coverage."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ldraw.connection_metadata import (
    LDCadShadowLibrary,
    ShadowConnectionResult,
    parse_ldcad_commands,
)
from ldraw.connection_studio import StudioConnectionLibrary
from ldraw.connection_types import (
    AnnularProfile,
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    CylindricalCaps,
    CylindricalProfile,
    CylindricalSection,
    FingerProfile,
    GenericBounds,
    GenericBoundsKind,
    GenericMatch,
    GenericPlacement,
    GenericProfile,
    SectionShape,
    angular_alignment_within,
    connection_residual,
    connections_compatible,
    frame_for_axis,
)
from ldraw.diagnostics import DiagnosticCode
from ldraw.geometry import Identity, Matrix, Vector, YAxis

if TYPE_CHECKING:
    from pathlib import Path


def test_all_supported_ldcad_records_preserve_profile_semantics() -> None:
    result = parse_ldcad_commands(
        "sample",
        (
            (
                "SNAP_CYL [id=axle] [group=drive] [gender=F] "
                "[secs=A 2e0 4 _L 2.1 1] [caps=B] [center=true] [slide=true] "
                "[scale=YandR] [mirror=cor] [pos=1 2 3] "
                "[ori=1 0 0 0 1 0 0 0 1] [grid=C 2 C 1 C 2 20 10 30]"
            ),
            (
                "SNAP_CLP [id=clip] [group=drive] [gender=F] [radius=4e0] "
                "[length=8] [center=true] [slide=true] [scale=none] "
                "[mirror=none] [pos=4 5 6] [ori=1 0 0 0 1 0 0 0 1]"
            ),
            (
                "SNAP_FGR [id=fingers] [group=click_hinge] [gender=M] "
                "[genderOfs=F] [seq=2.5 8 2.5] [radius=6] [center=false] "
                "[scale=YOnly] [mirror=corx]"
            ),
            (
                "SNAP_GEN [id=ball] [group=joint] [gender=M] "
                "[bounding=sph 8] [match=size] [placement=free] "
                "[scale=ROnly] [mirror=corz]"
            ),
        ),
        source="sample.dat",
    )

    assert result.source_count == 1
    assert result.recognized_record_count == 4
    assert result.unsupported_record_count == result.invalid_record_count == 0
    assert len(result.features) == 7

    axles = result.features[:4]
    assert {feature.feature_id for feature in axles} == {
        "axle@L1:I0",
        "axle@L1:I1",
        "axle@L1:I2",
        "axle@L1:I3",
    }
    assert {
        (feature.position.x, feature.position.y, feature.position.z)
        for feature in axles
    } == {(-9, 2, -12), (-9, 2, 18), (11, 2, -12), (11, 2, 18)}
    axle = axles[0]
    assert axle.kind is ConnectionKind.AXLE_HOLE
    assert axle.axis == Vector(0, -1, 0)
    assert axle.metadata_id == "axle"
    assert axle.scale_inheritance == "yandr"
    assert axle.mirror_inheritance == "cor"
    assert axle.freedoms == {
        ConnectionFreedom.ROTATE,
        ConnectionFreedom.SLIDE,
    }
    assert isinstance(axle.profile, CylindricalProfile)
    assert axle.profile.centered
    assert axle.profile.caps is CylindricalCaps.B
    assert axle.profile.primary_shape is SectionShape.AXLE
    assert axle.profile.sections[1].flexible
    assert axle.connection_provenance is not None
    assert axle.connection_provenance.line_number == 1
    assert axle.provenance == ("sample.dat:1",)

    clip, fingers, ball = result.features[4:]
    assert clip.kind is ConnectionKind.CLIP
    assert clip.role is ConnectionRole.FEMALE
    assert isinstance(clip.profile, CylindricalProfile)
    assert clip.profile.mating_radius == 4
    assert clip.profile.centered
    assert clip.position == Vector(4, 5, 6)

    assert isinstance(fingers.profile, FingerProfile)
    assert fingers.profile.sequence == (2.5, 8, 2.5)
    assert fingers.profile.first_role is ConnectionRole.FEMALE
    assert not fingers.profile.centered

    assert isinstance(ball.profile, GenericProfile)
    assert ball.profile.bounds == GenericBounds(GenericBoundsKind.SPHERE, (8,))
    assert ball.profile.match is GenericMatch.SIZE
    assert ball.profile.placement is GenericPlacement.FREE
    assert ball.freedoms == {ConnectionFreedom.FREE_ROTATE}


@pytest.mark.parametrize(
    ("bounding", "kind", "dimensions", "length"),
    [
        ("pnt", GenericBoundsKind.POINT, (), 0),
        ("point", GenericBoundsKind.POINT, (), 0),
        ("box 10 8 6", GenericBoundsKind.BOX, (10, 8, 6), 16),
        ("cube 8", GenericBoundsKind.BOX, (8, 8, 8), 16),
        ("cyl 8 20", GenericBoundsKind.CYLINDER, (8, 20), 20),
        ("sphere 8", GenericBoundsKind.SPHERE, (8,), 16),
    ],
)
def test_generic_bounding_shapes(
    bounding: str,
    kind: GenericBoundsKind,
    dimensions: tuple[float, ...],
    length: float,
) -> None:
    result = parse_ldcad_commands(
        "generic",
        (f"SNAP_GEN [group=g] [gender=F] [bounding={bounding}]",),
    )

    assert result.invalid_record_count == 0
    profile = result.features[0].profile
    assert isinstance(profile, GenericProfile)
    assert profile.bounds == GenericBounds(kind, dimensions)
    assert profile.length == length


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (
            "SNAP_CYL [secs=R 6 4] [secs=R 4 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R 6 4",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL stray [secs=R 6 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs R 6 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [1bad=value] [secs=R 6 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R nan 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [pos=1 2]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [ori=1 0 0 0 0 0 0 0 1]",
            DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [ori=1 1 0 0 1 0 0 0 1]",
            DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [grid=2 2 20]",
            DiagnosticCode.CONNECTION_INVALID_GRID,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [grid=0 1 20 20]",
            DiagnosticCode.CONNECTION_INVALID_GRID,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [scale=all]",
            DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [mirror=flip]",
            DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [gender=X]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [caps=three]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R 6 4] [center=yes]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=R -6 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CYL [secs=T 6 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_FGR [seq=one two]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_CLP [radius=0]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_FGR [seq=2 -1 2]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [bounding=box 1 2]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [bounding=cube 1 2]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [bounding=sph -1]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [bounding=cone 2 4]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [match=everything]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_GEN [placement=fixed]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
        (
            "SNAP_INCL [ref=missing.dat] [slide=yes]",
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        ),
    ],
)
def test_invalid_ldcad_values_recover_per_record(
    record: str,
    code: DiagnosticCode,
) -> None:
    result = parse_ldcad_commands(
        "bad",
        (record, "SNAP_CLP [id=recovered]"),
    )

    assert result.invalid_record_count == 1
    assert result.recognized_record_count == 1
    assert result.features[0].feature_id == "recovered"
    assert result.diagnostics[0].code is code


@pytest.mark.parametrize("record", ["SNAP_INCL", "SNAP_CYL", "SNAP_FGR"])
def test_missing_required_values_have_stable_diagnostic(record: str) -> None:
    result = parse_ldcad_commands("bad", (record,))

    assert result.invalid_record_count == 1
    assert (
        result.diagnostics[0].code is DiagnosticCode.CONNECTION_MISSING_REQUIRED_OPTION
    )


def test_unknown_records_and_options_count_once_per_record() -> None:
    result = parse_ldcad_commands(
        "partial",
        (
            "SNAP_SPH [gender=M] [radius=8]",
            "SNAP_FUTURE [foo=bar]",
            "SNAP_CLP [id=clip] [future=a] [another=b]",
        ),
    )

    assert result.recognized_record_count == 1
    assert result.unsupported_record_count == 3
    assert result.invalid_record_count == 0
    assert len(result.features) == 1
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        DiagnosticCode.CONNECTION_UNSUPPORTED_RECORD,
        DiagnosticCode.CONNECTION_UNSUPPORTED_RECORD,
        DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
        DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
    ]


def test_clear_uses_raw_metadata_ids_and_repeated_ids_are_disambiguated() -> None:
    result = parse_ldcad_commands(
        "ids",
        (
            "SNAP_CLP [id=Same]",
            "SNAP_CLP [id=same] [pos=1 0 0]",
            "SNAP_CLEAR [id=SAME]",
            "SNAP_CLP [id=final]",
            "SNAP_CLEAR",
            "SNAP_CLP [id=after]",
        ),
    )

    assert result.clear_all
    assert result.clear_ids == ()
    assert [feature.feature_id for feature in result.features] == ["after"]
    assert result.recognized_record_count == 6


def _shadow_documents() -> dict[str, str]:
    return {
        "PaRtS/ROOT.DAT": (
            "0 Root\n"
            "0 !LDCAD SNAP_CYL [id=local] [gender=M] [secs=R 4 8]\n"
            "0 !LDCAD SNAP_INCL [id=inc] [ref=s/child.dat] "
            "[grid=2 1 10 0] [slide=true]\n"
        ),
        "PARTS/S/Child.dat": (
            "0 Child\n"
            "0 !LDCAD SNAP_CLP [id=clip]\n"
            "0 !LDCAD SNAP_INCL [id=primitive] [ref=8/socket.dat]\n"
        ),
        "P/8/Socket.DAT": (
            "0 Socket\n"
            "0 !LDCAD SNAP_CYL [id=hole] [gender=F] "
            "[caps=none] [secs=R 4 8]\n"
        ),
    }


def _write_shadow_directory(root: Path) -> None:
    for relative, text in _shadow_documents().items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _write_shadow_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for relative, text in _shadow_documents().items():
            archive.writestr(f"library/{relative}", text)


def test_directory_zip_and_csl_sources_resolve_identically(tmp_path: Path) -> None:
    directory = tmp_path / "shadow"
    archive = tmp_path / "shadow.zip"
    csl = tmp_path / "shadow.csl"
    _write_shadow_directory(directory)
    _write_shadow_archive(archive)
    _write_shadow_archive(csl)

    results = tuple(
        LDCadShadowLibrary(source).connections_for("ROOT.dat")
        for source in (directory, archive, csl)
    )

    assert all(result.source_count == 3 for result in results)
    assert all(result.recognized_record_count == 5 for result in results)
    assert all(len(result.features) == 5 for result in results)
    assert all(not result.diagnostics for result in results)
    signatures = tuple(
        tuple(
            (
                feature.feature_id,
                feature.metadata_id,
                feature.kind,
                feature.position,
                feature.axis,
                feature.freedoms,
                feature.profile,
                (
                    feature.connection_provenance.line_number
                    if feature.connection_provenance is not None
                    else None
                ),
            )
            for feature in result.features
        )
        for result in results
    )
    assert signatures[0] == signatures[1] == signatures[2]
    assert results[1].features[-1].connection_provenance is not None
    assert results[1].features[-1].connection_provenance.archive_member is not None
    assert len(results[1].features[-1].connection_provenance.include_chain) >= 4


def test_shadow_document_line_numbers_survive_header_lines(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    target = root / "parts" / "lined.dat"
    target.parent.mkdir(parents=True)
    target.write_text(
        "0 Shadow header\n"
        "0 second header line\n"
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 4 8]\n",
        encoding="utf-8",
    )

    result = LDCadShadowLibrary(root).connections_for("lined")

    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.feature_id == "snap_cyl@L3:I0"
    assert "@L3" in feature.feature_id
    assert feature.connection_provenance is not None
    assert feature.connection_provenance.line_number == 3


def test_shadow_reparse_is_deterministic_across_instances(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    _write_shadow_directory(root)

    def signature(
        result: ShadowConnectionResult,
    ) -> tuple[tuple[str | None, tuple[float, float, float]], ...]:
        return tuple(
            (
                feature.feature_id,
                (feature.position.x, feature.position.y, feature.position.z),
            )
            for feature in result.features
        )

    first = LDCadShadowLibrary(root).connections_for("ROOT.dat")
    second = LDCadShadowLibrary(root).connections_for("ROOT.dat")

    assert len(first.features) == 5
    assert signature(first) == signature(second)


def test_inline_includes_fold_configured_sources_in_registration_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, radius in ((first, 4), (second, 6)):
        target = root / "parts" / "shared.dat"
        target.parent.mkdir(parents=True)
        target.write_text(
            f"0 !LDCAD SNAP_CYL [id=shared] [gender=M] [secs=R {radius} 8]\n",
            encoding="utf-8",
        )

    result = parse_ldcad_commands(
        "owner",
        ("SNAP_INCL [id=include] [ref=shared.dat]",),
        connection_shadows=(first, second),
    )

    assert result.source_count == 3
    assert result.recognized_record_count == 3
    assert len(result.features) == 1
    profile = result.features[0].profile
    assert isinstance(profile, CylindricalProfile)
    assert profile.mating_radius == 6
    assert any(
        diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
        for diagnostic in result.diagnostics
    )


def test_missing_and_cyclic_includes_preserve_unrelated_features(
    tmp_path: Path,
) -> None:
    root = tmp_path / "shadow"
    parts = root / "parts"
    parts.mkdir(parents=True)
    (parts / "a.dat").write_text(
        "0 !LDCAD SNAP_CLP [id=a]\n"
        "0 !LDCAD SNAP_INCL [ref=b.dat]\n"
        "0 !LDCAD SNAP_INCL [ref=missing.dat]\n",
        encoding="utf-8",
    )
    (parts / "b.dat").write_text(
        "0 !LDCAD SNAP_CLP [id=b]\n0 !LDCAD SNAP_INCL [ref=a.dat]\n",
        encoding="utf-8",
    )

    result = LDCadShadowLibrary(root).connections_for("a")

    assert {feature.metadata_id for feature in result.features} == {"a", "b"}
    assert (
        sum(
            diagnostic.code is DiagnosticCode.CONNECTION_INCLUDE_CYCLE
            for diagnostic in result.diagnostics
        )
        == 1
    )
    assert (
        sum(
            diagnostic.code is DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND
            for diagnostic in result.diagnostics
        )
        == 1
    )
    assert result.invalid_record_count == 2


def test_archive_decode_errors_are_non_fatal_metadata_diagnostics(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "bad.csl"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("parts/bad.dat", b"\xff")

    result = LDCadShadowLibrary(archive_path).connections_for("bad")

    assert result.source_count == result.invalid_record_count == 1
    assert not result.features
    assert result.diagnostics[0].code is DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE


def test_ldcad_inheritance_scaling_and_reflection_policies() -> None:
    none = parse_ldcad_commands(
        "scale",
        ("SNAP_CLP [id=none] [scale=none]",),
    ).features[0]
    y_only = parse_ldcad_commands(
        "scale",
        ("SNAP_CLP [id=y] [scale=YOnly]",),
    ).features[0]
    radial_only = parse_ldcad_commands(
        "scale",
        ("SNAP_CLP [id=r] [scale=ROnly]",),
    ).features[0]
    both = parse_ldcad_commands(
        "scale",
        ("SNAP_CLP [id=both] [scale=YandR]",),
    ).features[0]
    cylinder = parse_ldcad_commands(
        "scale",
        ("SNAP_CYL [id=cyl] [secs=R 6 4]",),
    ).features[0]

    axial = Identity().scale(1, 2, 1)
    radial = Identity().scale(2, 1, 2)
    combined = Identity().scale(2, 3, 2)
    asymmetric = Identity().scale(2, 1, 3)
    reflected = Identity().scale(-1, 1, 1)

    assert none.transformed(position=Vector(0, 0, 0), matrix=axial).confidence == 0
    assert y_only.transformed(
        position=Vector(0, 0, 0), matrix=axial
    ).profile.length == pytest.approx(16)
    assert y_only.transformed(position=Vector(0, 0, 0), matrix=radial).confidence == 0
    assert radial_only.transformed(
        position=Vector(0, 0, 0), matrix=radial
    ).profile.mating_radius == pytest.approx(8)
    assert (
        radial_only.transformed(position=Vector(0, 0, 0), matrix=axial).confidence == 0
    )
    assert both.transformed(position=Vector(0, 0, 0), matrix=combined).confidence > 0
    assert both.transformed(position=Vector(0, 0, 0), matrix=asymmetric).confidence == 0
    assert none.transformed(position=Vector(0, 0, 0), matrix=reflected).confidence == 0
    assert cylinder.mirror_inheritance == "cor"
    assert (
        cylinder.transformed(position=Vector(0, 0, 0), matrix=reflected).confidence > 0
    )


def _studio_document() -> dict[str, object]:
    rows: list[dict[str, object]] = [
        {"id": "stud", "type": "stud", "gender": "M"},
        {"id": "stud-hole", "type": "stud", "gender": "F"},
        {"id": "pin", "type": "technic-pin", "gender": "M"},
        {"id": "pin-hole", "type": "pin", "gender": "F"},
        {"id": "axle", "type": "axle", "gender": "male"},
        {"id": "axle-hole", "type": "axle", "gender": "female"},
        {"id": "bar", "type": "bar", "gender": "M"},
        {"id": "clip", "type": "clip", "gender": "F"},
        {"id": "hinge", "type": "hinge", "gender": "bidirectional"},
        {
            "id": "rim",
            "type": "tyre_rim",
            "gender": "M",
            "radius": 15,
            "width": 5,
        },
        {
            "id": "tyre",
            "type": "tyre_rim",
            "gender": "F",
            "radius": 15,
            "width": 5,
        },
        {"id": "ball", "type": "ball-joint", "gender": "neutral"},
        {"id": "turntable", "type": "turntable", "gender": "neutral"},
        {"id": "same", "type": "pin", "gender": "M"},
        {"id": "same", "type": "pin", "gender": "F"},
    ]
    for row in rows:
        row.setdefault("position", [1, 2, 3])
        row.setdefault("axis", [0, -1, 0])
        row.setdefault("radius", 4)
        row.setdefault("length", 8)
    return {"parts": [{"part_id": "parts\\3001.DAT", "connections": rows}]}


def test_studio_connectivity_schema_maps_all_supported_types(tmp_path: Path) -> None:
    source = tmp_path / "studio.json"
    source.write_text(json.dumps(_studio_document()), encoding="utf-8")

    result = StudioConnectionLibrary(source).connections_for("3001.dat")

    assert result.source_count == 1
    assert result.recognized_record_count == 15
    assert result.invalid_record_count == result.unsupported_record_count == 0
    assert {feature.kind for feature in result.features} == {
        ConnectionKind.STUD,
        ConnectionKind.STUD_RECEPTACLE,
        ConnectionKind.PIN,
        ConnectionKind.PIN_HOLE,
        ConnectionKind.AXLE,
        ConnectionKind.AXLE_HOLE,
        ConnectionKind.BAR,
        ConnectionKind.CLIP,
        ConnectionKind.HINGE,
        ConnectionKind.RIM_SEAT,
        ConnectionKind.TYRE_BEAD,
        ConnectionKind.GENERIC,
    }
    assert result.features[0].position == Vector(1, 2, 3)
    assert result.features[0].axis == Vector(0, -1, 0)
    assert result.features[0].source is ConnectionSource.STUDIO
    assert isinstance(result.features[8].profile, FingerProfile)
    assert isinstance(result.features[9].profile, AnnularProfile)
    assert isinstance(result.features[11].profile, GenericProfile)
    assert result.features[11].freedoms == {ConnectionFreedom.FREE_ROTATE}
    assert [feature.feature_id for feature in result.features[-2:]] == [
        "same@P0:I13",
        "same@P0:I14",
    ]
    assert all(feature.metadata_id == "same" for feature in result.features[-2:])


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"parts": [None, {"part_id": 3}]},
        {"parts": [{"part_id": "bad", "connections": "not-a-list"}]},
        {
            "parts": [
                {
                    "part_id": "bad",
                    "connections": [
                        None,
                        {},
                        {"type": "future", "position": [0, 0, 0], "axis": [0, 1, 0]},
                        {"type": "pin", "position": [0, 0], "axis": [0, 1, 0]},
                        {"type": "pin", "position": [0, 0, 0], "axis": [0, 0, 0]},
                        {
                            "type": "pin",
                            "position": [0, 0, 0],
                            "axis": [0, 1, float("inf")],
                        },
                        {
                            "type": "pin",
                            "position": [0, 0, 0],
                            "axis": [0, 1, 0],
                            "gender": "X",
                        },
                        {
                            "type": "pin",
                            "position": [0, 0, 0],
                            "axis": [0, 1, 0],
                            "radius": 0,
                        },
                    ],
                },
            ],
        },
    ],
)
def test_malformed_studio_documents_are_non_fatal(
    tmp_path: Path,
    document: object,
) -> None:
    source = tmp_path / "studio.json"
    source.write_text(json.dumps(document), encoding="utf-8")

    result = StudioConnectionLibrary(source).connections_for("bad")

    assert not result.features
    assert result.diagnostics
    assert all(
        diagnostic.code is DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE
        for diagnostic in result.diagnostics
    )


def test_unreadable_studio_json_is_non_fatal(tmp_path: Path) -> None:
    missing = StudioConnectionLibrary(tmp_path / "missing.json").connections_for("x")
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    malformed = StudioConnectionLibrary(malformed_path).connections_for("x")

    assert missing.diagnostics
    assert malformed.diagnostics
    assert not missing.features
    assert not malformed.features


def _generic_feature(
    *,
    role: ConnectionRole,
    group: str | None,
    match: GenericMatch,
    dimensions: tuple[float, ...],
) -> ConnectionFeature:
    return ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=role,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=GenericProfile(
            "generic",
            bounds=GenericBounds(GenericBoundsKind.SPHERE, dimensions),
            match=match,
        ),
        group=group,
    )


def test_generic_match_modes_and_gender_restrictions() -> None:
    male = _generic_feature(
        role=ConnectionRole.MALE,
        group=None,
        match=GenericMatch.SIZE,
        dimensions=(8,),
    )
    female = replace(male, role=ConnectionRole.FEMALE)
    wrong_size = replace(
        female,
        profile=replace(
            female.profile, bounds=GenericBounds(GenericBoundsKind.SPHERE, (9,))
        ),
    )
    grouped_male = replace(
        male, group="joint", profile=replace(male.profile, match=GenericMatch.GROUP)
    )
    grouped_female = replace(female, group="joint")
    ungrouped = replace(male, profile=replace(male.profile, match=GenericMatch.GROUP))

    assert connections_compatible(male, female)
    assert not connections_compatible(male, male)
    assert not connections_compatible(male, wrong_size)
    assert connections_compatible(grouped_male, grouped_female)
    assert connections_compatible(
        ungrouped,
        replace(ungrouped, role=ConnectionRole.FEMALE),
    )
    assert not connections_compatible(
        grouped_male, replace(grouped_female, group="other")
    )


def test_shadow_result_combination_applies_ordered_clears_and_conflicts() -> None:
    first = parse_ldcad_commands(
        "combined",
        ("SNAP_CLP [id=first]", "SNAP_CLP [id=second]"),
    )
    clear_one = ShadowConnectionResult(
        clear_ids=("FIRST",),
        source_count=1,
        document_ids=("clear",),
    )
    cleared = first.combined(clear_one)
    assert [feature.metadata_id for feature in cleared.features] == ["second"]
    assert cleared.clear_ids == ("FIRST",)

    replacement = replace(
        cleared.features[0],
        position=Vector(1, 0, 0),
        connection_provenance=None,
        provenance=("replacement",),
    )
    conflicted = cleared.combined(
        ShadowConnectionResult(
            features=(replacement,),
            source_count=1,
            document_ids=("replacement",),
        ),
    )
    assert conflicted.features == (replacement,)
    assert conflicted.source_count == 3
    assert conflicted.diagnostics[-1].code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
    assert "replacement" in conflicted.diagnostics[-1].message

    empty = conflicted.combined(ShadowConnectionResult(clear_all=True))
    assert empty.clear_all
    assert not empty.clear_ids
    assert not empty.features


def test_shadow_library_rejects_missing_source_and_caches_reads(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LDCadShadowLibrary(tmp_path / "missing")

    root = tmp_path / "shadow"
    target = root / "p" / "48" / "connector.dat"
    target.parent.mkdir(parents=True)
    target.write_text("0 !LDCAD SNAP_CLP [id=clip]\n", encoding="utf-8")
    library = LDCadShadowLibrary(root)
    first = library.connections_for("48/connector")
    second = library.connections_for("p/48/connector.dat")
    assert first.features == second.features


def test_shadow_directory_decode_errors_and_inline_missing_reference_recover(
    tmp_path: Path,
) -> None:
    root = tmp_path / "shadow"
    target = root / "parts" / "bad.dat"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff")
    unreadable = LDCadShadowLibrary(root).connections_for("bad")
    missing = parse_ldcad_commands(
        "owner",
        ("SNAP_INCL [ref=absent.dat]",),
        connection_shadows=(root,),
    )

    assert unreadable.invalid_record_count == 1
    assert (
        unreadable.diagnostics[0].code is DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE
    )
    assert missing.invalid_record_count == 1
    assert missing.diagnostics[0].code is DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND


@pytest.mark.parametrize(
    "record",
    [
        "SNAP_CYL [[secs=R 6 4]]",
        "SNAP_CYL [secs=R 6]",
        "SNAP_CYL [secs=R 6 4] [ori=1 0 0]",
        "SNAP_CYL [secs=R 6 4] [grid=1 1 C 20 30]",
        "SNAP_CLP [gender=M]",
    ],
)
def test_additional_malformed_option_forms_recover(record: str) -> None:
    result = parse_ldcad_commands("bad", (record,))

    assert result.invalid_record_count == 1
    assert not result.features


@pytest.mark.parametrize(
    "include",
    [
        "SNAP_INCL [ref=child.dat] [scale=0 1 1]",
        "SNAP_INCL [ref=child.dat] [scale=2 1 3]",
        "SNAP_INCL [ref=child.dat] [scale=-1 1 1]",
    ],
)
def test_invalid_include_scales_and_reflections_recover(
    tmp_path: Path,
    include: str,
) -> None:
    root = tmp_path / "shadow"
    target = root / "parts" / "child.dat"
    target.parent.mkdir(parents=True)
    target.write_text("0 !LDCAD SNAP_CLP [id=clip]\n", encoding="utf-8")

    result = parse_ldcad_commands(
        "owner",
        (include, "SNAP_CLP [id=recovered]"),
        connection_shadows=(root,),
    )

    assert result.invalid_record_count == 1
    assert [feature.feature_id for feature in result.features] == ["recovered"]
    assert result.diagnostics[0].code is DiagnosticCode.CONNECTION_INVALID_TRANSFORM


def test_include_vector_scale_is_applied_to_flattened_features(tmp_path: Path) -> None:
    root = tmp_path / "shadow"
    target = root / "parts" / "child.dat"
    target.parent.mkdir(parents=True)
    target.write_text("0 !LDCAD SNAP_CLP [id=clip]\n", encoding="utf-8")

    result = parse_ldcad_commands(
        "owner",
        ("SNAP_INCL [ref=child.dat] [scale=2 3 2]",),
        connection_shadows=(root,),
    )

    assert result.invalid_record_count == 0
    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.confidence > 0
    assert isinstance(feature.profile, CylindricalProfile)
    assert feature.profile.mating_radius == 8
    assert feature.profile.length == 24


def _cylindrical_feature(
    kind: ConnectionKind,
    role: ConnectionRole,
    *,
    shape: SectionShape = SectionShape.ROUND,
    radius: float = 4,
) -> ConnectionFeature:
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=CylindricalProfile(
            (CylindricalSection(shape, radius, 8),),
        ),
    )


def test_profile_scaling_properties_cover_every_profile_shape() -> None:
    square = CylindricalProfile(
        (CylindricalSection(SectionShape.SQUARE, 3, 4),),
    )
    flexible = CylindricalProfile(
        (CylindricalSection(SectionShape.ROUND, 2, 1, flexible=True),),
    )
    fingers = FingerProfile((2, 4, 2), 6)
    annular = AnnularProfile(10, 4, offset=1)
    point = GenericBounds(GenericBoundsKind.POINT)
    box = GenericBounds(GenericBoundsKind.BOX, (2, 3, 4))
    cylinder = GenericBounds(GenericBoundsKind.CYLINDER, (2, 5))
    sphere = GenericBounds(GenericBoundsKind.SPHERE, (2,))

    assert square.primary_shape is SectionShape.SQUARE
    assert flexible.mating_radius == 2
    assert fingers.length == 8
    assert fingers.scaled(radial=2, axial=3) == FingerProfile((6, 12, 6), 12)
    assert annular.length == 4
    assert annular.scaled(radial=2, axial=-3) == AnnularProfile(20, 12, offset=-3)
    assert point.scaled(radial=2, axial=3) == point
    assert box.scaled(radial=2, axial=3).dimensions == (4, 9, 8)
    assert cylinder.scaled(radial=2, axial=3).dimensions == (4, 15)
    assert sphere.scaled(radial=2, axial=3).dimensions == (4,)
    assert GenericProfile("none", length=2).scaled(radial=2, axial=3) == GenericProfile(
        "none",
        length=6,
    )


def test_feature_transform_handles_degenerate_and_non_metadata_shear() -> None:
    feature = _cylindrical_feature(ConnectionKind.BAR, ConnectionRole.MALE)
    degenerate = feature.transformed(
        position=Vector(1, 2, 3),
        matrix=Identity().scale(0, 1, 1),
    )
    sheared = feature.transformed(
        position=Vector(0, 0, 0),
        matrix=Matrix([[1, 0.25, 0], [0, 1, 0], [0, 0, 1]]),
    )
    zero_frame = replace(feature, frame=Matrix([[0, 0, 0]] * 3))

    assert degenerate.confidence == 0
    assert degenerate.position == Vector(1, 2, 3)
    assert sheared.confidence == pytest.approx(0.5)
    assert zero_frame.axis == zero_frame.radial == Vector(0, 0, 0)


def test_complete_compatibility_rules_cover_restrictions_and_profiles() -> None:
    bar = _cylindrical_feature(ConnectionKind.BAR, ConnectionRole.MALE)
    clip = _cylindrical_feature(ConnectionKind.CLIP, ConnectionRole.FEMALE)
    wrong_radius = _cylindrical_feature(
        ConnectionKind.CLIP,
        ConnectionRole.FEMALE,
        radius=6,
    )
    rim = replace(
        bar,
        kind=ConnectionKind.RIM_SEAT,
        profile=AnnularProfile(10, 4),
        owner_code="rim",
    )
    tyre = replace(
        clip,
        kind=ConnectionKind.TYRE_BEAD,
        profile=AnnularProfile(10, 4),
        owner_code="tyre",
    )

    with pytest.raises(ValueError):
        connections_compatible(bar, clip, radius_tolerance=-1)
    assert not connections_compatible(replace(bar, occupied=True), clip)
    assert not connections_compatible(bar, replace(clip, confidence=0))
    assert not connections_compatible(bar, wrong_radius)
    assert not connections_compatible(bar, replace(clip, kind=ConnectionKind.HINGE))
    assert not connections_compatible(
        replace(bar, compatible_parts=("other",), owner_code="bar"),
        replace(clip, owner_code="clip"),
    )
    assert connections_compatible(rim, tyre)
    assert not connections_compatible(
        rim,
        replace(tyre, profile=AnnularProfile(12, 4)),
    )
    assert connections_compatible(
        replace(rim, compatible_parts=("tyre",)),
        replace(tyre, profile=AnnularProfile(12, 4)),
    )
    assert not connections_compatible(
        replace(bar, profile=FingerProfile((8,), 4)),
        clip,
    )


def test_generic_shape_and_missing_bounds_matching() -> None:
    male = _generic_feature(
        role=ConnectionRole.MALE,
        group=None,
        match=GenericMatch.SHAPE,
        dimensions=(8,),
    )
    female = replace(male, role=ConnectionRole.FEMALE)
    different_size = replace(
        female,
        profile=replace(
            female.profile,
            bounds=GenericBounds(GenericBoundsKind.SPHERE, (20,)),
        ),
    )
    different_shape = replace(
        female,
        profile=replace(
            female.profile,
            bounds=GenericBounds(GenericBoundsKind.BOX, (8, 8, 8)),
        ),
    )
    no_bounds = replace(male, profile=replace(male.profile, bounds=None))

    assert connections_compatible(male, different_size)
    assert not connections_compatible(male, different_shape)
    assert not connections_compatible(
        no_bounds, replace(no_bounds, role=ConnectionRole.FEMALE)
    )
    assert not connections_compatible(
        replace(
            male,
            profile=CylindricalProfile((CylindricalSection(SectionShape.ROUND, 8, 8),)),
        ),
        female,
    )


def test_hinge_sequences_detents_and_free_rotation_residuals() -> None:
    left = ConnectionFeature(
        kind=ConnectionKind.HINGE,
        role=ConnectionRole.NEUTRAL,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=FingerProfile(
            (4.5, 8, 4.5),
            6,
            first_role=ConnectionRole.MALE,
            detents=(0, 90),
        ),
        group="click_hinge",
    )
    right = replace(
        left,
        frame=Identity().rotate(30, YAxis),
        profile=replace(left.profile, first_role=ConnectionRole.FEMALE),
    )
    free = _generic_feature(
        role=ConnectionRole.MALE,
        group=None,
        match=GenericMatch.SIZE,
        dimensions=(8,),
    )
    free = replace(
        free,
        profile=replace(free.profile, placement=GenericPlacement.FREE),
    )

    assert connections_compatible(left, right)
    assert not connections_compatible(
        left,
        replace(right, profile=replace(right.profile, sequence=(4, 8, 4))),
    )
    assert not connections_compatible(
        left,
        replace(right, profile=replace(right.profile, first_role=ConnectionRole.MALE)),
    )
    residual = connection_residual(left, right)
    assert residual.roll_alignment == pytest.approx(3**0.5 / 2)
    assert (
        connection_residual(free, replace(free, role=ConnectionRole.FEMALE)).alignment
        == 1
    )
    with pytest.raises(ValueError):
        angular_alignment_within(1, -1)


def test_frame_for_axis_recovers_from_parallel_radial_hint() -> None:
    frame = frame_for_axis(Vector(0, 1, 0), radial=Vector(0, 1, 0))

    assert frame.is_orthonormal()
    assert frame * Vector(0, 1, 0) == Vector(0, 1, 0)
