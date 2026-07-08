"""Tests for download functionality."""

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ldraw import download
from ldraw.downloads import (
    ARCHIVE_URL,
    LDRAW_URL,
    _case_safe_rename,
    _download,
    _normalize_tree,
    _temporary_rename_path,
    unpack_version,
)


@patch("zipfile.ZipFile", spec=zipfile.ZipFile)
@patch("ldraw.downloads._download_progress")
@patch("ldraw.downloads.generate_parts_lst")
def test_download(
    generate_parts_lst_mock: MagicMock,
    download_progress_mock: MagicMock,
    zip_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    zip_mock.return_value.__enter__.return_value.infolist.return_value = []

    with patch(
        "ldraw.downloads.get_latest_release_id",
        return_value="2099-01",
    ) as get_latest_release_id_mock:
        download()

    download_progress_mock.assert_called_once()
    get_latest_release_id_mock.assert_called_once()
    generate_parts_lst_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_versioned_uses_archive_url(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
) -> None:
    download(show_progress=False, version="2018-02")

    assert download_mock.call_args.args[0] == f"{ARCHIVE_URL}/2018-02.zip"


@patch("ldraw.downloads.get_latest_release_id", return_value="2099-01")
@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_complete_uses_ldraw_url(
    download_mock: MagicMock,
    unpack_version_mock: MagicMock,
    generate_parts_lst_mock: MagicMock,
    get_latest_release_id_mock: MagicMock,
    tmp_path: Path,
) -> None:
    unpack_version_mock.return_value = tmp_path

    assert download(show_progress=False) == "2099-01"

    assert download_mock.call_args.args[0] == f"{LDRAW_URL}/complete.zip"
    assert (tmp_path / "ldraw" / "_release.txt").read_text() == "2099-01"


def test_download_rejects_invalid_version() -> None:
    with pytest.raises(ValueError, match="Unsupported LDraw library version"):
        download(show_progress=False, version="../bad")


def test_unpack_version_rejects_unsafe_zip_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(version_zip, "w") as zip_file:
        zip_file.writestr("../escape.dat", "bad")
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path / "cache")

    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        unpack_version(version_zip, "2018-02")

    assert not (tmp_path / "escape.dat").exists()


def test_unpack_version_rejects_invalid_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported LDraw library version"):
        unpack_version(tmp_path / "missing.zip", "../bad")


@patch("ldraw.downloads.requests.get")
def test_download_failure_leaves_no_cached_file(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.side_effect = requests.ConnectionError("dropped")

    with pytest.raises(requests.ConnectionError):
        _download("https://example.test/x.zip", "x.zip")

    assert not (tmp_path / "x.zip").exists()


@patch("ldraw.downloads.requests.get")
def test_download_success_replaces_partial_file(
    get_mock: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)
    response = get_mock.return_value.__enter__.return_value
    response.iter_content.return_value = [b"zip-bytes"]

    result = _download("https://example.test/x.zip", "x.zip")

    assert result == tmp_path / "x.zip"
    assert result.read_bytes() == b"zip-bytes"
    assert not (tmp_path / "x.zip.part").exists()


def test_temporary_rename_path_skips_existing(tmp_path: Path) -> None:
    target = tmp_path / "LDRAW"
    (tmp_path / "LDRAW__pyldraw_tmp__").mkdir()

    candidate = _temporary_rename_path(target)

    assert candidate.name == "LDRAW__pyldraw_tmp_1__"


def test_case_safe_rename_changes_directory_case(tmp_path: Path) -> None:
    source = tmp_path / "LDRAW"
    source.mkdir()
    (source / "marker.txt").write_text("marker")

    result = _case_safe_rename(source, tmp_path / "ldraw")

    assert [child.name for child in tmp_path.iterdir()] == ["ldraw"]
    assert (result / "marker.txt").read_text() == "marker"


def test_normalize_tree_github_snapshot(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw-parts-2018-02" / "LDRAW"
    (ldraw_dir / "PARTS" / "S").mkdir(parents=True)
    (ldraw_dir / "PARTS" / "973.DAT").write_text("0 Minifig Torso")
    (ldraw_dir / "PARTS" / "S" / "973S01.DAT").write_text("0 ~Minifig Torso subpart")
    (ldraw_dir / "P").mkdir()
    (ldraw_dir / "PARTS.LST").write_text("parts")
    (ldraw_dir / "ldconfig.ldr").write_text("colours")

    _normalize_tree(tmp_path)

    assert not (tmp_path / "ldraw-parts-2018-02").exists()
    names = sorted(child.name for child in (tmp_path / "ldraw").iterdir())
    assert names == ["ldconfig.ldr", "p", "parts", "parts.lst"]
    parts_names = sorted(
        child.name for child in (tmp_path / "ldraw" / "parts").iterdir()
    )
    assert parts_names == ["973.dat", "s"]
    subpart_names = [
        child.name for child in (tmp_path / "ldraw" / "parts" / "s").iterdir()
    ]
    assert subpart_names == ["973s01.dat"]


def test_normalize_tree_complete_layout(tmp_path: Path) -> None:
    (tmp_path / "ldraw" / "parts").mkdir(parents=True)
    (tmp_path / "ldraw" / "LDConfig.ldr").write_text("colours")

    _normalize_tree(tmp_path)

    names = sorted(child.name for child in (tmp_path / "ldraw").iterdir())
    assert names == ["ldconfig.ldr", "parts"]


def test_normalize_tree_missing_destination(tmp_path: Path) -> None:
    _normalize_tree(tmp_path / "nonexistent")

    assert not (tmp_path / "nonexistent").exists()
