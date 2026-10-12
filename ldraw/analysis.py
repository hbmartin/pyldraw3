"""Reusable one-pass analysis over materialized model occurrences."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ldraw.bom import BomRow, bill_of_materials
from ldraw.coverage import Coverage
from ldraw.diagnostics import Diagnostic, Severity, _merge_diagnostics
from ldraw.model import ModelOccurrence
from ldraw.model_summary import ModelSummary
from ldraw.resolution import DocumentResolver, RawGeometry

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.inspection import ModelInspection
    from ldraw.instructions import InstructionStep
    from ldraw.model import Model, ModelOccurrence
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class ModelAnalysis:
    """Occurrences, statistics, BOM, steps, and diagnostics for one model."""

    occurrences: tuple[ModelOccurrence, ...]
    summary: ModelSummary
    bom: tuple[BomRow, ...]
    instruction_steps: tuple[InstructionStep, ...]
    diagnostics: tuple[Diagnostic, ...]
    inspection: ModelInspection | None = None
    processed_occurrences: int = 0
    total_occurrences: int | None = None
    bom_coverage: Coverage = Coverage.COMPLETE

    @property
    def geometry_coverage(self) -> Coverage:
        """Report inspection coverage or qualify bounds built without a library."""
        if self.inspection is not None:
            return self.inspection.geometry_coverage
        if self.occurrences or self.total_occurrences is None:
            return Coverage.PARTIAL if self.summary.bounds else Coverage.UNAVAILABLE
        return Coverage.COMPLETE

    @property
    def connection_coverage(self) -> Coverage:
        """Connections require inspection evidence independently of geometry."""
        return (
            self.inspection.connection_coverage
            if self.inspection
            else Coverage.UNAVAILABLE
        )


def analyze_model(
    model: Model,
    *,
    parts: Parts | None = None,
    diagnostics: Iterable[Diagnostic] = (),
    occurrence_budget: int | None = None,
    feature_pair_budget: int | None = None,
) -> ModelAnalysis:
    """Traverse leaf occurrences once and reuse them for all derived views.

    Cyclic submodel references (possible in tolerantly-loaded models) are
    skipped rather than raising; each skipped reference surfaces as an
    ``MPD_CYCLE`` diagnostic unless an equal one was already passed in via
    ``diagnostics``.
    """
    if occurrence_budget is not None and occurrence_budget < 0:
        message = "occurrence_budget must be non-negative"
        raise ValueError(message)
    resolver = DocumentResolver(model, parts)
    physical: list[ModelOccurrence] = []
    raw: list[RawGeometry] = []
    exhausted = False
    for event in resolver.events():
        if isinstance(event, RawGeometry):
            raw.append(event)
        elif occurrence_budget is not None and len(physical) >= occurrence_budget:
            exhausted = True
            resolver.diagnostics.append(
                Diagnostic(
                    code="analysis.occurrence_budget",
                    severity=Severity.WARNING,
                    message=(
                        f"Stopped after {len(physical)} physical occurrences; "
                        "total unknown"
                    ),
                )
            )
            break
        else:
            physical.append(event)
    occurrences = tuple(physical)
    total = None if exhausted or resolver.unresolved else len(occurrences)
    combined = _merge_diagnostics(diagnostics, resolver.diagnostics)
    inspection: ModelInspection | None = None
    if parts is not None:
        from ldraw.inspection import inspect_model  # noqa: PLC0415

        inspection = inspect_model(
            model,
            resolver.parts or parts,
            occurrences=occurrences,
            raw_geometry=raw,
            feature_pair_budget=feature_pair_budget,
        )
        inspection = replace(
            inspection,
            budget_exhausted=exhausted,
            occurrence_total=total,
            diagnostics=_merge_diagnostics(
                resolver.diagnostics, inspection.diagnostics
            ),
        )
        # The inspection already transformed every occurrence's expanded
        # geometry and recorded per-occurrence skip diagnostics, so the
        # summary reuses its bounds and the diagnostics are emitted once.
        summary = ModelSummary.from_inspection(inspection)
        combined = _merge_diagnostics(combined, inspection.diagnostics)
    else:
        summary = ModelSummary.from_occurrences(occurrences, parts, raw_geometry=raw)
    steps = () if exhausted else model.instruction_document(parts=parts).root.steps
    return ModelAnalysis(
        occurrences=occurrences,
        summary=summary,
        bom=tuple(bill_of_materials(parts=resolver.parts, occurrences=occurrences)),
        instruction_steps=steps,
        diagnostics=tuple(combined),
        inspection=inspection,
        processed_occurrences=len(occurrences),
        total_occurrences=total,
        bom_coverage=_bom_coverage(
            resolver, exhausted=exhausted, processed=len(occurrences)
        ),
    )


def _bom_coverage(
    resolver: DocumentResolver, *, exhausted: bool, processed: int
) -> Coverage:
    incomplete = exhausted or resolver.unresolved or resolver.provisional
    if incomplete:
        return Coverage.PARTIAL if processed else Coverage.UNAVAILABLE
    return Coverage.COMPLETE


__all__ = ["ModelAnalysis", "analyze_model"]
