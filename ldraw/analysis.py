"""Reusable one-pass analysis over materialized model occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.bom import BomRow, bill_of_materials
from ldraw.model import _iter_occurrences_skip_cycles
from ldraw.model_summary import ModelSummary

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.diagnostics import Diagnostic
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


def analyze_model(
    model: Model,
    *,
    parts: Parts | None = None,
    diagnostics: Iterable[Diagnostic] = (),
) -> ModelAnalysis:
    """Traverse leaf occurrences once and reuse them for all derived views.

    Cyclic submodel references (possible in tolerantly-loaded models) are
    skipped rather than raising; each skipped reference surfaces as an
    ``MPD_CYCLE`` diagnostic unless an equal one was already passed in via
    ``diagnostics``.
    """
    cycle_diagnostics: list[Diagnostic] = []
    occurrences = tuple(
        _iter_occurrences_skip_cycles(
            model,
            include_steps=True,
            diagnostics=cycle_diagnostics,
        ),
    )
    combined = list(diagnostics)
    for cycle_diagnostic in cycle_diagnostics:
        if cycle_diagnostic not in combined:
            combined.append(cycle_diagnostic)
    inspection: ModelInspection | None = None
    if parts is not None:
        from ldraw.inspection import inspect_model  # noqa: PLC0415

        inspection = inspect_model(model, parts, occurrences=occurrences)
        # The inspection already transformed every occurrence's expanded
        # geometry and recorded per-occurrence skip diagnostics, so the
        # summary reuses its bounds and the diagnostics are emitted once.
        summary = ModelSummary.from_inspection(inspection)
        combined.extend(inspection.diagnostics)
    else:
        summary = ModelSummary.from_occurrences(occurrences, parts)
    document = model.instruction_document(parts=parts)
    return ModelAnalysis(
        occurrences=occurrences,
        summary=summary,
        bom=tuple(bill_of_materials(parts=parts, occurrences=occurrences)),
        instruction_steps=document.root.steps,
        diagnostics=tuple(combined),
        inspection=inspection,
    )


__all__ = ["ModelAnalysis", "analyze_model"]
