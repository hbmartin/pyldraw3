"""Document-local reference targets shared by instruction consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._model_validation import ModelValidationContext

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.model import Model
    from ldraw.part import ParsedObject
    from ldraw.pieces import Piece


@dataclass(slots=True)
class InstructionResolution:
    """Retain resolver results for the lifetime of one instruction document."""

    root: Model
    context: ModelValidationContext = field(default_factory=ModelValidationContext)

    def resolve(self, piece: Piece) -> Model | None:
        """Resolve each source placement against the original root once."""
        return self.context.resolve(root=self.root, piece=piece)

    def expansion(
        self, *, source: Model, objects: Iterable[ParsedObject], expand: bool
    ) -> Model:
        """Build a step-local model using the document's authoritative targets."""
        from ldraw._instruction_expansion import _InstructionExpansion  # noqa: PLC0415 - runtime cycle

        return _InstructionExpansion(
            name=source.name,
            objects=list(objects),
            submodels=self.root.submodels,
            _source_lines=source._source_lines,  # noqa: SLF001
            _object_source_lines=source._object_source_lines,  # noqa: SLF001
            resolution=self,
            expand=expand,
        )
