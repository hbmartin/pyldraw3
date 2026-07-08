"""Validation of LDraw model and part files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.errors import PartError
from ldraw.model import _file_name, _normalize_ref
from ldraw.part import parse_ldraw_line
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A problem found on one line of an LDraw file."""

    line_number: int
    message: str


def _unknown_part(piece: Piece, parts: Parts) -> bool:
    try:
        return parts.part(code=piece.part) is None
    except PartError:
        return True


def iter_ldr_issues(
    path: Path,
    parts: Parts | None = None,
) -> Iterator[ValidationIssue]:
    """Yield the issues found in an LDraw model or part file.

    Malformed lines are always reported. When a parts catalog is given,
    type-1 references that resolve to neither a catalogued part nor a
    ``0 FILE`` submodel section of the same document are reported too.
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    submodels = {
        _normalize_ref(name) for line in lines if (name := _file_name(line)) is not None
    }
    for number, line in enumerate(lines, start=1):
        try:
            parsed = parse_ldraw_line(line)
        except PartError as error:
            message = " ".join(error.message.splitlines())
            yield ValidationIssue(line_number=number, message=message)
            continue
        if (
            parts is not None
            and isinstance(parsed, Piece)
            and _normalize_ref(parsed.reference) not in submodels
            and _unknown_part(parsed, parts)
        ):
            yield ValidationIssue(
                line_number=number,
                message=f"unknown part {parsed.reference}",
            )
