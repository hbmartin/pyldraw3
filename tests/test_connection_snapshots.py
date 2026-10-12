"""Pinned real-library connection regression corpus."""

import json
from pathlib import Path

import pytest

from ldraw._library_content import library_content_sha256
from ldraw.config import Config
from ldraw.parts import Parts
from scripts import connection_snapshots
from scripts.connection_snapshots import (
    MANIFEST,
    SEEDS,
    SNAPSHOT,
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


@pytest.mark.parametrize("archive_provenance", [False, True])
def test_regeneration_verifies_content_without_requiring_archive_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, archive_provenance: bool
) -> None:
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
    monkeypatch.setattr(connection_snapshots, "MANIFEST", manifest_path)
    monkeypatch.setattr(connection_snapshots, "SNAPSHOT", output_path)
    monkeypatch.setattr(connection_snapshots, "CORPUS", tmp_path)
    monkeypatch.setattr(connection_snapshots, "snapshot", lambda parts, codes: {})
    arguments = ["connection_snapshots", "--parts-list", str(listing)]
    if archive_provenance:
        archive = tmp_path / "archive.zip"
        archive.write_bytes(b"different archive encoding")
        arguments.extend(("--archive", str(archive)))
    monkeypatch.setattr("sys.argv", arguments)
    connection_snapshots.main()
    regenerated = json.loads(manifest_path.read_text())
    assert regenerated["library_content_sha256"] == manifest["library_content_sha256"]
    assert regenerated["part_codes"] == manifest["part_codes"]
    if archive_provenance:
        assert regenerated["archive_sha256"] != manifest["archive_sha256"]
    source.write_text("0 Changed brick\n", encoding="utf-8")
    with pytest.raises(ValueError, match="library content differs"):
        connection_snapshots.main()


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
