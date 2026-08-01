"""Exact world geometry, provenance, and broad-phase model inspection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError, PartError
from ldraw.geometry import Vector
from ldraw.lines import Comment
from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.geometry import Matrix
    from ldraw.model import Model, ModelOccurrence
    from ldraw.parts import Parts

DEFAULT_PAGE_MARKER_PREFIX = "// PDF_PAGE "


@dataclass(frozen=True, slots=True)
class OccurrenceAttribution:
    """Stable traversal identity and full source path for one occurrence."""

    index: int
    occurrence: ModelOccurrence
    model_path: tuple[str, ...]
    reference_path: tuple[str, ...]
    source_line_path: tuple[int | None, ...]
    local_step_path: tuple[int | None, ...]
    effective_step_path: tuple[int | None, ...]
    page_path: tuple[int | None, ...]

    @property
    def step_path(self) -> tuple[int | None, ...]:
        """Compatibility alias for local source steps."""
        return self.local_step_path

    @property
    def installation_page(self) -> int | None:
        """Page that places the outermost occurrence or submodel instance."""
        return self.page_path[0] if self.page_path else None

    @property
    def source_page(self) -> int | None:
        """Page local to the section which directly places the leaf part."""
        return self.page_path[-1] if self.page_path else None


@dataclass(frozen=True, slots=True)
class OccurrenceGeometry:
    """Expanded local geometry transformed into one occurrence's world frame."""

    attribution: OccurrenceAttribution
    local: PartGeometry
    bounds: BoundingBox
    studs: tuple[StudReference, ...]

    @property
    def occurrence(self) -> ModelOccurrence:
        """Return the source occurrence represented by this geometry."""
        return self.attribution.occurrence

    @property
    def index(self) -> int:
        """Return the occurrence's stable analysis-order index."""
        return self.attribution.index


@dataclass(frozen=True, slots=True)
class SkippedOccurrenceGeometry:
    """Occurrence whose geometry could not produce world bounds."""

    attribution: OccurrenceAttribution
    diagnostic: Diagnostic

    @property
    def reason(self) -> str:
        """Return the structured diagnostic's human-readable message."""
        return self.diagnostic.message


@dataclass(frozen=True, slots=True)
class BoundsGap:
    """Non-negative axis and Euclidean separation between two AABBs."""

    axes: Vector
    distance: float

    @property
    def intersects(self) -> bool:
        """Return whether the two bounds overlap or touch."""
        return self.distance == 0.0


@dataclass(frozen=True, slots=True)
class OccurrenceContact:
    """One occurrence and its nearest AABB neighbour."""

    subject: OccurrenceGeometry
    nearest: OccurrenceGeometry
    gap: BoundsGap


@dataclass(frozen=True, slots=True)
class StudContact:
    """A protruding stud whose short probe intersects another occurrence."""

    stud_occurrence: OccurrenceGeometry
    supported_occurrence: OccurrenceGeometry
    stud: StudReference
    position: Vector


@dataclass(frozen=True, slots=True)
class ModelInspection:
    """Exact bounds, resolved occurrences, failures, and source attribution."""

    bounds: BoundingBox | None
    occurrences: tuple[OccurrenceGeometry, ...]
    skipped_geometry: tuple[SkippedOccurrenceGeometry, ...]
    diagnostics: tuple[Diagnostic, ...]
    occurrence_count: int

    @property
    def complete(self) -> bool:
        """Whether every occurrence and nested part reference resolved."""
        return not self.skipped_geometry and not self.diagnostics

    def stud_contacts(
        self,
        *,
        tolerance: float = 0.1,
        probe_distance: float = 0.1,
    ) -> tuple[StudContact, ...]:
        """Return protruding studs whose base/probe meet another AABB."""
        if tolerance < 0:
            message = "tolerance must be non-negative"
            raise ValueError(message)
        if probe_distance <= 0:
            message = "probe_distance must be positive"
            raise ValueError(message)
        contacts: list[StudContact] = []
        for stud_occurrence in self.occurrences:
            for stud in stud_occurrence.studs:
                if stud.is_receptacle or stud.is_placeholder:
                    continue
                length = abs(stud.up)
                if length == 0:
                    continue
                probe = stud.position + probe_distance * (stud.up / length)
                contacts.extend(
                    StudContact(
                        stud_occurrence=stud_occurrence,
                        supported_occurrence=candidate,
                        stud=stud,
                        position=stud.position.copy(),
                    )
                    for candidate in self.occurrences
                    if candidate.index != stud_occurrence.index
                    and _box_contains(candidate.bounds, stud.position, tolerance)
                    and _box_contains(candidate.bounds, probe, tolerance)
                )
        return tuple(contacts)

    def contact_gaps(
        self,
        *,
        minimum_gap: float = 5.0,
        chronological: bool = False,
    ) -> tuple[OccurrenceContact, ...]:
        """Return occurrences farther than ``minimum_gap`` from every peer."""
        if minimum_gap < 0:
            message = "minimum_gap must be non-negative"
            raise ValueError(message)
        disconnected: list[OccurrenceContact] = []
        for subject in self.occurrences:
            candidates = tuple(
                candidate
                for candidate in self.occurrences
                if candidate.index != subject.index
                and (not chronological or _not_installed_later(subject, candidate))
            )
            if not candidates:
                continue
            nearest, gap = min(
                (
                    (candidate, bounds_gap(subject.bounds, candidate.bounds))
                    for candidate in candidates
                ),
                key=lambda item: (item[1].distance, item[0].index),
            )
            if gap.distance > minimum_gap:
                disconnected.append(
                    OccurrenceContact(subject=subject, nearest=nearest, gap=gap),
                )
        return tuple(
            sorted(
                disconnected,
                key=lambda contact: (-contact.gap.distance, contact.subject.index),
            ),
        )


def inspect_model(
    model: Model,
    parts: Parts,
    *,
    occurrences: Iterable[ModelOccurrence] | None = None,
    page_marker_prefix: str = DEFAULT_PAGE_MARKER_PREFIX,
) -> ModelInspection:
    """Inspect leaf occurrences using recursively expanded exact geometry."""
    piece_pages = _piece_pages(model, marker_prefix=page_marker_prefix)
    world_bounds = _BoundsAccumulator()
    inspected: list[OccurrenceGeometry] = []
    skipped: list[SkippedOccurrenceGeometry] = []
    diagnostics: list[Diagnostic] = []
    all_occurrences = tuple(
        model.iter_occurrences(include_steps=True)
        if occurrences is None
        else occurrences
    )
    noted_parts: set[str] = set()

    def note_part_diagnostics(code: str, local: PartGeometry) -> None:
        """Surface a part's own diagnostics once per part, not per placement."""
        key = code.replace("\\", "/").casefold()
        if key in noted_parts:
            return
        noted_parts.add(key)
        diagnostics.extend(local.diagnostics)

    for index, occurrence in enumerate(all_occurrences):
        attribution = _attribution(occurrence, index=index, piece_pages=piece_pages)
        try:
            local = parts.geometry(occurrence.part_code)
            # Recorded before the bounds checks so the root-cause
            # diagnostics (e.g. an unresolved subfile) survive even when
            # the occurrence is skipped below.
            note_part_diagnostics(occurrence.part_code, local)
            if local.bounds is None:
                raise NoGeometryError(occurrence.part_code)
            bounds = transformed_bounds(
                local.points,
                position=occurrence.position,
                matrix=occurrence.matrix,
            )
            if bounds is None:
                raise NoGeometryError(occurrence.part_code)
        except PartError as error:
            diagnostic = Diagnostic(
                line_number=occurrence.source_line,
                message=error.message,
                severity=Severity.WARNING,
                code=DiagnosticCode.GEOMETRY_INCOMPLETE,
                section=occurrence.source_model.name or None,
                offending_value=occurrence.part_code,
                cause=error,
            )
            skipped.append(
                SkippedOccurrenceGeometry(
                    attribution=attribution,
                    diagnostic=diagnostic,
                ),
            )
            diagnostics.append(diagnostic)
            continue
        geometry = OccurrenceGeometry(
            attribution=attribution,
            local=local,
            bounds=bounds,
            studs=tuple(
                StudReference(
                    name=stud.name,
                    description=stud.description,
                    position=occurrence.position + occurrence.matrix * stud.position,
                    up=occurrence.matrix * stud.up,
                )
                for stud in local.studs
            ),
        )
        inspected.append(geometry)
        world_bounds.add_box(bounds)
    return ModelInspection(
        bounds=world_bounds.box(),
        occurrences=tuple(inspected),
        skipped_geometry=tuple(skipped),
        diagnostics=tuple(diagnostics),
        occurrence_count=len(all_occurrences),
    )


def transformed_bounds(
    points: Iterable[Vector],
    *,
    position: Vector,
    matrix: Matrix,
) -> BoundingBox | None:
    """Return the exact world AABB after transforming expanded points."""
    bounds = _BoundsAccumulator()
    for point in points:
        bounds.add(position + matrix * point)
    return bounds.box()


def occurrence_bounds(occurrence: ModelOccurrence, parts: Parts) -> BoundingBox:
    """Return exact transformed drawable bounds for one occurrence."""
    geometry = parts.geometry(occurrence.part_code)
    if geometry.bounds is None:
        raise NoGeometryError(occurrence.part_code)
    bounds = transformed_bounds(
        geometry.points,
        position=occurrence.position,
        matrix=occurrence.matrix,
    )
    if bounds is None:
        raise NoGeometryError(occurrence.part_code)
    return bounds


def bounds_gap(left: BoundingBox, right: BoundingBox) -> BoundsGap:
    """Return axis and Euclidean distance between two AABBs."""
    axes = Vector(
        _axis_gap(left.min.x, left.max.x, right.min.x, right.max.x),
        _axis_gap(left.min.y, left.max.y, right.min.y, right.max.y),
        _axis_gap(left.min.z, left.max.z, right.min.z, right.max.z),
    )
    return BoundsGap(
        axes=axes,
        distance=math.sqrt(axes.x**2 + axes.y**2 + axes.z**2),
    )


def _axis_gap(
    left_min: float, left_max: float, right_min: float, right_max: float
) -> float:
    return float(max(left_min - right_max, right_min - left_max, 0.0))


def _not_installed_later(
    subject: OccurrenceGeometry,
    candidate: OccurrenceGeometry,
) -> bool:
    subject_page = subject.attribution.installation_page
    candidate_page = candidate.attribution.installation_page
    return (
        subject_page is None or candidate_page is None or candidate_page <= subject_page
    )


def _box_contains(box: BoundingBox, point: Vector, tolerance: float) -> bool:
    return (
        box.min.x - tolerance <= point.x <= box.max.x + tolerance
        and box.min.y - tolerance <= point.y <= box.max.y + tolerance
        and box.min.z - tolerance <= point.z <= box.max.z + tolerance
    )


def _attribution(
    occurrence: ModelOccurrence,
    *,
    index: int,
    piece_pages: dict[int, int],
) -> OccurrenceAttribution:
    return OccurrenceAttribution(
        index=index,
        occurrence=occurrence,
        model_path=tuple(item.model.name for item in occurrence.path),
        reference_path=tuple(item.piece.reference for item in occurrence.path),
        source_line_path=tuple(item.source_line for item in occurrence.path),
        local_step_path=tuple(item.local_step for item in occurrence.path),
        effective_step_path=tuple(item.effective_step for item in occurrence.path),
        page_path=tuple(piece_pages.get(id(item.piece)) for item in occurrence.path),
    )


def _piece_pages(model: Model, *, marker_prefix: str) -> dict[int, int]:
    if not marker_prefix:
        return {}
    pages: dict[int, int] = {}
    for section in (model, *model.submodels.values()):
        page: int | None = None
        for obj in section.objects:
            if isinstance(obj, Comment):
                if (
                    marker_page := _marker_page(obj.text, prefix=marker_prefix)
                ) is not None:
                    page = marker_page
            elif page is not None and isinstance(obj, Piece):
                pages[id(obj)] = page
    return pages


def _marker_page(text: str, *, prefix: str) -> int | None:
    candidate = text.strip()
    if not candidate.casefold().startswith(prefix.casefold()):
        return None
    try:
        page = int(candidate[len(prefix) :].strip())
    except ValueError:
        return None
    return page if page >= 0 else None


class _BoundsAccumulator:
    def __init__(self) -> None:
        self._min: Vector | None = None
        self._max: Vector | None = None

    def add(self, point: Vector) -> None:
        if self._min is None or self._max is None:
            self._min = point.copy()
            self._max = point.copy()
            return
        self._min.x = min(self._min.x, point.x)
        self._min.y = min(self._min.y, point.y)
        self._min.z = min(self._min.z, point.z)
        self._max.x = max(self._max.x, point.x)
        self._max.y = max(self._max.y, point.y)
        self._max.z = max(self._max.z, point.z)

    def add_box(self, box: BoundingBox) -> None:
        self.add(box.min)
        self.add(box.max)

    def box(self) -> BoundingBox | None:
        if self._min is None or self._max is None:
            return None
        return BoundingBox(min=self._min.copy(), max=self._max.copy())


__all__ = [
    "DEFAULT_PAGE_MARKER_PREFIX",
    "BoundsGap",
    "ModelInspection",
    "OccurrenceAttribution",
    "OccurrenceContact",
    "OccurrenceGeometry",
    "SkippedOccurrenceGeometry",
    "StudContact",
    "bounds_gap",
    "inspect_model",
    "occurrence_bounds",
    "transformed_bounds",
]
