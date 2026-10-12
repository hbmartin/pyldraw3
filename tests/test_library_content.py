"""Portable corpus identity tracks source bytes rather than archive metadata."""

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from ldraw._library_content import library_content_sha256

SOURCES = {
    "parts/3001.dat": b"0 Brick\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n",
    "p/stud.dat": b"0 Stud\n2 24 0 0 0 1 1 1\n",
    "ldconfig.ldr": b"0 !COLOUR Red CODE 4 VALUE #FF0000 EDGE #000000\n",
}


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "ldraw"
    for relative, content in SOURCES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def test_content_identity_ignores_timestamps_and_generated_files(library: Path) -> None:
    original = library_content_sha256(library)
    for relative in SOURCES:
        os.utime(library / relative, times=(1_000_000_000, 1_000_000_000))
    for name in ("parts.lst", "_archive_sha256.txt", "_release.txt", "catalog.sqlite"):
        (library / name).write_text("generated data", encoding="utf-8")
    (library / "parts" / "notes.txt").write_text("unrelated data", encoding="utf-8")
    assert library_content_sha256(library) == original


@pytest.mark.parametrize("relative", SOURCES)
def test_content_identity_detects_source_edits(library: Path, relative: str) -> None:
    original = library_content_sha256(library)
    path = library / relative
    path.write_bytes(path.read_bytes() + b"0 Changed\n")
    assert library_content_sha256(library) != original


def test_content_identity_detects_path_changes(library: Path) -> None:
    original = library_content_sha256(library)
    source = library / "parts" / "3001.dat"
    source.rename(source.with_name("3002.dat"))
    assert library_content_sha256(library) != original


def test_content_identity_detects_added_and_removed_sources(library: Path) -> None:
    original = library_content_sha256(library)
    extra = library / "p" / "extra.dat"
    extra.write_bytes(b"0 Extra\n")
    assert library_content_sha256(library) != original
    extra.unlink()
    assert library_content_sha256(library) == original
    (library / "p" / "stud.dat").unlink()
    assert library_content_sha256(library) != original


def test_content_identity_is_independent_of_zip_encoding_and_wrapper(
    tmp_path: Path,
) -> None:
    digests: list[str] = []
    archives: list[bytes] = []
    for index, compression in enumerate((ZIP_STORED, ZIP_DEFLATED)):
        archive_path = tmp_path / f"{index}.zip"
        wrapper = f"wrapper-{index}"
        with ZipFile(archive_path, mode="w") as archive:
            for relative in sorted(SOURCES, reverse=bool(index)):
                member = ZipInfo(
                    filename=f"{wrapper}/ldraw/{relative}",
                    date_time=(2000 + index, 1, 1, 0, 0, 0),
                )
                archive.writestr(member, SOURCES[relative], compress_type=compression)
        archives.append(archive_path.read_bytes())
        destination = tmp_path / f"extracted-{index}"
        with ZipFile(archive_path) as archive:
            for member_name in archive.namelist():
                path = destination / member_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member_name))
        digests.append(library_content_sha256(destination / wrapper / "ldraw"))
    assert archives[0] != archives[1]
    assert digests[0] == digests[1]
