"""Validation of LDraw model and part files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ldraw.errors import PartError
from ldraw.lines import Line, MetaCommand, OptionalLine, Quadrilateral, Triangle
from ldraw.part import parse_ldraw_line
from ldraw.pieces import Piece
from ldraw.utils import ldraw_file_name, normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ldraw.colour import Colour
    from ldraw.part import ParsedObject
    from ldraw.parts import Parts

# Official bang meta-commands from the ldraw.org File Format, Official
# Header, MPD, and OMR specs, plus widespread editor metas ("!:" is the
# TEXMAP fallback prefix; LDCad and BrickLink Studio write their own).
# Plain "0 STEP"-style commands parse as comments and are never checked
# against this list.
KNOWN_META_COMMANDS = frozenset(
    {
        "LDRAW_ORG",
        "LICENSE",
        "CATEGORY",
        "KEYWORDS",
        "CMDLINE",
        "HELP",
        "HISTORY",
        "COLOUR",
        "TEXMAP",
        "DATA",
        ":",
        "THEME",
        "LPUB",
        "PYLDRAW",
        "LEOCAD",
        "LDCAD",
        "STUDIO",
    }
)

_LEGACY_DITHERED_MIN = 256
_LEGACY_DITHERED_MAX = 511

_COLOURED_TYPES = (Piece, Line, Triangle, Quadrilateral, OptionalLine)


class Severity(StrEnum):
    """How serious a validation issue is."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A problem found on one line of an LDraw file."""

    line_number: int
    message: str
    severity: Severity = Severity.ERROR


def _unknown_part(piece: Piece, parts: Parts) -> bool:
    return parts.find_part(code=piece.part) is None


def _colour_issue(
    colour: Colour,
    number: int,
    colours_by_code: dict[int, Colour] | None,
) -> ValidationIssue | None:
    if colour.code is None or colours_by_code is None:
        return None
    if colour.code in colours_by_code:
        return None
    if _LEGACY_DITHERED_MIN <= colour.code <= _LEGACY_DITHERED_MAX:
        return ValidationIssue(
            line_number=number,
            message=f"legacy dithered colour code {colour.code}",
            severity=Severity.WARNING,
        )
    return ValidationIssue(
        line_number=number,
        message=f"unknown colour code {colour.code}",
    )


def _matrix_issue(piece: Piece, number: int) -> ValidationIssue | None:
    if piece.matrix.is_singular():
        return ValidationIssue(
            line_number=number,
            message="singular transformation matrix (flattens geometry)",
            severity=Severity.WARNING,
        )
    if not piece.matrix.is_orthonormal():
        return ValidationIssue(
            line_number=number,
            message="transformation matrix is not orthonormal (scaled or sheared part)",
            severity=Severity.WARNING,
        )
    return None


def _meta_issue(meta: MetaCommand, number: int) -> ValidationIssue | None:
    if meta.type not in KNOWN_META_COMMANDS:
        return ValidationIssue(
            line_number=number,
            message=f"unknown meta-command !{meta.type}",
            severity=Severity.WARNING,
        )
    return None


def _object_issues(
    parsed: ParsedObject,
    *,
    number: int,
    parts: Parts | None,
    submodels: set[str],
    colours_by_code: dict[int, Colour] | None,
) -> Iterator[ValidationIssue]:
    if isinstance(parsed, MetaCommand):
        if (meta_issue := _meta_issue(parsed, number)) is not None:
            yield meta_issue
        return
    if isinstance(parsed, _COLOURED_TYPES) and (
        colour_issue := _colour_issue(parsed.colour, number, colours_by_code)
    ):
        yield colour_issue
    if not isinstance(parsed, Piece):
        return
    if (matrix_issue := _matrix_issue(parsed, number)) is not None:
        yield matrix_issue
    if (
        parts is not None
        and normalize_ref(parsed.reference) not in submodels
        and _unknown_part(piece=parsed, parts=parts)
    ):
        yield ValidationIssue(
            line_number=number,
            message=f"unknown part {parsed.reference}",
        )


def iter_ldr_issues(
    path: Path,
    parts: Parts | None = None,
) -> Iterator[ValidationIssue]:
    """Yield the issues found in an LDraw model or part file.

    Malformed lines, unparseable colour values, and (when a parts catalog
    with colour definitions is given) unknown part references and colour
    codes are errors. Suspicious-but-legal constructs — legacy dithered
    colours, non-orthonormal or singular transformation matrices, and
    unknown bang meta-commands — are warnings.
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    submodels = {
        normalize_ref(name)
        for line in lines
        if (name := ldraw_file_name(line)) is not None
    }
    colours_by_code = parts.colours_by_code if parts is not None else None
    for number, line in enumerate(lines, start=1):
        try:
            parsed = parse_ldraw_line(line)
        except PartError as error:
            message = " ".join(error.message.splitlines())
            yield ValidationIssue(line_number=number, message=message)
            continue
        except ValueError as error:
            message = " ".join(str(error).splitlines())
            yield ValidationIssue(line_number=number, message=message)
            continue
        if parsed is None:
            continue
        yield from _object_issues(
            parsed,
            number=number,
            parts=parts,
            submodels=submodels,
            colours_by_code=colours_by_code or None,
        )
