"""Portable corpus identity tracks source bytes rather than archive metadata."""

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

import pytest

from ldraw._library_content import (
    archive_library_content_sha256,
    library_content_sha256,
)

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


@pytest.mark.parametrize("relative", SOURCES)
def test_uppercase_library_identity_matches_and_detects_edits(
    tmp_path: Path, library: Path, relative: str
) -> None:
    uppercase = tmp_path / "uppercase"
    for name, content in SOURCES.items():
        path = uppercase / name.upper()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    original = library_content_sha256(library)
    assert library_content_sha256(uppercase) == original
    changed = uppercase / relative.upper()
    changed.write_bytes(changed.read_bytes() + b"0 Changed\n")
    assert library_content_sha256(uppercase) != original


def test_directory_identity_rejects_case_colliding_sources(library: Path) -> None:
    source = library / "parts" / "3001.dat"
    collision = source.with_name("3001.DAT")
    if collision.exists():
        pytest.skip("case-insensitive filesystem cannot host colliding source names")
    collision.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="duplicate normalized library path"):
        library_content_sha256(library)


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
                archive.writestr(
                    zinfo_or_arcname=member,
                    data=SOURCES[relative],
                    compress_type=compression,
                )
        archives.append(archive_path.read_bytes())
        destination = tmp_path / f"extracted-{index}"
        with ZipFile(archive_path) as archive:
            for member_name in archive.namelist():
                path = destination / member_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(member_name))
        digests.append(library_content_sha256(destination / wrapper / "ldraw"))
        assert archive_library_content_sha256(archive_path) == digests[-1]
    assert archives[0] != archives[1]
    assert digests[0] == digests[1]


@pytest.mark.parametrize("prefix", ["", "ldraw/", "wrapper/LDRAW/"])
def test_archive_identity_normalizes_case_without_extraction(
    tmp_path: Path, library: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    archive_path = tmp_path / "library.zip"
    with ZipFile(archive_path, mode="w") as archive:
        for relative, content in SOURCES.items():
            archive.writestr(
                zinfo_or_arcname=f"{prefix}{relative.upper()}", data=content
            )
        archive.writestr(
            zinfo_or_arcname=f"{prefix}parts.lst", data="ignored generated listing"
        )
        archive.writestr(
            zinfo_or_arcname="readme.txt", data="ignored archive wrapper metadata"
        )

    def reject_extraction(*args: object, **kwargs: object) -> None:
        pytest.fail("content verification must not extract ZIP entries")

    monkeypatch.setattr(ZipFile, "extract", reject_extraction)
    monkeypatch.setattr(ZipFile, "extractall", reject_extraction)
    assert archive_library_content_sha256(archive_path) == library_content_sha256(
        library
    )


@pytest.mark.parametrize(
    "members",
    [
        ["readme.txt"],
        ["first/ldraw/parts/3001.dat", "second/ldraw/parts/3001.dat"],
        ["ldraw/parts/3001.dat", "ldraw/PARTS/3001.DAT"],
        ["ldraw/parts/3001.dat", "./ldraw/parts/3001.dat"],
        ["../ldraw/parts/3001.dat"],
        ["/ldraw/parts/3001.dat"],
        ["C:\\ldraw\\parts\\3001.dat"],
        ["ldraw\\..\\parts\\3001.dat"],
    ],
    ids=[
        "unrelated",
        "ambiguous",
        "case-collision",
        "normalized-collision",
        "unsafe",
        "absolute-posix",
        "absolute-windows",
        "windows-traversal",
    ],
)
def test_archive_identity_rejects_invalid_sources(
    tmp_path: Path, members: list[str]
) -> None:
    archive_path = tmp_path / "invalid.zip"
    with ZipFile(archive_path, mode="w") as archive:
        for member in members:
            archive.writestr(zinfo_or_arcname=member, data="0 Brick\n")
    with pytest.raises(ValueError):
        archive_library_content_sha256(archive_path)


def test_archive_identity_rejects_malformed_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "malformed.zip"
    archive_path.write_bytes(b"not a zip archive")
    with pytest.raises(BadZipFile):
        archive_library_content_sha256(archive_path)


def test_append_updated_archive_hashes_last_exact_filename(
    tmp_path: Path, library: Path
) -> None:
    archive_path = tmp_path / "updated.zip"
    filename = "ldraw/parts/3001.dat"
    with ZipFile(archive_path, mode="w") as archive:
        for relative, content in SOURCES.items():
            archive.writestr(
                zinfo_or_arcname=f"ldraw/{relative}",
                data=b"0 Old Brick\n" if relative == "parts/3001.dat" else content,
            )
    assert archive_library_content_sha256(archive_path) != library_content_sha256(
        library
    )
    with (
        ZipFile(archive_path, mode="a") as archive,
        pytest.warns(UserWarning, match="Duplicate name"),
    ):
        archive.writestr(zinfo_or_arcname=filename, data=SOURCES["parts/3001.dat"])
    extracted = tmp_path / "extracted"
    with ZipFile(archive_path) as archive:
        archive.extractall(path=extracted)
    assert (extracted / filename).read_bytes() == SOURCES["parts/3001.dat"]
    assert archive_library_content_sha256(archive_path) == library_content_sha256(
        library
    )
    assert library_content_sha256(extracted / "ldraw") == library_content_sha256(
        library
    )


def test_unsafe_exact_repeated_members_are_still_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    filename = "../ldraw/parts/3001.dat"
    with ZipFile(archive_path, mode="w") as archive:
        archive.writestr(zinfo_or_arcname=filename, data="0 First\n")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(zinfo_or_arcname=filename, data="0 Last\n")
    with pytest.raises(ValueError, match="unsafe ZIP member path"):
        archive_library_content_sha256(archive_path)
