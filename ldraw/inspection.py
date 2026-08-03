"""Exact world geometry, provenance, and broad-phase model inspection."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import product
from typing import TYPE_CHECKING

from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionKind,
    ConnectionResidual,
    ConnectionSource,
    ConnectionStatus,
    SnapTransform,
    angular_alignment_within,
    connection_residual,
    connections_compatible,
    snap_transform,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError, PartError
from ldraw.geometry import Vector
from ldraw.lines import Comment
from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

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
    connections: tuple[ConnectionFeature, ...] = ()

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
    """Compatibility projection of one strict stud/receptacle feature match."""

    stud_occurrence: OccurrenceGeometry
    supported_occurrence: OccurrenceGeometry
    stud: StudReference
    position: Vector
    stud_feature: ConnectionFeature | None = None
    receptacle_feature: ConnectionFeature | None = None
    residual: ConnectionResidual | None = None


@dataclass(frozen=True, slots=True)
class ConnectionContact:
    """Two placed connection features that are aligned and overlapping."""

    first_occurrence: OccurrenceGeometry
    second_occurrence: OccurrenceGeometry
    first: ConnectionFeature
    second: ConnectionFeature
    residual: ConnectionResidual
    status: ConnectionStatus = ConnectionStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class ConnectionGraphEdge:
    """One typed feature contact between two occurrence nodes."""

    first: int
    second: int
    first_feature_id: str
    second_feature_id: str
    status: ConnectionStatus
    residual: ConnectionResidual


@dataclass(frozen=True, slots=True)
class ConnectionMultigraph:
    """Immutable occurrence multigraph retaining parallel feature edges."""

    nodes: tuple[int, ...]
    edges: tuple[ConnectionGraphEdge, ...]


@dataclass(frozen=True, slots=True)
class ConnectionGraphs:
    """Confirmed and optimistic views of one inspection's connectivity."""

    confirmed: ConnectionMultigraph
    optimistic: ConnectionMultigraph


@dataclass(frozen=True, slots=True)
class SnapCandidate:
    """Compatible feature pair and the resulting moving-part placement."""

    moving_occurrence: OccurrenceGeometry
    fixed_occurrence: OccurrenceGeometry
    moving: ConnectionFeature
    fixed: ConnectionFeature
    transform: SnapTransform
    residual: ConnectionResidual


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
        """Return strict stud matches as the historical stud-contact view."""
        if tolerance < 0:
            message = "tolerance must be non-negative"
            raise ValueError(message)
        if probe_distance <= 0:
            message = "probe_distance must be positive"
            raise ValueError(message)
        contacts = self.connection_contacts(tolerance=tolerance)
        projected: list[StudContact] = []
        for contact in contacts:
            if (
                contact.residual.penetration is not None
                and contact.residual.penetration < probe_distance
            ):
                continue
            if contact.first.kind is ConnectionKind.STUD:
                stud_occurrence = contact.first_occurrence
                supported_occurrence = contact.second_occurrence
                stud_feature = contact.first
                receptacle = contact.second
            elif contact.second.kind is ConnectionKind.STUD:
                stud_occurrence = contact.second_occurrence
                supported_occurrence = contact.first_occurrence
                stud_feature = contact.second
                receptacle = contact.first
            else:
                continue
            if (stud := _stud_evidence(stud_occurrence, stud_feature)) is None:
                continue
            projected.append(
                StudContact(
                    stud_occurrence=stud_occurrence,
                    supported_occurrence=supported_occurrence,
                    stud=stud,
                    position=stud_feature.position.copy(),
                    stud_feature=stud_feature,
                    receptacle_feature=receptacle,
                    residual=contact.residual,
                ),
            )
        return tuple(projected)

    def connection_contacts(
        self,
        *,
        tolerance: float = 0.25,
        angular_tolerance: float = 2.0,
    ) -> tuple[ConnectionContact, ...]:
        """Return compatible connection features already mated in the model."""
        if tolerance < 0:
            message = "tolerance must be non-negative"
            raise ValueError(message)
        if angular_tolerance < 0:
            message = "angular_tolerance must be non-negative"
            raise ValueError(message)
        contacts: list[ConnectionContact] = []
        for first_index, second_index in _candidate_occurrence_pairs(
            self.occurrences,
            tolerance=tolerance,
        ):
            contacts.extend(
                _paired_contacts(
                    self.occurrences[first_index],
                    self.occurrences[second_index],
                    tolerance=tolerance,
                    angular_tolerance=angular_tolerance,
                ),
            )
        return tuple(
            sorted(
                contacts,
                key=lambda contact: (
                    contact.first_occurrence.index,
                    contact.second_occurrence.index,
                    contact.first.feature_id or "",
                    contact.second.feature_id or "",
                ),
            ),
        )

    def connection_graphs(
        self,
        *,
        tolerance: float = 0.25,
        angular_tolerance: float = 2.0,
    ) -> ConnectionGraphs:
        """Return confirmed and heuristic-inclusive occurrence multigraphs."""
        nodes = tuple(range(self.occurrence_count))
        optimistic_edges = tuple(
            ConnectionGraphEdge(
                first=contact.first_occurrence.index,
                second=contact.second_occurrence.index,
                first_feature_id=contact.first.feature_id or "",
                second_feature_id=contact.second.feature_id or "",
                status=contact.status,
                residual=contact.residual,
            )
            for contact in self.connection_contacts(
                tolerance=tolerance,
                angular_tolerance=angular_tolerance,
            )
        )
        confirmed_edges = tuple(
            edge
            for edge in optimistic_edges
            if edge.status is ConnectionStatus.CONFIRMED
        )
        return ConnectionGraphs(
            confirmed=ConnectionMultigraph(nodes=nodes, edges=confirmed_edges),
            optimistic=ConnectionMultigraph(nodes=nodes, edges=optimistic_edges),
        )

    def snap_candidates(
        self,
        moving: OccurrenceGeometry | int,
        *,
        fixed: OccurrenceGeometry | int | None = None,
        limit: int | None = None,
    ) -> tuple[SnapCandidate, ...]:
        """Return ranked placements for mating a moving occurrence's features.

        ``moving`` and ``fixed`` accept either an occurrence geometry or its
        stable inspection index. When ``fixed`` is omitted, every other
        occurrence is considered.
        """
        if limit is not None and limit < 0:
            message = "limit must be non-negative"
            raise ValueError(message)
        moving_occurrence = self._resolve_occurrence(moving)
        fixed_occurrences = (
            (self._resolve_occurrence(fixed),)
            if fixed is not None
            else tuple(
                occurrence
                for occurrence in self.occurrences
                if occurrence.index != moving_occurrence.index
            )
        )
        candidates: list[SnapCandidate] = []
        for fixed_occurrence in fixed_occurrences:
            if fixed_occurrence.index == moving_occurrence.index:
                continue
            for moving_feature in moving_occurrence.connections:
                for fixed_feature in fixed_occurrence.connections:
                    if not connections_compatible(moving_feature, fixed_feature):
                        continue
                    residual = connection_residual(moving_feature, fixed_feature)
                    delta = snap_transform(moving_feature, fixed_feature)
                    candidates.append(
                        SnapCandidate(
                            moving_occurrence=moving_occurrence,
                            fixed_occurrence=fixed_occurrence,
                            moving=moving_feature,
                            fixed=fixed_feature,
                            transform=SnapTransform(
                                position=(
                                    delta.position
                                    + delta.matrix
                                    * moving_occurrence.occurrence.position
                                ),
                                matrix=(
                                    delta.matrix * moving_occurrence.occurrence.matrix
                                ),
                            ),
                            residual=residual,
                        ),
                    )
        ranked = tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.residual.distance + candidate.residual.axial_gap,
                    -candidate.residual.alignment,
                    -candidate.residual.roll_alignment,
                    candidate.fixed_occurrence.index,
                    candidate.moving.feature_id or "",
                    candidate.fixed.feature_id or "",
                ),
            ),
        )
        return ranked if limit is None else ranked[:limit]

    def _resolve_occurrence(
        self,
        value: OccurrenceGeometry | int,
    ) -> OccurrenceGeometry:
        if isinstance(value, OccurrenceGeometry):
            if value not in self.occurrences:
                message = "occurrence does not belong to this inspection"
                raise ValueError(message)
            return value
        if not isinstance(value, int):
            message = "occurrence must be an OccurrenceGeometry or integer index"
            raise TypeError(message)
        try:
            return next(
                occurrence
                for occurrence in self.occurrences
                if occurrence.index == value
            )
        except StopIteration:
            message = f"inspection has no occurrence with index {value}"
            raise IndexError(message) from None

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
            connections=tuple(
                feature.transformed(
                    position=occurrence.position,
                    matrix=occurrence.matrix,
                )
                for feature in local.connections
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


def _candidate_occurrence_pairs(
    occurrences: tuple[OccurrenceGeometry, ...],
    *,
    tolerance: float,
) -> tuple[tuple[int, int], ...]:
    """Use a deterministic spatial hash to find overlapping feature reaches."""
    cell_size = 20.0
    cells: dict[tuple[int, int, int], list[int]] = {}
    for index, occurrence in enumerate(occurrences):
        for feature in occurrence.connections:
            reach = _feature_reach(
                occurrence,
                feature,
                tolerance=tolerance,
            )
            ranges = tuple(
                range(
                    math.floor(low / cell_size),
                    math.floor(high / cell_size) + 1,
                )
                for low, high in zip(
                    (reach.min.x, reach.min.y, reach.min.z),
                    (reach.max.x, reach.max.y, reach.max.z),
                    strict=True,
                )
            )
            for cell in product(*ranges):
                members = cells.setdefault(cell, [])
                if not members or members[-1] != index:
                    members.append(index)
    candidates: set[tuple[int, int]] = set()
    for members in cells.values():
        for offset, first in enumerate(members):
            candidates.update(
                (first, second) if first < second else (second, first)
                for second in members[offset + 1 :]
                if first != second
            )
    return tuple(sorted(candidates))


def _feature_reach(
    occurrence: OccurrenceGeometry,
    feature: ConnectionFeature,
    *,
    tolerance: float,
) -> BoundingBox:
    margin = tolerance + feature.length / 2
    pad = Vector(margin, margin, margin)
    midpoint = feature.axial_midpoint
    reach = BoundingBox(min=midpoint - pad, max=midpoint + pad)
    if feature.kind not in {ConnectionKind.STUD, ConnectionKind.STUD_RECEPTACLE}:
        return reach
    return BoundingBox(
        min=Vector(
            min(reach.min.x, occurrence.bounds.min.x),
            min(reach.min.y, occurrence.bounds.min.y),
            min(reach.min.z, occurrence.bounds.min.z),
        ),
        max=Vector(
            max(reach.max.x, occurrence.bounds.max.x),
            max(reach.max.y, occurrence.bounds.max.y),
            max(reach.max.z, occurrence.bounds.max.z),
        ),
    )


def _paired_contacts(
    first_occurrence: OccurrenceGeometry,
    second_occurrence: OccurrenceGeometry,
    *,
    tolerance: float,
    angular_tolerance: float,
) -> Iterator[ConnectionContact]:
    yield from _strict_stud_contacts_between(
        first_occurrence,
        second_occurrence,
        tolerance=tolerance,
        angular_tolerance=angular_tolerance,
    )
    for first in first_occurrence.connections:
        for second in second_occurrence.connections:
            if first.kind in {
                ConnectionKind.STUD,
                ConnectionKind.STUD_RECEPTACLE,
            } or second.kind in {
                ConnectionKind.STUD,
                ConnectionKind.STUD_RECEPTACLE,
            }:
                continue
            if not connections_compatible(first, second):
                continue
            residual = connection_residual(first, second)
            if (
                residual.distance <= tolerance
                and residual.axial_gap <= tolerance
                and angular_alignment_within(residual.alignment, angular_tolerance)
                and angular_alignment_within(
                    residual.roll_alignment,
                    angular_tolerance,
                )
            ):
                yield ConnectionContact(
                    first_occurrence=first_occurrence,
                    second_occurrence=second_occurrence,
                    first=first,
                    second=second,
                    residual=residual,
                    status=_contact_status(first, second),
                )


def _strict_stud_contacts_between(
    first_occurrence: OccurrenceGeometry,
    second_occurrence: OccurrenceGeometry,
    *,
    tolerance: float,
    angular_tolerance: float,
) -> Iterator[ConnectionContact]:
    yield from _strict_stud_direction(
        first_occurrence,
        second_occurrence,
        first_is_stud=True,
        tolerance=tolerance,
        angular_tolerance=angular_tolerance,
    )
    yield from _strict_stud_direction(
        second_occurrence,
        first_occurrence,
        first_is_stud=False,
        tolerance=tolerance,
        angular_tolerance=angular_tolerance,
    )


def _strict_stud_direction(
    stud_occurrence: OccurrenceGeometry,
    receptacle_occurrence: OccurrenceGeometry,
    *,
    first_is_stud: bool,
    tolerance: float,
    angular_tolerance: float,
) -> Iterator[ConnectionContact]:
    studs = tuple(
        feature
        for feature in stud_occurrence.connections
        if feature.kind is ConnectionKind.STUD
    )
    receptacles = tuple(
        feature
        for feature in receptacle_occurrence.connections
        if feature.kind is ConnectionKind.STUD_RECEPTACLE
    )
    for stud in studs:
        ordered = sorted(
            receptacles,
            key=lambda feature: (
                abs(feature.position - stud.position),
                feature.feature_id or "",
                feature.name,
            ),
        )
        evidence = next(
            (
                (receptacle, entry_gap, penetration)
                for receptacle in ordered
                if connections_compatible(stud, receptacle)
                and angular_alignment_within(
                    -stud.axis.dot(receptacle.axis),
                    angular_tolerance,
                )
                and (
                    entry := _entry_face_residual(
                        stud,
                        receptacle_occurrence,
                        tolerance=tolerance,
                    )
                )
                is not None
                for entry_gap, penetration in (entry,)
            ),
            None,
        )
        if evidence is None:
            continue
        receptacle, entry_gap, penetration = evidence
        residual = replace(
            connection_residual(stud, receptacle),
            entry_face_gap=entry_gap,
            penetration=penetration,
        )
        yield ConnectionContact(
            first_occurrence=(
                stud_occurrence if first_is_stud else receptacle_occurrence
            ),
            second_occurrence=(
                receptacle_occurrence if first_is_stud else stud_occurrence
            ),
            first=stud if first_is_stud else receptacle,
            second=receptacle if first_is_stud else stud,
            residual=residual,
            status=_contact_status(stud, receptacle),
        )


def _entry_face_residual(
    stud: ConnectionFeature,
    candidate: OccurrenceGeometry,
    *,
    tolerance: float,
) -> tuple[float, float] | None:
    bounds = candidate.local.bounds
    if bounds is None or candidate.occurrence.matrix.is_singular():
        return None
    inverse = candidate.occurrence.matrix.inverse()
    point = inverse * (stud.position - candidate.occurrence.position)
    direction = inverse * stud.axis
    if not (length := abs(direction)):
        return None
    direction = direction / length
    coordinates = (point.x, point.y, point.z)
    vector = (direction.x, direction.y, direction.z)
    minimum = (bounds.min.x, bounds.min.y, bounds.min.z)
    maximum = (bounds.max.x, bounds.max.y, bounds.max.z)
    axis = max(range(3), key=lambda index: abs(vector[index]))
    component = vector[axis]
    if abs(component) < 1e-9:
        return None
    entry_face = minimum[axis] if component > 0 else maximum[axis]
    exit_face = maximum[axis] if component > 0 else minimum[axis]
    entry_distance = (entry_face - coordinates[axis]) / component
    penetration = (exit_face - coordinates[axis]) / component
    lateral = tuple(index for index in range(3) if index != axis)
    if not all(
        minimum[index] - tolerance <= coordinates[index] <= maximum[index] + tolerance
        for index in lateral
    ):
        return None
    if abs(entry_distance) > tolerance or penetration <= 0:
        return None
    return abs(entry_distance), penetration


def _stud_evidence(
    occurrence: OccurrenceGeometry,
    feature: ConnectionFeature,
) -> StudReference | None:
    candidates = tuple(
        stud
        for stud in occurrence.studs
        if not stud.is_receptacle and not stud.is_placeholder and abs(stud.up)
    )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda stud: (
            abs(stud.position - feature.position),
            stud.name,
        ),
    )


def _contact_status(
    first: ConnectionFeature,
    second: ConnectionFeature,
) -> ConnectionStatus:
    return (
        ConnectionStatus.POTENTIAL
        if ConnectionSource.HEURISTIC in {first.source, second.source}
        else ConnectionStatus.CONFIRMED
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
    "ConnectionContact",
    "ConnectionGraphEdge",
    "ConnectionGraphs",
    "ConnectionMultigraph",
    "ModelInspection",
    "OccurrenceAttribution",
    "OccurrenceContact",
    "OccurrenceGeometry",
    "SkippedOccurrenceGeometry",
    "SnapCandidate",
    "StudContact",
    "bounds_gap",
    "inspect_model",
    "occurrence_bounds",
    "transformed_bounds",
]
