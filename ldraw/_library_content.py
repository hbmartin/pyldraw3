"""Portable content identity for extracted LDraw geometry and colours."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def library_content_sha256(library_root: Path) -> str:
    """Hash sorted relative paths and bytes, ignoring extraction metadata.

    Include drawable .dat sources under parts/ and p/, and the canonical
    root LDConfig.ldr. Generated catalogs, receipts, and archive wrappers
    are outside this content identity. Pass the normalized library root.
    """
    paths = [
        path
        for name in ("parts", "p")
        for path in (library_root / name).rglob("*")
        if path.is_file() and path.suffix.casefold() == ".dat"
    ]
    paths.extend(
        path
        for path in library_root.iterdir()
        if path.is_file() and path.name.casefold() == "ldconfig.ldr"
    )
    digest = hashlib.sha256()
    ordered = sorted(paths, key=lambda item: item.relative_to(library_root).as_posix())
    for path in ordered:
        relative = path.relative_to(library_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(length=8, byteorder="big"))
        digest.update(relative)
        with path.open("rb") as source:
            digest.update(hashlib.file_digest(source, "sha256").digest())
    return digest.hexdigest()
