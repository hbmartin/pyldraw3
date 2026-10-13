"""Document-local reference targets shared by instruction consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    import ldraw.model as _model
    from ldraw import _model_validation
    from ldraw.part import ParsedObject
    from ldraw.pieces import Piece


def _new_context() -> _model_validation.ModelValidationContext:
    """Construct reference caches after the core model modules are initialized."""
    from ldraw._model_validation import ModelValidationContext  # noqa: PLC0415 - runtime cycle

    return ModelValidationContext()


@dataclass(slots=True)
class InstructionResolution:
    """Retain resolver results for the lifetime of one instruction document."""

    root: _model.Model
    context: _model_validation.ModelValidationContext = field(
        default_factory=_new_context
    )

    def resolve(self, piece: Piece) -> _model.Model | None:
        """Resolve each source placement against the original root once."""
        return self.context.resolve(root=self.root, piece=piece)

    def expansion(
        self, *, source: _model.Model, objects: Iterable[ParsedObject], expand: bool
    ) -> _model.Model:
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
