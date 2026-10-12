"""Contextual assembly checks, kept separate from general format validation."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from ldraw.diagnostics import Diagnostic, Severity
from ldraw.lines import Comment, Line, OptionalLine, Quadrilateral, Triangle
from ldraw.model import ModelOccurrence
from ldraw.part_metadata import PartFileKind, PartStatus, parse_metadata_lines
from ldraw.pieces import Piece
from ldraw.resolution import DocumentResolver, RawGeometry
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw.model import Model
    from ldraw.part import ParsedObject
    from ldraw.parts import Parts


def _warning(
    code: str,
    message: str,
    *,
    section: Model | None = None,
    obj: ParsedObject | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=f"assembly.{code}",
        message=message,
        severity=Severity.WARNING,
        section=section.name if section else None,
        line_number=section.source_line_for(obj)
        if section and obj is not None
        else None,
    )


def assembly_issues(
    model: Model,
    *,
    parts: Parts | None = None,
    matrix_tolerance: float = 1e-6,
    connectivity: bool = False,
) -> Iterator[Diagnostic]:
    """Yield warnings about context; connectivity never establishes physical support."""
    if not math.isfinite(matrix_tolerance) or matrix_tolerance < 0:
        message = "matrix_tolerance must be finite and non-negative"
        raise ValueError(message)
    resolver = DocumentResolver(model, parts)
    raw_issues: list[Diagnostic] = []
    placements = _placements(resolver, raw_issues=raw_issues)
    yield from raw_issues
    yield from (
        replace(item, severity=Severity.WARNING) for item in resolver.diagnostics
    )
    yield from _world_placement_issues(placements, tolerance=matrix_tolerance)
    for section in (model, *model.submodels.values()):
        yield from _section_issues(section, tolerance=matrix_tolerance)
        yield from _reference_issues(section, resolver=resolver)
    reachable = _reachable(model)
    for key, section in model.submodels.items():
        if key not in reachable:
            yield _warning(
                "unreachable_section",
                f"Section {section.name!r} is unreachable",
                section=section,
            )
    if parts is None:
        yield _warning(
            "check_not_run",
            "Library shadowing, reference classification, and library-colour "
            "checks could not run without a parts library",
        )
    elif not parts.colours_by_code:
        yield _warning(
            "check_not_run",
            "Library-colour checks could not run without LDConfig colours",
        )
    if connectivity:
        yield from _connectivity_issues(model, parts=parts)


def _placements(
    resolver: DocumentResolver, *, raw_issues: list[Diagnostic]
) -> tuple[ModelOccurrence, ...]:
    placements: list[ModelOccurrence] = []
    for event in resolver.events():
        if isinstance(event, ModelOccurrence):
            placements.append(event)
        elif (
            isinstance(event, RawGeometry)
            and event.colour is not None
            and event.colour.code == 16
        ):
            raw_issues.append(
                Diagnostic(
                    code="assembly.unresolved_inherited_colour",
                    severity=Severity.WARNING,
                    message="Drawable record has no outer colour for colour 16",
                    section=event.section,
                    line_number=event.source_line,
                )
            )
    return tuple(placements)


def _reference_issues(
    section: Model, *, resolver: DocumentResolver
) -> Iterator[Diagnostic]:
    for piece in section.pieces:
        definition = resolver._definition(piece.reference)  # noqa: SLF001 - shared classification
        if definition is None or not definition.objects:
            continue
        metadata = parse_metadata_lines([obj.to_ldraw() for obj in definition.objects])
        if metadata.file_kind in {
            PartFileKind.SUBPART,
            PartFileKind.PRIMITIVE,
            PartFileKind.PRIMITIVE_8,
            PartFileKind.PRIMITIVE_48,
        }:
            yield _warning(
                "nonphysical_placement",
                f"Direct placement of {metadata.file_kind}: {piece.reference}",
                section=section,
                obj=piece,
            )
        if metadata.status in {PartStatus.ALIAS, PartStatus.MOVED}:
            yield _warning(
                "alias_placement",
                f"Alias placement {piece.reference}; target {metadata.replacement}",
                section=section,
                obj=piece,
            )


def _world_placement_issues(
    placements: tuple[ModelOccurrence, ...], *, tolerance: float
) -> Iterator[Diagnostic]:
    seen: set[tuple[object, ...]] = set()
    quantum = tolerance or 1e-12
    for occurrence in placements:
        key = (
            normalize_ref(occurrence.reference),
            occurrence.colour,
            *(
                round(value / quantum)
                for value in (
                    occurrence.position.x,
                    occurrence.position.y,
                    occurrence.position.z,
                    *occurrence.matrix.flatten(),
                )
            ),
        )
        if key in seen:
            yield _warning(
                "duplicate_world_placement",
                f"Duplicate world placement of {occurrence.reference}",
                section=occurrence.source_model,
                obj=occurrence.piece,
            )
        seen.add(key)
        if occurrence.matrix.det() < 0:
            yield _warning(
                "mirrored_placement",
                f"Mirrored placement of {occurrence.reference}",
                section=occurrence.source_model,
                obj=occurrence.piece,
            )
        if occurrence.colour.code == 16:
            yield _warning(
                "unresolved_inherited_colour",
                f"Inherited colour of {occurrence.reference} has no outer colour",
                section=occurrence.source_model,
                obj=occurrence.piece,
            )


def _section_issues(section: Model, *, tolerance: float) -> Iterator[Diagnostic]:
    if section.header_name and normalize_ref(section.header_name) != normalize_ref(
        section.name
    ):
        yield _warning(
            "header_name", "Name header disagrees with section name", section=section
        )
    invert = False
    geometry_seen = False
    for obj in section.objects:
        if isinstance(obj, Comment) and obj.text.startswith("BFC"):
            yield from _bfc_issues(
                obj, section=section, invert=invert, geometry_seen=geometry_seen
            )
            invert = invert or "INVERTNEXT" in obj.text
            continue
        if isinstance(obj, Piece | Line | OptionalLine | Triangle | Quadrilateral):
            geometry_seen = True
            if invert and not isinstance(obj, Piece):
                yield _warning(
                    "bfc_order",
                    "INVERTNEXT must precede a type-1 placement",
                    section=section,
                    obj=obj,
                )
            invert = False
            if (
                isinstance(obj, Piece | Triangle | Quadrilateral)
                and obj.colour.code == 24
            ):
                yield _warning(
                    "surface_colour",
                    "Edge colour 24 used for a surface or part",
                    section=section,
                    obj=obj,
                )
        if isinstance(obj, Triangle | Quadrilateral):
            yield from _polygon_issues(obj, section=section, tolerance=tolerance)
    if invert:
        yield _warning(
            "bfc_order",
            "Trailing INVERTNEXT has no following placement",
            section=section,
        )


def _bfc_issues(
    obj: Comment, *, section: Model, invert: bool, geometry_seen: bool
) -> Iterator[Diagnostic]:
    if "CERTIFY" in obj.text and geometry_seen:
        yield _warning(
            "bfc_order",
            "BFC certification follows drawable geometry",
            section=section,
            obj=obj,
        )
    if "INVERTNEXT" in obj.text and invert:
        yield _warning("bfc_order", "Repeated BFC INVERTNEXT", section=section, obj=obj)


def _polygon_issues(
    obj: Triangle | Quadrilateral, *, section: Model, tolerance: float
) -> Iterator[Diagnostic]:
    points = obj.points
    normal = (points[1] - points[0]).cross(points[2] - points[0])
    if abs(normal) <= tolerance or any(
        abs(left - right) <= tolerance
        for index, left in enumerate(points)
        for right in points[index + 1 :]
    ):
        yield _warning(
            "degenerate_polygon", "Degenerate polygon", section=section, obj=obj
        )
    elif isinstance(obj, Quadrilateral) and abs(
        normal.dot(points[3] - points[0])
    ) > tolerance * abs(normal):
        yield _warning(
            "nonplanar_polygon",
            "Non-planar quadrilateral",
            section=section,
            obj=obj,
        )


def _reachable(root: Model) -> set[str]:
    seen = {normalize_ref(root.name)}
    pending = [root]
    while pending:
        section = pending.pop()
        for piece in section.pieces:
            key = normalize_ref(piece.reference)
            if key not in seen and (target := root.submodel_for(piece)) is not None:
                seen.add(key)
                pending.append(target)
    return seen


def _connectivity_issues(model: Model, *, parts: Parts | None) -> Iterator[Diagnostic]:
    if parts is None:
        yield _warning(
            "check_not_run",
            "Connectivity could not run without geometry and connection evidence",
        )
        return
    from ldraw.inspection import inspect_model  # noqa: PLC0415

    inspection = inspect_model(model, parts)
    if inspection.connection_coverage != "complete":
        yield _warning(
            "check_not_run",
            "Connectivity evidence is incomplete; topology is qualified",
        )
    components = inspection.connection_graphs().optimistic.components()
    if len(components) > 1:
        yield _warning(
            "disconnected_components",
            f"{len(components)} components in supported optimistic topology; "
            "rigidity and physical support were not checked",
        )
