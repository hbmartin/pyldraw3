"""Validation of LDraw model and part files."""

from __future__ import annotations

from difflib import get_close_matches
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.lines import Line, MetaCommand, OptionalLine, Quadrilateral, Triangle
from ldraw.parts import CatalogSearchField
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ldraw.colour import Colour
    from ldraw.model import ModelLoadResult
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


ValidationIssue = Diagnostic


def _unknown_part(piece: Piece, parts: Parts) -> bool:
    return parts.find_part(code=piece.part) is None


_candidate_codes_cache: WeakKeyDictionary[Parts, tuple[int, tuple[str, ...]]] = (
    WeakKeyDictionary()
)


def _candidate_codes(parts: Parts) -> tuple[str, ...]:
    """Return the sorted casefolded catalog codes, built once per catalog."""
    count = len(parts.catalog.by_code)
    if (cached := _candidate_codes_cache.get(parts)) is not None:
        cached_count, candidates = cached
        if cached_count == count:
            return candidates
    candidates = tuple(
        sorted(candidate.casefold() for candidate in parts.catalog.by_code),
    )
    _candidate_codes_cache[parts] = (count, candidates)
    return candidates


def _part_suggestions(reference: str, parts: Parts) -> tuple[str, ...]:
    code = reference.rsplit(".", maxsplit=1)[0].replace("\\", "/")
    substring = parts.catalog.search(
        code,
        fields=(CatalogSearchField.CODE,),
        limit=3,
    )
    if substring:
        return tuple(entry.code for entry in substring)
    matches = get_close_matches(
        code.casefold(),
        _candidate_codes(parts),
        n=3,
        cutoff=0.55,
    )
    return tuple(matches)


def _colour_suggestions(value: int, parts: Parts) -> tuple[str, ...]:
    codes = {str(code): colour for code, colour in parts.colours_by_code.items()}
    matches = get_close_matches(str(value), sorted(codes), n=3, cutoff=0.4)
    return tuple(
        f"{code} ({codes[code].name})" if codes[code].name else code for code in matches
    )


def _colour_issue(
    colour: Colour,
    number: int,
    parts: Parts | None,
    *,
    path: Path | None,
    section: str | None,
) -> ValidationIssue | None:
    if parts is None or colour.code is None or not parts.colours_by_code:
        return None
    colours_by_code = parts.colours_by_code
    if colour.code in colours_by_code:
        return None
    if _LEGACY_DITHERED_MIN <= colour.code <= _LEGACY_DITHERED_MAX:
        return ValidationIssue(
            line_number=number,
            message=f"legacy dithered colour code {colour.code}",
            severity=Severity.WARNING,
            code=DiagnosticCode.MODEL_LEGACY_COLOUR,
            path=path,
            section=section,
            offending_value=colour.code,
        )
    return ValidationIssue(
        line_number=number,
        message=f"unknown colour code {colour.code}",
        code=DiagnosticCode.MODEL_UNKNOWN_COLOUR,
        path=path,
        section=section,
        offending_value=colour.code,
        suggestions=_colour_suggestions(colour.code, parts),
    )


def _matrix_issue(
    piece: Piece,
    number: int,
    *,
    path: Path | None,
    section: str | None,
) -> ValidationIssue | None:
    if piece.matrix.is_singular():
        return ValidationIssue(
            line_number=number,
            message="singular transformation matrix (flattens geometry)",
            severity=Severity.WARNING,
            code=DiagnosticCode.MODEL_SINGULAR_MATRIX,
            path=path,
            section=section,
            offending_value=piece.matrix,
        )
    if not piece.matrix.is_orthonormal():
        return ValidationIssue(
            line_number=number,
            message="transformation matrix is not orthonormal (scaled or sheared part)",
            severity=Severity.WARNING,
            code=DiagnosticCode.MODEL_NON_ORTHONORMAL_MATRIX,
            path=path,
            section=section,
            offending_value=piece.matrix,
        )
    return None


def _meta_issue(
    meta: MetaCommand,
    number: int,
    *,
    path: Path | None,
    section: str | None,
) -> ValidationIssue | None:
    if meta.type not in KNOWN_META_COMMANDS:
        return ValidationIssue(
            line_number=number,
            message=f"unknown meta-command !{meta.type}",
            severity=Severity.WARNING,
            code=DiagnosticCode.MODEL_UNKNOWN_META,
            path=path,
            section=section,
            offending_value=meta.type,
        )
    return None


def iter_object_issues(  # noqa: PLR0913 - parsed-object context is explicit
    parsed: ParsedObject,
    *,
    number: int,
    parts: Parts | None,
    submodels: set[str],
    path: Path | None = None,
    section: str | None = None,
) -> Iterator[ValidationIssue]:
    """Yield validation diagnostics for one already-parsed source object."""
    if isinstance(parsed, MetaCommand):
        if (
            meta_issue := _meta_issue(
                parsed,
                number,
                path=path,
                section=section,
            )
        ) is not None:
            yield meta_issue
        return
    if isinstance(parsed, _COLOURED_TYPES) and (
        colour_issue := _colour_issue(
            parsed.colour,
            number,
            parts,
            path=path,
            section=section,
        )
    ):
        yield colour_issue
    if not isinstance(parsed, Piece):
        return
    if (
        matrix_issue := _matrix_issue(
            parsed,
            number,
            path=path,
            section=section,
        )
    ) is not None:
        yield matrix_issue
    if (
        parts is not None
        and normalize_ref(parsed.reference) not in submodels
        and _unknown_part(piece=parsed, parts=parts)
    ):
        yield ValidationIssue(
            line_number=number,
            message=f"unknown part {parsed.reference}",
            code=DiagnosticCode.MODEL_UNKNOWN_PART,
            path=path,
            section=section,
            offending_value=parsed.reference,
            suggestions=_part_suggestions(parsed.reference, parts),
        )


def iter_ldr_issues(
    path: Path | ModelLoadResult,
    parts: Parts | None = None,
) -> Iterator[ValidationIssue]:
    """Yield the issues found in an LDraw model or part file, in line order.

    Malformed lines, unparseable colour values, and (when a parts catalog
    with colour definitions is given) unknown part references and colour
    codes are errors. Suspicious-but-legal constructs — legacy dithered
    colours, non-orthonormal or singular transformation matrices, and
    unknown bang meta-commands — are warnings.

    Unreadable or non-UTF-8 files do not raise; they yield an
    ``IO_READ_FAILED`` or ``IO_DECODE_FAILED`` error diagnostic with
    ``line_number=None``. Issues are yielded sorted by line number, with
    file-level diagnostics (``line_number=None``) first.
    """
    from ldraw.model import ModelLoadResult, load_model  # noqa: PLC0415

    result = (
        path if isinstance(path, ModelLoadResult) else load_model(path, parts=parts)
    )
    yield from sorted(
        result.diagnostics,
        key=lambda issue: (issue.line_number is not None, issue.line_number or 0),
    )
