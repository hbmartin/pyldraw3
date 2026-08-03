"""Regression tests for the PR #51 connectivity review fixes."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ldraw.connection_metadata import (
    ConnectionMetadataCoverage,
    LDCadShadowLibrary,
    metadata_report,
    parse_ldcad_commands,
    parse_ldcad_text,
)
from ldraw.connection_studio import StudioConnectionLibrary
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    CylindricalProfile,
    CylindricalSection,
    SectionShape,
    snap_transform,
)
from ldraw.diagnostics import DiagnosticCode
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.inspection import _paired_contacts, inspect_model
from ldraw.model import parse_model
from ldraw.parts import Parts

_IDENTITY = "1 0 0 0 1 0 0 0 1"
_FLIP_Y = "1 0 0 0 -1 0 0 0 -1"


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _non_centered_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "parts/nchole.dat": (
                "0 Deep Socket Fixture\n"
                "0 !LDCAD SNAP_CLEAR\n"
                "0 !LDCAD SNAP_CYL [gender=F] [secs=R 6 60] [id=hole]\n"
                "2 24 -6 -60 -6 6 0 6\n"
            ),
            "parts/ncpin.dat": (
                "0 Long Connector Fixture\n"
                "0 !LDCAD SNAP_CLEAR\n"
                "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 60] [id=pin]\n"
                "2 24 -6 -60 -6 6 0 6\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "nchole.dat Deep Socket Fixture\nncpin.dat Long Connector Fixture\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text("", encoding="utf-8")
    return Parts(root / "parts.lst")


def _stud_shadow_parts(tmp_path: Path) -> Parts:
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "p/stud.dat": "0 Stud\n2 24 -6 -4 -6 6 0 6\n",
            "p/stud4.dat": "0 Stud Tube Open\n2 24 -6 0 -6 6 4 6\n",
            "parts/oneplate.dat": (
                "0 Single Stud Plate\n"
                "2 24 -10 0 -10 10 4 10\n"
                f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
            ),
            "parts/socket.dat": (
                "0 Single Receptacle Plate\n"
                "2 24 -10 0 -10 10 4 10\n"
                f"1 16 0 0 0 {_FLIP_Y} stud4.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "oneplate.dat Single Stud Plate\nsocket.dat Single Receptacle Plate\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text(
        "stud.dat Stud\nstud4.dat Stud Tube Open\n",
        encoding="utf-8",
    )
    return Parts(root / "parts.lst")


def test_broad_phase_pairs_non_centered_features(tmp_path: Path) -> None:
    """A far-apart non-centered pin/hole pair must survive the broad phase."""
    parts = _non_centered_parts(tmp_path)
    hole = next(iter(parts.connections("nchole")))
    assert hole.centered is False
    assert hole.length == pytest.approx(60)

    inspection = inspect_model(
        parse_model(
            "0 Non-centered insertion fixture\n"
            f"1 16 0 0 0 {_IDENTITY} nchole.dat\n"
            f"1 16 0 -80 0 {_FLIP_Y} ncpin.dat\n",
        ),
        parts,
    )
    exhaustive = tuple(
        contact
        for index, first in enumerate(inspection.occurrences)
        for second in inspection.occurrences[index + 1 :]
        for contact in _paired_contacts(
            first,
            second,
            tolerance=0.25,
            angular_tolerance=2.0,
        )
    )
    contacts = inspection.connection_contacts()
    assert len(exhaustive) == 1
    assert len(contacts) == 1
    assert contacts[0].residual.distance == pytest.approx(0)


def test_primitive_shadow_metadata_supersedes_inferred_stud(tmp_path: Path) -> None:
    """offLibShadow-style stud metadata must not double-count features."""
    parts = _stud_shadow_parts(tmp_path)
    shadow = tmp_path / "shadow"
    _write_tree(
        shadow,
        {"p/stud.dat": "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [id=studsnap]\n"},
    )
    parts.add_connection_shadow(shadow)

    studs = [
        feature
        for feature in parts.connections("oneplate")
        if feature.kind is ConnectionKind.STUD
    ]
    assert len(studs) == 1
    assert studs[0].source is ConnectionSource.LDCAD_SHADOW

    inspection = inspect_model(
        parse_model(
            "0 stacked\n"
            f"1 16 0 0 0 {_IDENTITY} oneplate.dat\n"
            f"1 16 0 -4 0 {_IDENTITY} socket.dat\n",
        ),
        parts,
    )
    assert len(inspection.stud_contacts()) == 1
    assert len(inspection.connection_graphs().confirmed.edges) == 1


def test_stud_contacts_pair_with_nearest_receptacle(tmp_path: Path) -> None:
    """The reported receptacle is the closest compatible one, not the first."""
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "p/stud.dat": "0 Stud\n2 24 -6 -4 -6 6 0 6\n",
            "p/stud4.dat": "0 Stud Tube Open\n2 24 -6 0 -6 6 4 6\n",
            "parts/oneplate.dat": (
                "0 Single Stud Plate\n"
                "2 24 -10 0 -10 10 4 10\n"
                f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
            ),
            "parts/twosockets.dat": (
                "0 Twin Receptacle Plate\n"
                "2 24 -10 0 -50 10 4 50\n"
                f"1 16 0 0 0 {_FLIP_Y} stud4.dat\n"
                f"1 16 0 0 40 {_FLIP_Y} stud4.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "oneplate.dat Single Stud Plate\ntwosockets.dat Twin Receptacle Plate\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text(
        "stud.dat Stud\nstud4.dat Stud Tube Open\n",
        encoding="utf-8",
    )
    parts = Parts(root / "parts.lst")

    inspection = inspect_model(
        parse_model(
            "0 offset stack\n"
            f"1 16 0 0 40 {_IDENTITY} oneplate.dat\n"
            f"1 16 0 -4 0 {_IDENTITY} twosockets.dat\n",
        ),
        parts,
    )
    contacts = inspection.stud_contacts()
    assert len(contacts) == 1
    receptacle = contacts[0].receptacle_feature
    assert receptacle is not None
    assert receptacle.feature_id == "stud4@R1/stud4"
    assert receptacle.position.z == pytest.approx(40)
    assert contacts[0].residual is not None
    assert contacts[0].residual.distance == pytest.approx(0)


@pytest.mark.parametrize("offset", [2, 40])
def test_stud_contacts_reject_misaligned_sole_receptacle(
    tmp_path: Path,
    offset: int,
) -> None:
    """Entry-face overlap cannot substitute for stud centerline alignment."""
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "p/stud.dat": "0 Stud\n2 24 -6 -4 -6 6 0 6\n",
            "p/stud4.dat": "0 Stud Tube Open\n2 24 -6 0 -6 6 4 6\n",
            "parts/oneplate.dat": (
                "0 Single Stud Plate\n"
                "2 24 -10 0 -10 10 4 10\n"
                f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
            ),
            "parts/widesocket.dat": (
                "0 Wide Single Receptacle Plate\n"
                "2 24 -10 0 -50 10 4 50\n"
                f"1 16 0 0 {offset} {_FLIP_Y} stud4.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "oneplate.dat Single Stud Plate\nwidesocket.dat Wide Single Receptacle Plate\n",
        encoding="utf-8",
    )
    (root / "p.lst").write_text(
        "stud.dat Stud\nstud4.dat Stud Tube Open\n",
        encoding="utf-8",
    )
    inspection = inspect_model(
        parse_model(
            "0 misaligned stack\n"
            f"1 16 0 0 0 {_IDENTITY} oneplate.dat\n"
            f"1 16 0 -4 0 {_IDENTITY} widesocket.dat\n",
        ),
        Parts(root / "parts.lst"),
    )

    assert inspection.stud_contacts() == ()
    assert inspection.connection_graphs().confirmed.edges == ()


def test_snap_transform_mates_non_centered_profiles_axis_to_axis() -> None:
    """Non-centered profiles never flip; the mated axes stay parallel."""
    profile = CylindricalProfile(
        sections=(CylindricalSection(shape=SectionShape.ROUND, radius=6, length=60),),
        centered=False,
    )
    hole = ConnectionFeature(
        kind=ConnectionKind.PIN_HOLE,
        role=ConnectionRole.FEMALE,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=profile,
    )
    pin = ConnectionFeature(
        kind=ConnectionKind.PIN,
        role=ConnectionRole.MALE,
        position=Vector(37, 11, -5),
        frame=Matrix([[1, 0, 0], [0, -1, 0], [0, 0, -1]]),
        profile=profile,
    )
    transform = snap_transform(pin, hole)
    mated_axis = (transform.matrix * pin.frame) * Vector(0, 1, 0)
    assert mated_axis.dot(hole.axis) == pytest.approx(1)
    landed = transform.position + transform.matrix * pin.position
    assert abs(landed - hole.position) == pytest.approx(0)


def test_snap_incl_reference_cannot_escape_shadow_root(tmp_path: Path) -> None:
    library_root = tmp_path / "lib"
    _write_tree(
        library_root,
        {"parts/100.dat": "0 !LDCAD SNAP_INCL [ref=../../outside/secret]\n"},
    )
    _write_tree(
        tmp_path / "outside",
        {"secret.dat": "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4]\n"},
    )
    library = LDCadShadowLibrary(library_root)

    direct = library.connections_for("../../outside/secret")
    assert direct.features == ()
    assert direct.source_count == 0

    included = library.connections_for("100")
    assert included.features == ()
    assert [diagnostic.code for diagnostic in included.diagnostics] == [
        DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND
    ]


def test_parse_ldcad_commands_diagnoses_garbage_and_recovers_missing_prefix() -> None:
    garbage = parse_ldcad_commands("3001", ["this is not a snap command"])
    assert garbage.features == ()
    assert garbage.invalid_record_count == 1
    report = metadata_report("3001", features=(), result=garbage)
    assert report.coverage is ConnectionMetadataCoverage.PARTIAL

    recovered = parse_ldcad_commands(
        "3001",
        ["!LDCAD SNAP_CYL [gender=M] [secs=R 6 4]"],
    )
    assert recovered.invalid_record_count == 0
    assert recovered.recognized_record_count == 1
    assert len(recovered.features) == 1


def test_parse_ldcad_text_flags_malformed_snap_lines_only() -> None:
    result = parse_ldcad_text(
        "3001",
        "0 !LDCAD GROUP_DEF [name=snap group]\n0 !LDCAD SNAP CYL [gender=M]\n",
    )
    assert result.features == ()
    assert result.invalid_record_count == 1
    assert len(result.diagnostics) == 1
    assert "unrecognized LDCad metadata line" in result.diagnostics[0].message


def test_duplicate_snap_incl_ids_keep_both_instances(tmp_path: Path) -> None:
    library_root = tmp_path / "lib"
    _write_tree(
        library_root,
        {
            "parts/child.dat": "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4]\n",
            "parts/200.dat": (
                "0 !LDCAD SNAP_INCL [id=a] [ref=child]\n"
                "0 !LDCAD SNAP_INCL [id=a] [ref=child] [pos=0 0 40]\n"
            ),
        },
    )
    result = LDCadShadowLibrary(library_root).connections_for("200")
    assert [feature.feature_id for feature in result.features] == [
        "a:I0/snap_cyl@L1:I0",
        "a@L2:I0/snap_cyl@L1:I0",
    ]
    assert [feature.position.z for feature in result.features] == [0, 40]


def test_rejected_duplicate_id_keeps_survivor_feature_id() -> None:
    valid = "0 !LDCAD SNAP_CYL [id=x] [gender=M] [secs=R 6 4]\n"
    rejected_duplicate = valid + "0 !LDCAD SNAP_CYL [id=x] [gender=M] [secs=R 6]\n"

    assert [
        feature.feature_id for feature in parse_ldcad_text("t", valid).features
    ] == ["x"]
    with_rejected = parse_ldcad_text("t", rejected_duplicate)
    assert [feature.feature_id for feature in with_rejected.features] == ["x"]
    assert with_rejected.invalid_record_count == 1


def test_feature_replacement_is_case_insensitive() -> None:
    first = parse_ldcad_text(
        "t",
        "0 !LDCAD SNAP_CYL [id=Conn] [gender=M] [secs=R 6 4]\n",
    )
    second = parse_ldcad_text(
        "t",
        "0 !LDCAD SNAP_CYL [id=conn] [gender=M] [secs=R 6 4] [pos=0 0 40]\n",
    )
    merged = first.combined(second)
    assert [feature.feature_id for feature in merged.features] == ["conn"]
    assert merged.features[0].position.z == pytest.approx(40)
    assert any(
        diagnostic.code is DiagnosticCode.CONNECTION_FEATURE_CONFLICT
        for diagnostic in merged.diagnostics
    )


def test_zip_members_under_nested_prefixes_resolve(tmp_path: Path) -> None:
    archive_path = tmp_path / "shadow.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "custom/offLib/shadow/parts/zc.dat",
            "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4]\n",
        )
        archive.writestr(
            "setup/p/prim.dat",
            "0 !LDCAD SNAP_CYL [gender=F] [secs=R 6 4]\n",
        )
    library = LDCadShadowLibrary(archive_path)
    assert len(library.connections_for("zc").features) == 1
    assert len(library.connections_for("prim").features) == 1


def test_snap_incl_resolves_across_registered_libraries(tmp_path: Path) -> None:
    _write_tree(
        tmp_path / "a",
        {"parts/100.dat": "0 !LDCAD SNAP_INCL [ref=200]\n"},
    )
    _write_tree(
        tmp_path / "b",
        {"parts/200.dat": "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4]\n"},
    )
    first = LDCadShadowLibrary(tmp_path / "a")
    second = LDCadShadowLibrary(tmp_path / "b")

    merged = first.connections_for("100", siblings=(first, second))
    assert [feature.feature_id for feature in merged.features] == [
        "snap_incl@L1:I0/snap_cyl@L1:I0",
    ]
    assert merged.diagnostics == ()

    solo = first.connections_for("100")
    assert solo.features == ()
    assert [diagnostic.code for diagnostic in solo.diagnostics] == [
        DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND
    ]


def test_reflective_orientation_matrix_is_diagnosed() -> None:
    result = parse_ldcad_text(
        "t",
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [ori=1 0 0 0 1 0 0 0 -1]\n",
    )
    assert result.features == ()
    assert result.invalid_record_count == 1
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        DiagnosticCode.CONNECTION_INVALID_TRANSFORM
    ]


def test_studio_empty_connections_is_not_authoritative(tmp_path: Path) -> None:
    parts = _stud_shadow_parts(tmp_path)
    studio_path = tmp_path / "studio.json"
    studio_path.write_text(
        '{"parts": [{"part_id": "oneplate", "connections": []}]}',
        encoding="utf-8",
    )

    adapter = StudioConnectionLibrary(studio_path)
    assert adapter.connections_for("oneplate").source_count == 0

    parts.add_studio_metadata(studio_path)
    report = parts.connection_metadata("oneplate")
    assert report.coverage is ConnectionMetadataCoverage.PARTIAL
    studs = [
        feature for feature in report.features if feature.kind is ConnectionKind.STUD
    ]
    assert len(studs) == 1
    assert studs[0].source is ConnectionSource.PRIMITIVE


def test_studio_document_failures_are_single_source_diagnostics(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "deep.json"
    nested.write_text(
        '{"parts": [' + "[" * 200_000 + "]" * 200_000 + "]}",
        encoding="utf-8",
    )
    library = StudioConnectionLibrary(nested)
    result = library.connections_for("3001")
    assert result.source_count == 1
    assert result.invalid_record_count == 1
    assert len(result.document_ids) == 1
    assert result.document_ids == library.connections_for("9999").document_ids


@pytest.mark.parametrize("scalar", [True, "not-a-number"])
def test_studio_rejects_non_numeric_scalars(
    tmp_path: Path,
    scalar: object,
) -> None:
    """Booleans and unparseable strings both earn the labeled diagnostic."""
    source = tmp_path / "bad-radius.json"
    source.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": "3001",
                        "connections": [
                            {
                                "type": "stud",
                                "position": [0, 0, 0],
                                "axis": [0, -1, 0],
                                "radius": scalar,
                            },
                        ],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    result = StudioConnectionLibrary(source).connections_for("3001")

    assert result.recognized_record_count == 0
    assert result.invalid_record_count == 1
    assert "radius must be a finite number" in result.diagnostics[0].message


@pytest.mark.parametrize("digit_count", [4_000, 5_000])
def test_studio_oversized_numbers_are_recoverable_diagnostics(
    tmp_path: Path,
    digit_count: int,
) -> None:
    source = tmp_path / f"oversized-{digit_count}.json"
    source.write_text(
        '{"parts":[{"part_id":"3001","connections":['
        '{"type":"stud","position":[0,0,0],"axis":[0,-1,0],"radius":'
        f"{'9' * digit_count}"
        "}]}]}",
        encoding="utf-8",
    )

    result = StudioConnectionLibrary(source).connections_for("3001")

    assert result.recognized_record_count == 0
    assert result.invalid_record_count == 1
    assert len(result.diagnostics) == 1


def test_studio_document_failure_is_counted_once_for_assembly(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "parts/childa.dat": (
                "0 Child A\n"
                "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [id=a]\n"
                "2 24 -1 0 -1 1 1 1\n"
            ),
            "parts/childb.dat": (
                "0 Child B\n"
                "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [id=b]\n"
                "2 24 -1 0 -1 1 1 1\n"
            ),
            "parts/parent.dat": (
                "0 Parent Assembly\n"
                f"1 16 0 0 0 {_IDENTITY} childa.dat\n"
                f"1 16 20 0 0 {_IDENTITY} childb.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "childa.dat Child A\nchildb.dat Child B\nparent.dat Parent Assembly\n",
        encoding="utf-8",
    )
    studio = tmp_path / "broken-studio.json"
    studio.write_text('{"parts": [', encoding="utf-8")
    parts = Parts(root / "parts.lst")
    parts.add_studio_metadata(studio)

    geometry = parts.geometry("parent")
    report = geometry.connection_metadata
    assert report is not None
    assert report.source_count == 3
    assert report.recognized_record_count == 2
    assert report.invalid_record_count == 1
    assert len(report.diagnostics) == 1
    assert "Studio" in report.diagnostics[0].message
    assert geometry.diagnostics == report.diagnostics


def test_document_metadata_aggregation_is_cached_and_invalidated(
    tmp_path: Path,
) -> None:
    parts = _stud_shadow_parts(tmp_path)
    studio = tmp_path / "broken-studio.json"
    studio.write_text('{"parts": [', encoding="utf-8")
    parts.add_studio_metadata(studio)

    aggregate = parts._connection_document_results  # noqa: SLF001
    with patch.object(
        parts,
        "_connection_document_results",
        wraps=aggregate,
    ) as aggregate_mock:
        first = parts.geometry("oneplate")
        second = parts.geometry("ONEPLATE")

        assert first.connection_metadata == second.connection_metadata
        assert first.diagnostics == second.diagnostics
        assert aggregate_mock.call_count == 1

        parts.clear_studio_metadata()
        parts.geometry("oneplate")
        assert aggregate_mock.call_count == 2


def test_studio_valid_and_document_failure_contributions_share_one_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "parts/child.dat": "0 Child\n2 24 -1 0 -1 1 1 1\n",
            "parts/parent.dat": (
                f"0 Parent Assembly\n1 16 0 0 0 {_IDENTITY} child.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "child.dat Child\nparent.dat Parent Assembly\n",
        encoding="utf-8",
    )
    studio = tmp_path / "mixed-studio.json"
    studio.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": "child",
                        "connections": [
                            {
                                "id": "studio-stud",
                                "type": "stud",
                                "position": [0, 0, 0],
                                "axis": [0, -1, 0],
                                "gender": "male",
                            },
                        ],
                    },
                    {"connections": []},
                ],
            },
        ),
        encoding="utf-8",
    )
    parts = Parts(root / "parts.lst")
    parts.add_studio_metadata(studio)

    report = parts.connection_metadata("parent")
    assert report.source_count == 1
    assert report.recognized_record_count == 1
    assert report.invalid_record_count == 1
    assert len(report.diagnostics) == 1
    assert "part_id" in report.diagnostics[0].message


def test_studio_document_counts_distinct_part_rows_once_per_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ldraw"
    _write_tree(
        root,
        {
            "parts/childa.dat": "0 Child A\n2 24 -1 0 -1 1 1 1\n",
            "parts/childb.dat": "0 Child B\n2 24 -1 0 -1 1 1 1\n",
            "parts/parent.dat": (
                "0 Parent Assembly\n"
                f"1 16 0 0 0 {_IDENTITY} childa.dat\n"
                f"1 16 20 0 0 {_IDENTITY} childa.dat\n"
                f"1 16 40 0 0 {_IDENTITY} childb.dat\n"
            ),
        },
    )
    (root / "parts.lst").write_text(
        "childa.dat Child A\nchildb.dat Child B\nparent.dat Parent Assembly\n",
        encoding="utf-8",
    )
    studio = tmp_path / "two-parts.json"
    studio.write_text(
        json.dumps(
            {
                "parts": [
                    {
                        "part_id": code,
                        "connections": [
                            {
                                "id": f"{code}-stud",
                                "type": "stud",
                                "position": [0, 0, 0],
                                "axis": [0, -1, 0],
                                "gender": "male",
                            },
                        ],
                    }
                    for code in ("childa", "childb")
                ],
            },
        ),
        encoding="utf-8",
    )
    parts = Parts(root / "parts.lst")
    parts.add_studio_metadata(studio)

    report = parts.connection_metadata("parent")
    studio_features = [
        feature
        for feature in report.features
        if feature.source is ConnectionSource.STUDIO
    ]

    assert report.source_count == 1
    assert report.recognized_record_count == 2
    assert report.invalid_record_count == 0
    assert len(studio_features) == 3


def test_parts_get_memo_is_not_aliased_by_source_mutation(tmp_path: Path) -> None:
    parts = _stud_shadow_parts(tmp_path)
    parts_lst = parts.path
    studio_path = tmp_path / "studio.json"
    studio_path.write_text(
        '{"parts": [{"part_id": "oneplate", "connections": '
        '[{"id": "s", "type": "stud", "position": [0, 0, 0], '
        '"axis": [0, -1, 0], "gender": "male"}]}]}',
        encoding="utf-8",
    )

    memoized = Parts.get(parts_lst)
    memoized.add_studio_metadata(studio_path)
    fresh = Parts.get(parts_lst)
    assert fresh is not memoized
    assert not fresh._studio_connection_libraries  # noqa: SLF001

    keyed = Parts.get(parts_lst, studio_metadata=(studio_path,))
    stat_result = studio_path.stat()
    os.utime(studio_path, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1))
    rekeyed = Parts.get(parts_lst, studio_metadata=(studio_path,))
    assert rekeyed is not keyed


def test_nested_shadow_edits_use_explicit_parts_cache_invalidation(
    tmp_path: Path,
) -> None:
    parts = _stud_shadow_parts(tmp_path)
    shadow = tmp_path / "shadow"
    target = shadow / "p" / "stud.dat"
    _write_tree(
        shadow,
        {
            "p/stud.dat": ("0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [id=old]\n"),
        },
    )
    Parts.clear_cache()

    first = Parts.get(parts.path, connection_shadows=(shadow,))
    assert {feature.metadata_id for feature in first.connections("oneplate")} == {"old"}

    root_stat = shadow.stat()
    target_stat = target.stat()
    target.write_text(
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4] [id=new]\n",
        encoding="utf-8",
    )
    os.utime(
        target,
        ns=(target_stat.st_atime_ns, target_stat.st_mtime_ns + 1),
    )
    os.utime(
        shadow,
        ns=(root_stat.st_atime_ns, root_stat.st_mtime_ns),
    )

    with patch(
        "ldraw.parts.Path.rglob",
        side_effect=AssertionError("memo lookup walked the source tree"),
    ):
        cached = Parts.get(parts.path, connection_shadows=(shadow,))
    assert cached is first
    assert {feature.metadata_id for feature in cached.connections("oneplate")} == {
        "old"
    }

    second = Parts.fresh(parts.path, connection_shadows=(shadow,))
    assert second is not first
    assert {feature.metadata_id for feature in second.connections("oneplate")} == {
        "new"
    }


def test_explicit_provenance_survives_replace() -> None:
    result = parse_ldcad_text(
        "t",
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 4]\n",
    )
    feature = result.features[0]
    assert feature.provenance != ()
    merged = replace(feature, provenance=("left", "right"))
    assert merged.provenance == ("left", "right")
