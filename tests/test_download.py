"""Tests for download functionality."""

import zipfile
from pathlib import Path
from unittest.mock import patch

from ldraw import download
from ldraw.downloads import ARCHIVE_URL, LDRAW_URL, _normalize_tree


@patch("zipfile.ZipFile", spec=zipfile.ZipFile)
@patch("ldraw.downloads._download_progress")
@patch("ldraw.downloads.generate_parts_lst")
def test_download(
    generate_parts_lst_mock,
    download_progress_mock,
    zip_mock,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("ldraw.downloads.cache_ldraw", tmp_path)

    download()

    download_progress_mock.assert_called_once()
    generate_parts_lst_mock.assert_called_once()


@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_versioned_uses_archive_url(
    download_mock,
    unpack_version_mock,
    generate_parts_lst_mock,
) -> None:
    download(show_progress=False, version="2018-02")

    assert download_mock.call_args.args[0] == f"{ARCHIVE_URL}/2018-02.zip"


@patch("ldraw.downloads.get_latest_release_id", return_value="2099-01")
@patch("ldraw.downloads.generate_parts_lst")
@patch("ldraw.downloads.unpack_version")
@patch("ldraw.downloads._download")
def test_download_complete_uses_ldraw_url(
    download_mock,
    unpack_version_mock,
    generate_parts_lst_mock,
    get_latest_release_id_mock,
    tmp_path,
) -> None:
    unpack_version_mock.return_value = tmp_path

    assert download(show_progress=False) == "2099-01"

    assert download_mock.call_args.args[0] == f"{LDRAW_URL}/complete.zip"
    assert (tmp_path / "ldraw" / "_release.txt").read_text() == "2099-01"


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
