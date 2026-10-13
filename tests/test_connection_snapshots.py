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
