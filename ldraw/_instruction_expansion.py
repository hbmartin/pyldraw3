"""Step-local expansion models, imported after core model initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw.model import Model

if TYPE_CHECKING:
    from ldraw._instruction_resolution import InstructionResolution
    from ldraw.pieces import Piece


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
