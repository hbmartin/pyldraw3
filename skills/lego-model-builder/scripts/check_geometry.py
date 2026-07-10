#!/usr/bin/env python3
"""Lightweight geometry sanity check for a generated LDraw model.

Flags two cheap, high-signal problem classes (it does NOT do true 3-D collision):

  1. Exact-duplicate placements — two pieces with the same part, colour, and
     position (a copy-paste / loop-bounds mistake).
  2. Obviously floating pieces — a piece with nothing beneath it anywhere near
     its column and which is not resting on the base layer.

Tolerances are deliberately generous so legitimately offset stacking (a 1x4 on
two 1x2s) is NOT flagged; the goal is few, trustworthy warnings. It never fails
the build — it prints warnings and exits 0.

Usage:
    python check_geometry.py MODEL.ldr
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

# LDU tolerances (see references/api-cheatsheet.md: brick=24, plate=8, stud=20).
XZ_TOL = 40.0  # "roughly in the same column" — 2 studs of slack
VERTICAL_GAP = 28.0  # a supporter at most ~one brick (24) below, plus slack
GROUND_TOL = 8.0  # within a plate-height of the lowest layer counts as grounded


def _colour_key(colour: object) -> object:
    """Return a hashable, comparable colour identity."""
    code = getattr(colour, "code", None)
    return code if code is not None else colour


def _load_pieces(model_path: Path) -> list:
    # Keep this lazy so --help works without pyldraw3 installed.
    from ldraw import read_model  # noqa: PLC0415

    model = read_model(str(model_path))
    pieces = list(getattr(model, "pieces", []) or [])
    if not pieces and hasattr(model, "iter_pieces"):
        pieces = list(model.iter_pieces())
    return pieces


def _find_duplicates(pieces: list) -> list[str]:
    seen: dict[tuple, int] = defaultdict(int)
    for p in pieces:
        pos = p.position
        key = (
            p.part.casefold(),
            _colour_key(p.colour),
            round(pos.x, 1),
            round(pos.y, 1),
            round(pos.z, 1),
        )
        seen[key] += 1
    warnings = []
    for (part, colour, x, y, z), count in seen.items():
        if count > 1:
            warnings.append(
                f"duplicate: {count}x part {part} colour {colour} at "
                f"({x:g}, {y:g}, {z:g}) — same piece placed on top of itself"
            )
    return warnings


def _find_floating(pieces: list) -> list[str]:
    if len(pieces) < 2:
        return []
    # In LDraw, -Y is up; the base layer has the LARGEST y. "Below" = larger y.
    max_y = max(p.position.y for p in pieces)
    warnings = []
    for p in pieces:
        py = p.position.y
        if py >= max_y - GROUND_TOL:
            continue  # resting on the base layer
        supported = any(
            q is not p
            and q.position.y > py
            and (q.position.y - py) <= VERTICAL_GAP
            and abs(q.position.x - p.position.x) <= XZ_TOL
            and abs(q.position.z - p.position.z) <= XZ_TOL
            for q in pieces
        )
        if not supported:
            warnings.append(
                f"floating?: part {p.part} at "
                f"({p.position.x:g}, {py:g}, {p.position.z:g}) has nothing beneath it"
            )
    return warnings


def main(argv: list[str] | None = None) -> int:
    """Check the model named in argv and return a CLI status code."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    model_path = Path(argv[0])
    if not model_path.is_file():
        print(f"error: model not found: {model_path}", file=sys.stderr)
        return 2
    try:
        pieces = _load_pieces(model_path)
    except ImportError:
        print(
            "error: pyldraw3 not importable; run preflight.sh first.",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - report and continue, don't crash the skill
        print(f"error: could not parse {model_path}: {exc}", file=sys.stderr)
        return 2

    warnings = _find_duplicates(pieces) + _find_floating(pieces)
    if not warnings:
        print(f"GEOMETRY: OK ({len(pieces)} pieces, no duplicates or floating pieces)")
        return 0

    print(f"GEOMETRY: {len(warnings)} warning(s) across {len(pieces)} pieces:")
    for w in warnings:
        print(f"  WARN {w}")
    print(
        "Note: heuristic only (generous tolerances; no true 3-D collision). "
        "Verify against the render before acting."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
