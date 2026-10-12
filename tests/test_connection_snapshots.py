"""Pinned real-library connection regression corpus."""

import json
from pathlib import Path

import pytest

from ldraw.config import Config
from ldraw.parts import Parts
from scripts.connection_snapshots import MANIFEST, SNAPSHOT, snapshot


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
    receipt = root / "_archive_sha256.txt"
    assert receipt.is_file(), "Redownload 2018-02 to record its archive checksum"
    assert receipt.read_text().strip() == manifest["archive_sha256"], (
        "Pinned 2018-02 archive checksum mismatch; inspect the release before "
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
