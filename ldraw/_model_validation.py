"""Invocation-local source placements and reference resolution for comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ldraw.geometry import Matrix, Vector
    from ldraw.model import Model
    from ldraw.pieces import Piece


@dataclass(slots=True)
class ModelValidationContext:
    """Share analysis within one load/compare operation, never across mutations."""

    placements: dict[Piece, tuple[Vector, Matrix]] = field(default_factory=dict)
    targets: dict[Piece, Model | None] = field(default_factory=dict)

    def resolve(self, *, root: Model, piece: Piece) -> Model | None:
        """Resolve a source reference once against this operation's root table."""
        if piece not in self.targets:
            self.targets[piece] = root.submodel_for(piece)
        return self.targets[piece]
