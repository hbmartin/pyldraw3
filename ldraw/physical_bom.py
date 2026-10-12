"""Qualified physical inventories built from shared definition resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ldraw.bom import BomRow, _count_occurrences
from ldraw.coverage import Coverage
from ldraw.diagnostics import Diagnostic, Severity
from ldraw.model import ModelOccurrence
from ldraw.resolution import DocumentResolver

if TYPE_CHECKING:
    from ldraw.model import Model
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class BomReport:
    """Known physical counts with unresolved contents and explicit qualification."""

    rows: tuple[BomRow, ...]
    diagnostics: tuple[Diagnostic, ...]
    unresolved_contents: tuple[str, ...]
    coverage: Coverage
    provisional_rows: tuple[str, ...]
    processed_occurrences: int
    total_occurrences: int | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full report; legacy rows-only exports remain separate."""
        return {
            "rows": [row.to_dict() for row in self.rows],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "unresolved_contents": list(self.unresolved_contents),
            "coverage": self.coverage.value,
            "provisional_rows": list(self.provisional_rows),
            "processed_occurrences": self.processed_occurrences,
            "total_occurrences": self.total_occurrences,
        }


def bom_report(
    model: Model, *, parts: Parts | None = None, occurrence_budget: int | None = None
) -> BomReport:
    """Expand shortcuts and aliases, stop at parts, and retain known partial counts."""
    if occurrence_budget is not None and occurrence_budget < 0:
        message = "occurrence_budget must be non-negative"
        raise ValueError(message)
    resolver = DocumentResolver(model, parts)
    occurrences: list[ModelOccurrence] = []
    exhausted = False
    for event in resolver.events():
        if not isinstance(event, ModelOccurrence):
            continue
        if occurrence_budget is not None and len(occurrences) >= occurrence_budget:
            exhausted = True
            resolver.diagnostics.append(
                Diagnostic(
                    code="analysis.occurrence_budget",
                    severity=Severity.WARNING,
                    message=(
                        f"Stopped after {len(occurrences)} physical occurrences; "
                        "total unknown"
                    ),
                )
            )
            break
        occurrences.append(event)
    rows = tuple(_count_occurrences(occurrences=occurrences, parts=resolver.parts))
    incomplete = exhausted or bool(resolver.provisional or resolver.unresolved)
    coverage = Coverage.PARTIAL if incomplete else Coverage.COMPLETE
    if incomplete and not rows:
        coverage = Coverage.UNAVAILABLE
    return BomReport(
        rows=rows,
        diagnostics=tuple(resolver.diagnostics),
        unresolved_contents=tuple(dict.fromkeys(resolver.unresolved)),
        coverage=coverage,
        provisional_rows=tuple(sorted(resolver.provisional)),
        processed_occurrences=len(occurrences),
        total_occurrences=None
        if exhausted or resolver.unresolved
        else len(occurrences),
    )
