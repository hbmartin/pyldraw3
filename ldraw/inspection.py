"""Catalog-backed world geometry, attribution, and contact-gap inspection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


@dataclass(frozen=True, slots=True)
class OccurrenceAttribution:
    """Stable identity and source context for one expanded leaf occurrence."""

    index: int
    occurrence: ModelOccurrence
    model_path: tuple[str, ...]
    reference_path: tuple[str, ...]
    source_line_path: tuple[int | None, ...]
    step_path: tuple[int | None, ...]
    page_path: tuple[int | None, ...]

    @property
    def installation_page(self) -> int | None:
        """Page that places the outermost part or submodel reference."""
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
        """The placed leaf occurrence represented by this record."""
        return self.attribution.occurrence

    @property
    def index(self) -> int:
        """Zero-based traversal index, stable for unchanged model text."""
        return self.attribution.index


@dataclass(frozen=True, slots=True)
class SkippedOccurrenceGeometry:
    """An occurrence whose catalog geometry could not produce world bounds."""

    attribution: OccurrenceAttribution
    reason: str


@dataclass(frozen=True, slots=True)
class BoundsGap:
    """Non-negative AABB separation along each axis and in Euclidean space."""

    axes: Vector
    distance: float

    @property
    def intersects(self) -> bool:
        """Whether the two boxes overlap or touch on all three axes."""
        return self.distance == 0.0


@dataclass(frozen=True, slots=True)
class OccurrenceContact:
    """One occurrence and its nearest AABB neighbour."""

    subject: OccurrenceGeometry
    nearest: OccurrenceGeometry
    gap: BoundsGap


@dataclass(frozen=True, slots=True)
class StudContact:
    """A stud whose base and protrusion direction contact another part's AABB."""

    stud_occurrence: OccurrenceGeometry
    supported_occurrence: OccurrenceGeometry
    stud: StudReference
    position: Vector


@dataclass(frozen=True, slots=True)
class ModelInspection:
    """Exact world bounds and attribution for all resolvable model occurrences."""

    bounds: BoundingBox | None
    occurrences: tuple[OccurrenceGeometry, ...]
    skipped_geometry: tuple[SkippedOccurrenceGeometry, ...]
    occurrence_count: int

    def stud_contacts(
        self,
        *,
        tolerance: float = 0.1,
        probe_distance: float = 0.1,
    ) -> tuple[StudContact, ...]:
        """Return protruding studs that meet another occurrence's AABB.

        A contact requires the stud base and a short probe along its transformed
        protrusion axis to fall inside the other occurrence's exact world AABB.
        This recognizes ordinary stacked and sideways-stud placements without
        assuming underside tubes are concentric with studs. It remains a
        broad-phase contact heuristic, not proof of a legal LEGO connection.
        """
        if tolerance < 0:
            msg = "tolerance must be non-negative"
            raise ValueError(msg)
        if probe_distance <= 0:
            msg = "probe_distance must be positive"
            raise ValueError(msg)

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
        """Return occurrences farther than ``minimum_gap`` from every peer.

        This is a deterministic broad-phase diagnostic over exact transformed
        axis-aligned bounds, not proof of a legal LEGO connection. With
        ``chronological=True``, a subject whose installation page is known
        ignores neighbours installed on a later known page. Occurrences on the
        same page remain peers so an off-model subassembly can be checked as a
        unit.
        """
        if minimum_gap < 0:
            msg = "minimum_gap must be non-negative"
            raise ValueError(msg)

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
    page_marker_prefix: str = DEFAULT_PAGE_MARKER_PREFIX,
) -> ModelInspection:
    """Inspect every leaf occurrence using recursively expanded part geometry.

    Page attribution follows comments such as ``0 // PDF_PAGE 149``. The
    prefix is configurable for generators which use a different comment
    convention. Repeated references to one submodel receive distinct traversal
    indices and root-to-leaf paths even though they share source piece objects.
    """
    piece_pages = _piece_pages(model, marker_prefix=page_marker_prefix)
    world_bounds = _BoundsAccumulator()
    inspected: list[OccurrenceGeometry] = []
    skipped: list[SkippedOccurrenceGeometry] = []
    occurrences = tuple(model.iter_occurrences(include_steps=True))
    for index, occurrence in enumerate(occurrences):
        attribution = _attribution(
            occurrence,
            index=index,
            piece_pages=piece_pages,
        )
        try:
            local = parts.geometry(occurrence.part_code)
            if local.bounds is None:
                raise NoGeometryError(occurrence.part_code)
            bounds = transformed_bounds(
                local.points,
                position=occurrence.position,
                matrix=occurrence.matrix,
            )
            if bounds is None:  # pragma: no cover - guarded by local.bounds
                raise NoGeometryError(occurrence.part_code)
        except PartError as error:
            skipped.append(
                SkippedOccurrenceGeometry(
                    attribution=attribution,
                    reason=error.message,
                ),
            )
            continue
        geometry = OccurrenceGeometry(
            attribution=attribution,
            local=local,
            bounds=bounds,
            studs=tuple(
                StudReference(
                    name=stud.name,
                    description=stud.description,
                    position=(occurrence.position + occurrence.matrix * stud.position),
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
        occurrence_count=len(occurrences),
    )


def transformed_bounds(
    points: Iterable[Vector],
    *,
    position: Vector,
    matrix: Matrix,
) -> BoundingBox | None:
    """Return exact world AABB after transforming expanded drawable points."""
    bounds = _BoundsAccumulator()
    for point in points:
        bounds.add(position + matrix * point)
    return bounds.box()


def occurrence_bounds(occurrence: ModelOccurrence, parts: Parts) -> BoundingBox:
    """Return exact transformed drawable bounds for one model occurrence."""
    geometry = parts.geometry(occurrence.part_code)
    if geometry.bounds is None:
        raise NoGeometryError(occurrence.part_code)
    bounds = transformed_bounds(
        geometry.points,
        position=occurrence.position,
        matrix=occurrence.matrix,
    )
    if bounds is None:  # pragma: no cover - guarded by geometry.bounds
        raise NoGeometryError(occurrence.part_code)
    return bounds


def bounds_gap(left: BoundingBox, right: BoundingBox) -> BoundsGap:
    """Return the non-negative axis and Euclidean gap between two AABBs."""
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
    left_min: float,
    left_max: float,
    right_min: float,
    right_max: float,
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
        step_path=tuple(item.step for item in occurrence.path),
        page_path=tuple(piece_pages.get(id(item.piece)) for item in occurrence.path),
    )


def _piece_pages(model: Model, *, marker_prefix: str) -> dict[int, int]:
    if not marker_prefix:
        return {}
    pages: dict[int, int] = {}
    sections = (model, *model.submodels.values())
    for section in sections:
        page: int | None = None
        for obj in section.objects:
            if isinstance(obj, Comment):
                marker_page = _marker_page(obj.text, prefix=marker_prefix)
                if marker_page is not None:
                    page = marker_page
            elif page is not None and isinstance(obj, Piece):
                pages[id(obj)] = page
    return pages


def _marker_page(text: str, *, prefix: str) -> int | None:
    candidate = text.strip()
    if not candidate.casefold().startswith(prefix.casefold()):
        return None
    value = candidate[len(prefix) :].strip()
    try:
        page = int(value)
    except ValueError:
        return None
    return page if page >= 0 else None


class _BoundsAccumulator:
    """Fold points or boxes into an axis-aligned bounding box."""

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
