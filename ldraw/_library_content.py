"""Portable content identity for extracted LDraw geometry and colours."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast
from zipfile import ZipFile

from ldraw._zip_paths import is_unsafe_zip_member

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path
    from zipfile import ZipExtFile, ZipInfo


def _content_sha256(entries: Iterable[tuple[str, bytes]]) -> str:
    """Hash canonical relative paths and source digests for either storage form."""
    sources: dict[str, bytes] = {}
    for relative, file_digest in entries:
        canonical = relative.lower()
        if canonical in sources:
            message = f"duplicate normalized library path {canonical!r}"
            raise ValueError(message)
        sources[canonical] = file_digest
    digest = hashlib.sha256()
    for canonical, file_digest in sorted(sources.items()):
        relative = canonical.encode("utf-8")
        digest.update(len(relative).to_bytes(length=8, byteorder="big"))
        digest.update(relative)
        digest.update(file_digest)
    return digest.hexdigest()


def _directory_entries(library_root: Path) -> Iterator[tuple[str, bytes]]:
    for child in library_root.iterdir():
        match child.name.lower():
            case "parts" | "p" if child.is_dir():
                paths = (
                    path
                    for path in child.rglob("*")
                    if path.is_file() and path.suffix.lower() == ".dat"
                )
            case "ldconfig.ldr" if child.is_file():
                paths = iter((child,))
            case _:
                continue
        for path in paths:
            with path.open("rb") as source:
                file_digest = hashlib.file_digest(source, "sha256").digest()
            yield path.relative_to(library_root).as_posix(), file_digest


def library_content_sha256(library_root: Path) -> str:
    """Hash sorted relative paths and bytes, ignoring extraction metadata.

    Include drawable .dat sources under parts/ and p/, and the canonical
    root LDConfig.ldr. Paths use the downloader's lowercase normalization;
    duplicate normalized source paths are rejected. Generated catalogs,
    receipts, and archive wrappers are outside this content identity.
    """
    return _content_sha256(_directory_entries(library_root))


def _is_content_source(relative: PurePosixPath) -> bool:
    return (len(relative.parts) == 1 and relative.name == "ldconfig.ldr") or (
        len(relative.parts) > 1
        and relative.parts[0] in {"parts", "p"}
        and relative.suffix == ".dat"
    )


def _archive_members(archive: ZipFile) -> list[tuple[ZipInfo, PurePosixPath]]:
    members: dict[str, tuple[ZipInfo, PurePosixPath]] = {}
    for member in archive.infolist():
        if is_unsafe_zip_member(member.filename):
            message = f"unsafe ZIP member path {member.filename!r}"
            raise ValueError(message)
        if not member.is_dir():
            members[member.filename] = (member, PurePosixPath(member.filename.lower()))
    return list(members.values())


def _archive_library_root(paths: Iterable[PurePosixPath]) -> tuple[str, ...]:
    roots: set[tuple[str, ...]] = set()
    for path in paths:
        if _is_content_source(path):
            roots.add(())
        for index, name in enumerate(path.parts[:-1]):
            if name == "ldraw" and _is_content_source(
                PurePosixPath(*path.parts[index + 1 :]),
            ):
                roots.add(path.parts[: index + 1])
    if len(roots) != 1:
        message = "archive must contain exactly one LDraw library root"
        raise ValueError(message)
    return roots.pop()


def _archive_entries(archive: ZipFile) -> Iterator[tuple[str, bytes]]:
    members = _archive_members(archive)
    root = _archive_library_root(path for _, path in members)
    for member, path in members:
        if path.parts[: len(root)] != root:
            continue
        relative = PurePosixPath(*path.parts[len(root) :])
        if _is_content_source(relative):
            with cast("ZipExtFile", archive.open(member)) as source:
                digest = hashlib.file_digest(source, "sha256").digest()
            yield relative.as_posix(), digest


def archive_library_content_sha256(archive_path: Path) -> str:
    """Hash effective ZIP sources, using the last entry for exact name repeats."""
    with ZipFile(archive_path) as archive:
        return _content_sha256(_archive_entries(archive))
