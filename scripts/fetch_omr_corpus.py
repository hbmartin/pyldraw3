#!/usr/bin/env python
"""Fetch a small curated corpus of real LDraw OMR models.

Downloads a hand-picked set of models from the LDraw Official Model
Repository (https://library.ldraw.org/omr) for local round-trip fidelity
testing with ``scripts/check_roundtrip.py``. This is a local developer
tool: CI never fetches the corpus (bandwidth and licensing), so run it
yourself or via the ``verify-roundtrip`` agent skill.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

OMR_BASE = "https://library.ldraw.org/library/omr"

# Chosen for feature coverage: 1970s sets with legacy colours (390, 894),
# a classic-space MPD with no 0 NOFILE terminators (6861), a castle set
# (6054), mid-size models (3681, 75060), and large modern Technic files
# (42111, 42054). Sizes range from ~3 KB to ~2.8 MB.
CURATED_MODELS: dict[str, str] = {
    name: f"{OMR_BASE}/{name}"
    for name in (
        "390-2.mpd",
        "894-1.mpd",
        "3681-1.mpd",
        "6054-1.mpd",
        "6861-1.mpd",
        "42054-1.mpd",
        "42111-1.mpd",
        "75060-1.mpd",
    )
}

_CHUNK_SIZE = 65_536
_TIMEOUT_SECONDS = 60


def _looks_like_ldraw(path: Path) -> bool:
    """Return whether the file starts with an LDraw line (not an HTML 404)."""
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                return stripped[0] in "012345"
    return False


def fetch_model(name: str, url: str, dest: Path, *, force: bool) -> str:
    """Download one model; return a status string for the manifest."""
    target = dest / name
    if target.exists() and not force:
        return "cached"
    partial = target.with_suffix(f"{target.suffix}.part")
    response = requests.get(url, stream=True, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    with partial.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            handle.write(chunk)
    if not _looks_like_ldraw(partial):
        partial.unlink()
        message = f"{url} did not return LDraw content (moved or removed?)"
        raise ValueError(message)
    partial.replace(target)
    return "downloaded"


def main(argv: list[str] | None = None) -> int:
    """Fetch the curated corpus and write a manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("corpus"),
        help="Directory to download models into (default: ./corpus).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files that already exist.",
    )
    args = parser.parse_args(argv)

    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)
    statuses: dict[str, str] = {}
    for name, url in CURATED_MODELS.items():
        try:
            statuses[name] = fetch_model(name, url, dest, force=args.force)
        except (requests.RequestException, ValueError) as exc:
            statuses[name] = f"FAILED: {exc}"
        print(f"{name}: {statuses[name]}")

    manifest = dest / "manifest.txt"
    manifest.write_text(
        "".join(f"{name}\t{status}\n" for name, status in statuses.items()),
        encoding="utf-8",
    )
    fetched = sum(1 for status in statuses.values() if not status.startswith("FAILED"))
    print(f"{fetched}/{len(CURATED_MODELS)} models available in {dest}")
    return 0 if fetched else 1


if __name__ == "__main__":
    sys.exit(main())
