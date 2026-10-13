"""Pinned real-library connection regression corpus."""

import json
from dataclasses import replace
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pytest

from ldraw._library_content import library_content_sha256
from ldraw.config import Config
from ldraw.connection_types import ConnectionProvenance, ConnectionSource
from ldraw.parts import Parts
from scripts import connection_snapshots
from scripts.connection_snapshots import (
    MANIFEST,
    SEEDS,
    SNAPSHOT,
    normalized,
    select_codes,
    snapshot,
)


@pytest.mark.parametrize("count", [199, 200, 201])
def test_select_codes_handles_exact_capacity(tmp_path: Path, count: int) -> None:
    root = tmp_path / "ldraw"
    parts_dir = root / "parts"
    parts_dir.mkdir(parents=True)
    codes = [
        *SEEDS,
        *(str(code) for code in range(10_000, 10_000 + count - len(SEEDS))),
    ]
    for code in codes:
        (parts_dir / f"{code}.dat").write_text("0 Brick Test\n", encoding="utf-8")
    listing = root / "parts.lst"
    listing.write_text(
        "".join(f"{code}.dat  Brick Test\n" for code in reversed(codes)),
        encoding="utf-8",
    )
    parts = Parts(listing)
    if count < 200:
        with pytest.raises(ValueError, match="200 eligible parts"):
            select_codes(parts)
    else:
        selected = select_codes(parts)
        assert len(selected) == len(set(selected)) == 200
        assert selected[: len(SEEDS)] == list(SEEDS)
        assert selected == select_codes(parts)


@pytest.fixture
def regeneration_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Provide isolated corpus inputs and existing output files."""
    root = tmp_path / "ldraw"
    (root / "parts").mkdir(parents=True)
    source = root / "parts" / "3001.dat"
    source.write_text("0 Brick\n", encoding="utf-8")
    listing = root / "parts.lst"
    listing.write_text("3001.dat  Brick\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": 2,
        "release": "2018-02",
        "archive_sha256": "historical provenance",
        "library_content_sha256": library_content_sha256(root),
        "part_codes": ["3001"],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output_path = tmp_path / "snapshot.json"
    output_path.write_text('{"historical": true}\n', encoding="utf-8")
    monkeypatch.setattr(connection_snapshots, "MANIFEST", manifest_path)
    monkeypatch.setattr(connection_snapshots, "SNAPSHOT", output_path)
    monkeypatch.setattr(connection_snapshots, "CORPUS", tmp_path)
    monkeypatch.setattr(connection_snapshots, "snapshot", lambda parts, codes: {})
    monkeypatch.setattr(
        "sys.argv", ["connection_snapshots", "--parts-list", str(listing)]
    )
    return root, manifest_path, output_path


@pytest.mark.parametrize("archive_provenance", [False, True])
def test_regeneration_verifies_content_without_requiring_archive_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    regeneration_inputs: tuple[Path, Path, Path],
    *,
    archive_provenance: bool,
) -> None:
    root, manifest_path, output_path = regeneration_inputs
    source = root / "parts" / "3001.dat"
    listing = root / "parts.lst"
    manifest = json.loads(manifest_path.read_text())
    arguments = ["connection_snapshots", "--parts-list", str(listing)]
    if archive_provenance:
        archive = tmp_path / "archive.zip"
        with ZipFile(archive, mode="w") as zipped:
            zipped.write(filename=source, arcname="wrapper/LDRAW/PARTS/3001.DAT")
        arguments.extend(("--archive", str(archive)))
    monkeypatch.setattr("sys.argv", arguments)
    connection_snapshots.main()
    regenerated = json.loads(manifest_path.read_text())
    assert regenerated["library_content_sha256"] == manifest["library_content_sha256"]
    assert regenerated["part_codes"] == manifest["part_codes"]
    if archive_provenance:
        assert regenerated["archive_sha256"] != manifest["archive_sha256"]
        assert regenerated["archive_sha256"] == connection_snapshots.archive_checksum(
            archive
        )
    else:
        assert regenerated["archive_sha256"] == manifest["archive_sha256"]
    original_manifest = manifest_path.read_bytes()
    original_output = output_path.read_bytes()
    source.write_text("0 Changed brick\n", encoding="utf-8")
    with pytest.raises(ValueError, match="library content differs"):
        connection_snapshots.main()
    assert manifest_path.read_bytes() == original_manifest
    assert output_path.read_bytes() == original_output


@pytest.mark.parametrize("failure", ["mismatch", "malformed", "unrelated", "ambiguous"])
@pytest.mark.parametrize("select", [False, True])
def test_regeneration_rejects_unverified_provenance_without_writing_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    regeneration_inputs: tuple[Path, Path, Path],
    failure: str,
    *,
    select: bool,
) -> None:
    root, manifest_path, output_path = regeneration_inputs
    original_manifest = manifest_path.read_bytes()
    original_output = output_path.read_bytes()
    archive = tmp_path / "archive.zip"
    if failure == "malformed":
        archive.write_bytes(b"not a zip archive")
    else:
        with ZipFile(archive, mode="w") as zipped:
            match failure:
                case "mismatch":
                    zipped.writestr(
                        zinfo_or_arcname="ldraw/parts/3001.dat",
                        data="0 Changed brick\n",
                    )
                case "unrelated":
                    zipped.writestr(
                        zinfo_or_arcname="readme.txt", data="unrelated archive"
                    )
                case "ambiguous":
                    for prefix in ("first", "second"):
                        zipped.writestr(
                            zinfo_or_arcname=f"{prefix}/ldraw/parts/3001.dat",
                            data="0 Brick\n",
                        )
    arguments = [
        "connection_snapshots",
        "--parts-list",
        str(root / "parts.lst"),
        "--archive",
        str(archive),
    ]
    if select:
        arguments.append("--select")
        monkeypatch.setattr(
            connection_snapshots,
            "select_codes",
            lambda parts: pytest.fail("selection before verification"),
        )
    monkeypatch.setattr(
        connection_snapshots,
        "snapshot",
        lambda parts, codes: pytest.fail("snapshot before verification"),
    )
    monkeypatch.setattr(
        connection_snapshots,
        "archive_checksum",
        lambda archive: pytest.fail("raw checksum before content verification"),
    )
    monkeypatch.setattr("sys.argv", arguments)
    with pytest.raises((ValueError, BadZipFile)):
        connection_snapshots.main()
    assert manifest_path.read_bytes() == original_manifest
    assert output_path.read_bytes() == original_output


@pytest.mark.parametrize("verified_archive", [False, True])
def test_reselection_records_only_explicit_verified_archive_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    regeneration_inputs: tuple[Path, Path, Path],
    *,
    verified_archive: bool,
) -> None:
    root, manifest_path, _ = regeneration_inputs
    (root / "_archive_sha256.txt").write_text("unverified receipt\n", encoding="utf-8")
    arguments = [
        "connection_snapshots",
        "--parts-list",
        str(root / "parts.lst"),
        "--select",
    ]
    if verified_archive:
        archive = tmp_path / "archive.zip"
        with ZipFile(archive, mode="w") as zipped:
            zipped.write(
                filename=root / "parts" / "3001.dat", arcname="ldraw/parts/3001.dat"
            )
        arguments.extend(("--archive", str(archive)))
    monkeypatch.setattr(connection_snapshots, "select_codes", lambda parts: ["3001"])
    monkeypatch.setattr("sys.argv", arguments)
    connection_snapshots.main()
    regenerated = json.loads(manifest_path.read_text())
    assert regenerated["schema_version"] == 2
    assert regenerated["part_codes"] == ["3001"]
    if verified_archive:
        assert regenerated["archive_sha256"] == connection_snapshots.archive_checksum(
            archive
        )
    else:
        assert "archive_sha256" not in regenerated


def test_snapshot_paths_and_embedded_provenance_ignore_library_path_case(
    tmp_path: Path,
) -> None:
    command = "0 !LDCAD SNAP_CYL [id=PiN] [gender=M] [secs=R 6 4]"
    snapshots = []
    digests = []
    for uppercase in (False, True):
        root = tmp_path / str(uppercase)
        relative = "PARTS/3001.DAT" if uppercase else "parts/3001.dat"
        source = root / relative
        source.parent.mkdir(parents=True)
        source.write_text(f"0 Brick\n{command}\n")
        listing = root / "parts.lst"
        listing.write_text("3001.dat  Brick\n")
        parts = Parts(parts_lst=listing)
        digests.append(library_content_sha256(root))
        snapshots.append(snapshot(parts=parts, codes=["3001"]))
        feature = parts.connections("3001")[0]
        text = "MiXeD descriptive text"
        feature = replace(feature, provenance=(*feature.provenance, text))
        assert normalized(feature, library_root=root)["provenance"][-1] == text
    assert digests[0] == digests[1]
    assert snapshots[0] == snapshots[1]
    feature = snapshots[0]["3001"][0]
    assert feature["connection_provenance"]["path"] == "parts/3001.dat"
    assert feature["connection_provenance"]["command"] == command
    assert feature["provenance"] == ["<library>/parts/3001.dat:2"]


def test_snapshot_preserves_metadata_command_text(tmp_path: Path) -> None:
    path = tmp_path / "PARTS" / "Custom.DAT"
    command = f"0 !LDCAD SNAP_INCL [ref={path}]"
    provenance = ConnectionProvenance(
        source=ConnectionSource.LDCAD_INLINE, path=path, command=command
    )
    result = normalized(provenance, library_root=tmp_path)
    assert result["path"] == "parts/custom.dat"
    assert result["command"] == command


def test_snapshot_canonicalizes_symlinked_paths_and_source_prefixes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    source = root / "PARTS" / "3001.DAT"
    source.parent.mkdir(parents=True)
    source.write_text("0 Brick\n0 !LDCAD SNAP_CYL [id=PiN] [gender=M] [secs=R 6 4]\n")
    listing = root / "parts.lst"
    listing.write_text("3001.dat  Brick\n")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    feature = Parts(parts_lst=listing).connections("3001")[0]
    assert feature.connection_provenance is not None
    descriptive = f"{root}/MiXeD descriptive text"
    changed = replace(feature, provenance=(f"{alias}/PARTS/3001.DAT:2", descriptive))
    result = normalized(changed, library_root=alias)
    assert result["provenance"] == ["<library>/parts/3001.dat:2", descriptive]
    assert result["connection_provenance"]["path"] == "parts/3001.dat"
    alternate = replace(
        changed,
        connection_provenance=replace(
            feature.connection_provenance, path=alias / "PARTS" / "3001.DAT"
        ),
    )
    assert normalized(alternate, library_root=root) == result
    outside = replace(feature.connection_provenance, path=tmp_path / "outside.dat")
    with pytest.raises(ValueError):
        normalized(outside, library_root=root)


@pytest.mark.parametrize(
    "member", ["PARTS/3001.DAT", "parts/3001.dat", "PARTS\\3001.DAT"]
)
def test_snapshot_normalizes_archive_members_preserving_attribution(
    tmp_path: Path, member: str
) -> None:
    root = tmp_path / "library"
    source = root / "parts" / "3001.dat"
    source.parent.mkdir(parents=True)
    command = "0 !LDCAD SNAP_CYL [id=PiN] [gender=M] [secs=R 6 4]"
    source.write_text(f"0 Brick\n{command}\n")
    listing = root / "parts.lst"
    listing.write_text("3001.dat  Brick\n")
    feature = Parts(parts_lst=listing).connections("3001")[0]
    provenance = ConnectionProvenance(
        source=ConnectionSource.LDCAD_SHADOW,
        path=root / "SHADOW.ZIP",
        archive_member=member,
        line_number=2,
        command=command,
        include_chain=("MyID:I0", "parts/target"),
    )
    feature = replace(feature, connection_provenance=provenance, provenance=())
    result = normalized(feature, library_root=root)
    assert result["provenance"] == ["parts/3001.dat:2 via MyID:I0 > parts/target"]
    assert result["connection_provenance"]["path"] == "shadow.zip"
    assert result["connection_provenance"]["archive_member"] == "parts/3001.dat"
    assert result["connection_provenance"]["include_chain"] == [
        "MyID:I0",
        "parts/target",
    ]
    assert result["connection_provenance"]["command"] == command
    assert result["metadata_id"] == "PiN"
    unrelated = replace(feature, provenance=("MiXeD descriptive text",))
    assert normalized(unrelated, library_root=root)["provenance"] == [
        "MiXeD descriptive text"
    ]


def test_snapshot_canonicalizes_multiple_origins_and_preserves_attribution(
    tmp_path: Path,
) -> None:
    outputs = []
    for uppercase in (False, True):
        root = tmp_path / f"Library: Mixed Names {uppercase}"
        directory = root / ("PARTS" if uppercase else "parts")
        directory.mkdir(parents=True)
        source = directory / ("PRIMARY.DAT" if uppercase else "primary.dat")
        other = directory / ("OTHER.DAT" if uppercase else "other.dat")
        source.write_text(
            "0 Brick\n0 !LDCAD SNAP_CYL [id=PiN] [gender=M] [secs=R 6 4]\n"
        )
        other.write_text("0 Other\n")
        listing = root / "parts.lst"
        listing.write_text("primary.dat  Brick\n")
        alias = tmp_path / f"Alias: With Spaces {uppercase}"
        alias.symlink_to(root, target_is_directory=True)
        feature = Parts(parts_lst=listing).connections("primary")[0]
        member = "PARTS\\SHADOW.DAT" if uppercase else "parts/shadow.dat"
        secondary = alias / other.relative_to(root)
        metadata = alias / ("Metadata.JSON" if uppercase else "metadata.json")
        feature = replace(
            feature,
            provenance=(
                *feature.provenance,
                f"{secondary}:37 via MiXeD:I0 > parts/Target.DAT",
                f"{metadata}: Studio connection 4",
                f"{member}:12 via MyID:I0 > PARTS/Target",
                "MiXeD descriptive text",
            ),
        )
        result = normalized(feature, library_root=root)
        assert result["provenance"] == [
            "<library>/parts/primary.dat:2",
            "<library>/parts/other.dat:37 via MiXeD:I0 > parts/Target.DAT",
            "<library>/metadata.json: Studio connection 4",
            "parts/shadow.dat:12 via MyID:I0 > PARTS/Target",
            "MiXeD descriptive text",
        ]
        descriptive = f"{root}/MiXeD descriptive text"
        with_description = replace(
            feature, provenance=(*feature.provenance, descriptive)
        )
        assert (
            normalized(with_description, library_root=root)["provenance"][-1]
            == descriptive
        )
        outputs.append(result)
    assert outputs[0] == outputs[1]


def test_snapshot_secondary_sources_without_structured_origin_and_outside_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "library"
    (root / "parts").mkdir(parents=True)
    source = root / "parts" / "3001.dat"
    source.write_text("0 Brick\n0 !LDCAD SNAP_CYL [id=PiN] [gender=M] [secs=R 6 4]\n")
    listing = root / "parts.lst"
    listing.write_text("3001.dat  Brick\n")
    feature = Parts(parts_lst=listing).connections("3001")[0]
    secondary = replace(
        feature,
        connection_provenance=None,
        provenance=(
            f"{root}/PARTS/OTHER.DAT:3",
            "OtherID:I0",
            "parts/a.dat:4 via ID.dat",
        ),
    )
    assert normalized(secondary, library_root=root)["provenance"] == [
        "<library>/parts/other.dat:3",
        "OtherID:I0",
        "parts/a.dat:4 via ID.dat",
    ]
    outside = replace(secondary, provenance=(f"{tmp_path}/outside.dat:3",))
    with pytest.raises(ValueError):
        normalized(outside, library_root=root)


@pytest.mark.parametrize(
    "failure", ["missing", "malformed", "non-object", "schema", "content"]
)
def test_manifest_failures_precede_archive_reads_and_output_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    regeneration_inputs: tuple[Path, Path, Path],
    failure: str,
) -> None:
    root, manifest, output = regeneration_inputs
    match failure:
        case "missing":
            manifest.unlink()
        case "malformed":
            manifest.write_text("invalid json")
        case "non-object":
            manifest.write_text("[]")
        case "schema":
            data = json.loads(manifest.read_text())
            data["schema_version"] = 1
            manifest.write_text(json.dumps(data))
        case "content":
            (root / "parts" / "3001.dat").write_text("0 Changed\n")
    original_manifest = manifest.read_bytes() if manifest.exists() else None
    original_output = output.read_bytes()
    monkeypatch.setattr(
        "sys.argv",
        [
            "connection_snapshots",
            "--parts-list",
            str(root / "parts.lst"),
            "--archive",
            str(tmp_path / "absent.zip"),
        ],
    )
    monkeypatch.setattr(
        connection_snapshots,
        "archive_library_content_sha256",
        lambda path: pytest.fail("archive content read"),
    )
    monkeypatch.setattr(
        connection_snapshots,
        "archive_checksum",
        lambda path: pytest.fail("archive checksum read"),
    )
    monkeypatch.setattr(
        connection_snapshots,
        "snapshot",
        lambda parts, codes: pytest.fail("snapshot generated"),
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        connection_snapshots.main()
    assert (manifest.read_bytes() if manifest.exists() else None) == original_manifest
    assert output.read_bytes() == original_output


def assert_snapshot_equal(actual: object, expected: object, path: str = "root") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            assert_snapshot_equal(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), path
        assert len(actual) == len(expected), path
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            assert_snapshot_equal(left, right, f"{path}[{index}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-9, abs=1e-7), path
    else:
        assert actual == expected, path


@pytest.mark.integration
def test_pinned_connection_corpus(pytestconfig) -> None:
    if not pytestconfig.getoption("--connection-snapshots"):
        pytest.skip("pass --connection-snapshots with the pinned 2018-02 library")
    manifest = json.loads(MANIFEST.read_text())
    root = Path(Config.load().ldraw_library_path) / "ldraw"
    assert manifest["schema_version"] == 2
    assert library_content_sha256(root) == manifest["library_content_sha256"], (
        "Pinned 2018-02 library content mismatch; inspect the release before "
        "explicitly regenerating the corpus"
    )
    assert len(manifest["part_codes"]) == len(set(manifest["part_codes"])) == 200
    actual = snapshot(Parts(root / "parts.lst"), manifest["part_codes"])
    assert_snapshot_equal(actual, json.loads(SNAPSHOT.read_text()))


def test_snapshot_comparison_uses_tolerance_and_checks_structure() -> None:
    assert_snapshot_equal({"position": [1.0 + 1e-8]}, {"position": [1.0]})
    with pytest.raises(AssertionError):
        assert_snapshot_equal({"position": [1.1]}, {"position": [1.0]})
    with pytest.raises(AssertionError):
        assert_snapshot_equal([1.0, 2.0], [1.0])
    with pytest.raises(AssertionError):
        assert_snapshot_equal({"kind": "bar"}, {"kind": "stud"})
