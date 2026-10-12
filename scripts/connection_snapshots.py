"""Explicitly regenerate the pinned connection corpus; tests never write it."""

# ruff: noqa: INP001
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict, deque
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ldraw._library_content import (
    archive_library_content_sha256,
    library_content_sha256,
)
from ldraw.dirs import get_cache_dir
from ldraw.geometry import Matrix
from ldraw.part_geometry import part_connections
from ldraw.parts import Parts

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "snapshots"
MANIFEST = CORPUS / "connections-2018-02-manifest.json"
SNAPSHOT = CORPUS / "connections-2018-02.json"
SEEDS = (
    "3001",
    "3005",
    "3023",
    "3068b",
    "4070",
    "87087",
    "99780",
    "99781",
    "3700",
    "2780",
    "3705",
    "30374",
    "4085c",
    "3641",
    "4624",
)


def archive_checksum(archive: Path) -> str:
    """Return an archive digest for optional provenance, not content identity."""
    with archive.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def select_codes(parts: Parts) -> list[str]:
    """Select 200 ordinary parts by round-robin category, including regressions."""
    codes = [code for code in SEEDS if parts.get_entry_by_code(code) is not None]
    categories: dict[str, deque[str]] = defaultdict(deque)
    for code, entry in sorted(parts.catalog.by_code.items()):
        if re.fullmatch(r"[0-9]{4,5}[a-z]?", code) and code not in codes:
            categories[entry.category.value].append(code)
    while len(codes) < 200:
        for category in sorted(categories):
            if categories[category]:
                codes.append(categories[category].popleft())
                if len(codes) == 200:
                    break
        if len(codes) < 200 and not any(categories.values()):
            message = "library does not contain 200 eligible parts"
            raise ValueError(message)
    return codes


def normalized(value: Any, *, library_root: Path) -> Any:  # noqa: ANN401, PLR0911 - recursive normalized type dispatch
    """Serialize connection data without host-specific paths or unordered sets."""
    if isinstance(value, Matrix):
        return list(value.flatten())
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.relative_to(library_root).as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: normalized(getattr(value, item.name), library_root=library_root)
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {
            key: normalized(item, library_root=library_root)
            for key, item in value.items()
        }
    if isinstance(value, tuple | list | frozenset):
        result = [normalized(item, library_root=library_root) for item in value]
        return sorted(result) if isinstance(value, frozenset) else result
    if isinstance(value, str):
        return value.replace(str(library_root), "<library>")
    return value


def snapshot(parts: Parts, codes: list[str]) -> dict[str, Any]:
    """Capture all feature fields, including identifiers and provenance."""
    return {
        code: normalized(part_connections(parts, code), library_root=parts.library_root)
        for code in codes
    }


def main() -> None:
    """Regenerate snapshots, optionally replacing the fixed selection."""
    cache = Path(get_cache_dir())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parts-list", type=Path, default=cache / "2018-02" / "ldraw" / "parts.lst"
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Verify archive content before recording optional archive provenance.",
    )
    parser.add_argument(
        "--select",
        action="store_true",
        help="Explicitly replace the fixed part selection and content digest.",
    )
    args = parser.parse_args()
    parts = Parts(args.parts_list)
    digest = library_content_sha256(parts.library_root)
    if args.select:
        manifest = {
            "schema_version": 2,
            "release": "2018-02",
            "library_content_sha256": digest,
            "part_codes": select_codes(parts),
        }
    else:
        manifest = json.loads(MANIFEST.read_text())
        if manifest.get("schema_version") != 2:
            message = "unsupported corpus manifest schema; migrate to content identity"
            raise ValueError(message)
        if digest != manifest["library_content_sha256"]:
            message = (
                "2018-02 library content differs; inspect the extracted files "
                "before explicitly reselecting"
            )
            raise ValueError(message)
    if args.archive is not None:
        if archive_library_content_sha256(args.archive) != digest:
            message = "archive library content differs from the extracted library"
            raise ValueError(message)
        manifest["archive_sha256"] = archive_checksum(args.archive)
    result = snapshot(parts, manifest["part_codes"])
    CORPUS.mkdir(exist_ok=True)
    MANIFEST.write_text(f"{json.dumps(manifest, indent=2)}\n", encoding="utf-8")
    SNAPSHOT.write_text(f"{json.dumps(result, indent=2)}\n", encoding="utf-8")
    print(f"Captured {len(result)} parts; review the snapshot diff before committing.")


if __name__ == "__main__":
    main()
