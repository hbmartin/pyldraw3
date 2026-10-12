"""Incremental, explicitly qualified feature-pair searches."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import TYPE_CHECKING

from ldraw.connection_types import (
    ConnectionFeature,
    SnapTransform,
    connection_residual,
    connections_compatible,
    snap_transform,
)
from ldraw.coverage import Coverage
from ldraw.diagnostics import Diagnostic, Severity

if TYPE_CHECKING:
    from ldraw.inspection import (
        ConnectionContact,
        ModelInspection,
        OccurrenceGeometry,
        SnapCandidate,
    )


@dataclass(frozen=True, slots=True)
class SnapReport:
    """Candidates ranked over examined pairs, with a stated search coverage."""

    candidates: tuple[SnapCandidate, ...]
    examined_pairs: int
    total_pairs: int | None
    coverage: Coverage
    diagnostics: tuple[Diagnostic, ...] = ()
    unsupported_checks: tuple[str, ...] = ("collisions", "seating_rules", "joint_rules")
    geometry_coverage: Coverage = Coverage.UNAVAILABLE
    connection_coverage: Coverage = Coverage.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class ContactReport:
    """Completed contact checks and the limits of their coverage."""

    contacts: tuple[ConnectionContact, ...]
    examined_pairs: int
    total_pairs: int | None
    coverage: Coverage
    diagnostics: tuple[Diagnostic, ...] = ()
    unsupported_checks: tuple[str, ...] = ("seating_rules", "joint_rules", "rigidity")
    geometry_coverage: Coverage = Coverage.UNAVAILABLE
    connection_coverage: Coverage = Coverage.UNAVAILABLE


def _budget_diagnostic(examined: int, *, ranked: bool = False) -> Diagnostic:
    tail = "; candidate ranking covers examined pairs only" if ranked else ""
    return Diagnostic(
        code="analysis.feature_pair_budget",
        severity=Severity.WARNING,
        message=f"Feature-pair budget exhausted after {examined} pairs{tail}",
    )


def bounded_snap(
    inspection: ModelInspection,
    *,
    moving: OccurrenceGeometry | int,
    fixed: OccurrenceGeometry | int | None,
    limit: int | None,
    feature_pair_budget: int | None,
) -> SnapReport:
    """Examine a deterministic prefix without materializing the Cartesian product."""
    from ldraw.inspection import SnapCandidate  # noqa: PLC0415

    if (limit is not None and limit < 0) or (
        feature_pair_budget is not None and feature_pair_budget < 0
    ):
        message = "limit and feature_pair_budget must be non-negative"
        raise ValueError(message)
    subject = inspection._resolve_occurrence(moving)  # noqa: SLF001
    fixed_items = (
        (inspection._resolve_occurrence(fixed),)  # noqa: SLF001
        if fixed is not None
        else inspection.occurrences
    )
    fixed_items = tuple(item for item in fixed_items if item.index != subject.index)
    total = len(subject.connections) * sum(
        len(item.connections) for item in fixed_items
    )
    examined = 0
    candidates: list[SnapCandidate] = []
    for item in fixed_items:
        for first in subject.connections:
            for second in item.connections:
                if feature_pair_budget is not None and examined >= feature_pair_budget:
                    return _snap_result(
                        candidates,
                        examined=examined,
                        total=total,
                        limit=limit,
                        inspection=inspection,
                        global_scope=fixed is None,
                    )
                examined += 1
                if not connections_compatible(first, second):
                    continue
                delta = snap_transform(first, second)
                candidates.append(
                    SnapCandidate(
                        moving_occurrence=subject,
                        fixed_occurrence=item,
                        moving=first,
                        fixed=second,
                        transform=SnapTransform(
                            position=delta.position
                            + delta.matrix * subject.occurrence.position,
                            matrix=delta.matrix * subject.occurrence.matrix,
                        ),
                        residual=connection_residual(first, second),
                        contact_supported=_snap_contact_supported(
                            subject,
                            item,
                            moving=first,
                            fixed=second,
                            delta=delta,
                        ),
                    )
                )
    return _snap_result(
        candidates,
        examined=examined,
        total=total,
        limit=limit,
        inspection=inspection,
        global_scope=fixed is None,
    )


def _snap_result(  # noqa: PLR0913 - explicit search scope and presentation limits
    candidates: list[SnapCandidate],
    *,
    examined: int,
    total: int,
    limit: int | None,
    inspection: ModelInspection,
    global_scope: bool,
) -> SnapReport:
    candidates.sort(
        key=lambda item: (
            item.residual.distance + item.residual.axial_gap,
            -item.residual.alignment,
            -item.residual.roll_alignment,
            item.fixed_occurrence.index,
            item.moving.feature_id or "",
            item.fixed.feature_id or "",
        )
    )
    truncated = examined < total
    unknown = global_scope and inspection.occurrence_total is None
    partial = truncated or unknown
    diagnostics = list(inspection.diagnostics)
    if truncated:
        diagnostics.append(_budget_diagnostic(examined, ranked=True))
    if unknown:
        diagnostics.append(_scope_diagnostic())
    if unsupported := sum(not candidate.contact_supported for candidate in candidates):
        diagnostics.append(
            Diagnostic(
                code="connection.snap_unverified",
                severity=Severity.WARNING,
                message=(
                    f"{unsupported} candidate(s) did not establish contact "
                    "after application"
                ),
            )
        )
    return SnapReport(
        candidates=tuple(candidates if limit is None else candidates[:limit]),
        examined_pairs=examined,
        total_pairs=None if unknown else total,
        coverage=Coverage.PARTIAL if partial else Coverage.COMPLETE,
        diagnostics=tuple(diagnostics),
        geometry_coverage=inspection.geometry_coverage,
        connection_coverage=inspection.connection_coverage,
    )


def bounded_contacts(
    inspection: ModelInspection,
    *,
    feature_pair_budget: int,
    tolerance: float,
    angular_tolerance: float,
) -> ContactReport:
    """Check pairs incrementally and return completed contact evidence."""
    from ldraw.inspection import _paired_contacts  # noqa: PLC0415

    if feature_pair_budget < 0:
        message = "feature_pair_budget must be non-negative"
        raise ValueError(message)
    contacts: list[ConnectionContact] = []
    examined = 0
    for first, second in combinations(inspection.occurrences, 2):
        for left in first.connections:
            for right in second.connections:
                if examined >= feature_pair_budget:
                    return _contact_result(
                        inspection, contacts=contacts, examined=examined, truncated=True
                    )
                examined += 1
                contacts.extend(
                    _paired_contacts(
                        replace(first, connections=(left,)),
                        replace(second, connections=(right,)),
                        tolerance=tolerance,
                        angular_tolerance=angular_tolerance,
                    )
                )
    return _contact_result(
        inspection, contacts=contacts, examined=examined, truncated=False
    )


def _scope_diagnostic() -> Diagnostic:
    return Diagnostic(
        code="analysis.incomplete_pair_scope",
        severity=Severity.WARNING,
        message="Pair total is unknown; candidate ranking covers examined pairs only",
    )


def _contact_result(
    inspection: ModelInspection,
    *,
    contacts: list[ConnectionContact],
    examined: int,
    truncated: bool,
) -> ContactReport:
    unknown = inspection.occurrence_total is None
    diagnostics = list(inspection.diagnostics)
    if truncated:
        diagnostics.append(_budget_diagnostic(examined))
    if unknown:
        diagnostics.append(_scope_diagnostic())
    return ContactReport(
        contacts=tuple(contacts),
        examined_pairs=examined,
        total_pairs=None if truncated or unknown else examined,
        coverage=Coverage.PARTIAL if truncated or unknown else Coverage.COMPLETE,
        diagnostics=tuple(diagnostics),
        geometry_coverage=inspection.geometry_coverage,
        connection_coverage=inspection.connection_coverage,
    )


def _snap_contact_supported(
    subject: OccurrenceGeometry,
    target: OccurrenceGeometry,
    *,
    moving: ConnectionFeature,
    fixed: ConnectionFeature,
    delta: SnapTransform,
) -> bool:
    from ldraw.inspection import _paired_contacts, transformed_bounds  # noqa: PLC0415

    occurrence = replace(
        subject.occurrence,
        position=delta.position + delta.matrix * subject.occurrence.position,
        matrix=delta.matrix * subject.occurrence.matrix,
    )
    bounds = transformed_bounds(
        subject.local.points, position=occurrence.position, matrix=occurrence.matrix
    )
    if bounds is None:
        return False
    placed = replace(
        subject,
        attribution=replace(subject.attribution, occurrence=occurrence),
        bounds=bounds,
        connections=(moving.transformed(position=delta.position, matrix=delta.matrix),),
    )
    return bool(
        tuple(
            _paired_contacts(
                placed,
                replace(target, connections=(fixed,)),
                tolerance=0.25,
                angular_tolerance=2.0,
            )
        )
    )
