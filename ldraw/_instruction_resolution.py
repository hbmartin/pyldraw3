"""Document-local reference targets shared by instruction consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._model_validation import ModelValidationContext
from ldraw.model import Model

if TYPE_CHECKING:
    from collections.abc import Iterable

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
        return _InstructionExpansion(
            name=source.name,
            objects=list(objects),
            submodels=self.root.submodels,
            _source_lines=source._source_lines,  # noqa: SLF001
            _object_source_lines=source._object_source_lines,  # noqa: SLF001
            resolution=self,
            expand=expand,
        )


@dataclass(slots=True, eq=False)
class _InstructionExpansion(Model):
    resolution: InstructionResolution = field(kw_only=True, repr=False)
    expand: bool = field(kw_only=True, repr=False)

    def submodel_for(self, piece: Piece) -> Model | None:
        """Expand instruction sections while keeping embedded DAT parts as leaves."""
        if not self.expand:
            return None
        target = self.resolution.resolve(piece)
        return (
            target
            if target is not None and not target.name.casefold().endswith(".dat")
            else None
        )
