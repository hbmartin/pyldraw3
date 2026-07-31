"""Reusable one-pass analysis over materialized model occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.bom import BomRow, bill_of_materials
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.model_summary import ModelSummary

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


def analyze_model(
    model: Model,
    *,
    parts: Parts | None = None,
    diagnostics: Iterable[Diagnostic] = (),
) -> ModelAnalysis:
    """Traverse leaf occurrences once and reuse them for all derived views."""
    occurrences = tuple(model.iter_occurrences(include_steps=True))
    summary = ModelSummary.from_occurrences(occurrences, parts)
    combined = list(diagnostics)
    combined.extend(
        Diagnostic(
            line_number=skipped.source_line,
            message=skipped.reason,
            severity=Severity.WARNING,
            code=DiagnosticCode.GEOMETRY_INCOMPLETE,
            section=skipped.source_model,
            offending_value=skipped.part,
        )
        for skipped in summary.skipped_geometry
    )
    inspection = None
    if parts is not None:
        from ldraw.inspection import inspect_model  # noqa: PLC0415

        inspection = inspect_model(model, parts, occurrences=occurrences)
        combined.extend(inspection.diagnostics)
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
