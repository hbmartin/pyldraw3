"""Validation of LDraw model and part files."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
from math import isfinite
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.lines import Line, MetaCommand, OptionalLine, Quadrilateral, Triangle
from ldraw.parts import CatalogSearchField
from ldraw.pieces import Piece
from ldraw.serialization import format_ldraw_number
from ldraw.utils import normalize_ref, split_ldraw_reference

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ldraw.colour import Colour
    from ldraw.geometry import Matrix, Vector
    from ldraw.model import Model, ModelLoadResult
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


@dataclass(slots=True)
class _NumericAnalysis:
    values: tuple[float, ...]
    invalid: tuple[tuple[str, float], ...] = ()
    matrix_invalid: bool = False


_PLACEMENT_FIELDS = (
    "position.x",
    "position.y",
    "position.z",
    *(f"matrix[{row}][{column}]" for row in range(3) for column in range(3)),
)


def _placement_analysis(position: Vector, matrix: Matrix) -> _NumericAnalysis:
    values = (position.x, position.y, position.z, *matrix.flatten())
    if all(isfinite(value) for value in values):
        return _NumericAnalysis(values)
    invalid = tuple(
        (field, value)
        for field, value in zip(_PLACEMENT_FIELDS, values, strict=True)
        if not isfinite(value)
    )
    return _NumericAnalysis(
        values=values,
        invalid=invalid,
        matrix_invalid=any(field.startswith("matrix[") for field, _ in invalid),
    )


def _object_analysis(parsed: ParsedObject) -> _NumericAnalysis:
    match parsed:
        case Piece():
            position, matrix = parsed._transformed()  # noqa: SLF001 - effective placement
            return _placement_analysis(position=position, matrix=matrix)
        case Line() | Triangle() | Quadrilateral() | OptionalLine():
            invalid = tuple(
                (f"point{index}.{axis}", value)
                for index, point in enumerate(parsed.points, start=1)
                for axis in ("x", "y", "z")
                if not isfinite(value := getattr(point, axis))
            )
            return _NumericAnalysis(values=(), invalid=invalid)
        case _:
            return _NumericAnalysis(())


def iter_duplicate_issues(
    model: Model, *, path: Path | None = None
) -> Iterator[ValidationIssue]:
    """Warn about placements equal at serialization precision in one section."""
    yield from _iter_duplicate_issues(
        ((piece, _object_analysis(piece)) for piece in model.pieces),
        model=model,
        path=path,
    )


def _iter_duplicate_issues(
    placements: Iterator[tuple[Piece, _NumericAnalysis]],
    *,
    model: Model,
    path: Path | None,
) -> Iterator[ValidationIssue]:
    cached_format = lru_cache(maxsize=4_096)(format_ldraw_number)
    format_number = cached_format
    finite_count = 0
    seen: dict[tuple[object, ...], int | None] = {}
    for piece, analysis in placements:
        if analysis.invalid:
            continue
        key = (
            normalize_ref(piece.reference),
            piece.colour,
            *(format_number(value) for value in analysis.values),
        )
        finite_count += 1
        if finite_count == 128:
            info = cached_format.cache_info()
            if info.hits / (info.hits + info.misses) < 0.25:
                format_number = format_ldraw_number
                cached_format.cache_clear()
        number = model.source_line_for(piece)
        if key in seen:
            first = seen[key]
            location = f"line {first}" if first is not None else "an earlier placement"
            yield ValidationIssue(
                line_number=number,
                message=(
                    f"duplicate placement of {piece.reference}; first at {location}"
                ),
                severity=Severity.WARNING,
                code=DiagnosticCode.MODEL_DUPLICATE_PLACEMENT,
                path=path,
                section=model.name or None,
                offending_value=piece.reference,
            )
        else:
            seen[key] = number


def _unknown_part(piece: Piece, parts: Parts) -> bool:
    return parts.find_part(code=piece.part) is None


def _numeric_issue(
    analysis: _NumericAnalysis,
    *,
    number: int | None,
    path: Path | None,
    section: str | None,
) -> ValidationIssue | None:
    invalid = ", ".join(f"{field}={value!r}" for field, value in analysis.invalid)
    if not invalid:
        return None
    return ValidationIssue(
        line_number=number,
        message=f"non-finite numeric fields: {invalid}",
        code=DiagnosticCode.MODEL_NON_FINITE_NUMERIC,
        path=path,
        section=section,
        offending_value=invalid,
    )


def _iter_model_numeric_issues(
    model: Model, *, placements: dict[Piece, tuple[Vector, Matrix]] | None = None
) -> Iterator[ValidationIssue]:
    """Check declared geometry, or only reachable sections for a submodel view."""
    pending = [model]
    visited: set[int] = set()
    while pending:
        section = pending.pop()
        if id(section) in visited:
            continue
        visited.add(id(section))
        if model._is_submodel_view:  # noqa: SLF001 - comparison validation scope
            targets = [
                target
                for piece in section.pieces
                if (target := model.submodel_for(piece)) is not None
            ]
        else:
            targets = list(section.submodels.values())
        pending.extend(reversed(targets))
        for obj in section.objects:
            if isinstance(obj, Piece) and placements is not None:
                if obj in placements:
                    continue
                position, matrix = obj._transformed()  # noqa: SLF001 - effective placement
                analysis = _placement_analysis(position=position, matrix=matrix)
                if not analysis.invalid:
                    placements[obj] = position, matrix
            else:
                analysis = _object_analysis(obj)
            if issue := _numeric_issue(
                analysis,
                number=section.source_line_for(obj),
                path=None,
                section=section.name or None,
            ):
                yield issue


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
    code = split_ldraw_reference(reference)[0].replace("\\", "/")
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
    yield from _iter_object_issues(
        parsed,
        analysis=_object_analysis(parsed),
        number=number,
        parts=parts,
        submodels=submodels,
        path=path,
        section=section,
    )


def _iter_object_issues(  # noqa: PLR0913 - shared parsed-object analysis and context
    parsed: ParsedObject,
    *,
    analysis: _NumericAnalysis,
    number: int,
    parts: Parts | None,
    submodels: set[str],
    path: Path | None,
    section: str | None,
) -> Iterator[ValidationIssue]:
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
    numeric_issue = _numeric_issue(analysis, number=number, path=path, section=section)
    if numeric_issue is not None:
        yield numeric_issue
    if not isinstance(parsed, Piece):
        return
    if (
        not analysis.matrix_invalid
        or all(isfinite(value) for value in parsed.matrix.flatten())
    ) and (
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


def _iter_section_issues(
    model: Model, *, parts: Parts | None, submodels: set[str], path: Path | None
) -> Iterator[ValidationIssue]:
    """Share each object's numeric analysis across section validation passes."""
    object_issues: list[ValidationIssue] = []

    def placements() -> Iterator[tuple[Piece, _NumericAnalysis]]:
        for obj in model.objects:
            number = model.source_line_for(obj)
            if number is None and not isinstance(obj, Piece):
                continue
            analysis = _object_analysis(obj)
            if number is not None:
                object_issues.extend(
                    _iter_object_issues(
                        obj,
                        analysis=analysis,
                        number=number,
                        parts=parts,
                        submodels=submodels,
                        path=path,
                        section=model.name or None,
                    )
                )
            if isinstance(obj, Piece):
                yield obj, analysis

    yield from _iter_duplicate_issues(placements(), model=model, path=path)
    yield from object_issues


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
