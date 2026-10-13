"""Invocation-local source placements and reference resolution for comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ldraw.geometry import Matrix, Vector
    from ldraw.model import Model
    from ldraw.pieces import Piece
    from ldraw.validation import _NumericAnalysis


@dataclass(slots=True)
class ModelValidationContext:
    """Share analysis within one load/compare operation, never across mutations."""

    placements: dict[Piece, tuple[Vector, Matrix]] = field(default_factory=dict)
    targets: dict[Piece, Model | None] = field(default_factory=dict)
    _root: Model | None = field(default=None, init=False, repr=False)
    _validated_scopes: set[bool] = field(default_factory=set, init=False, repr=False)

    def bind(self, root: Model) -> None:
        """Keep cached references scoped to one resolution root."""
        if self._root is None:
            self._root = root
        elif self._root is not root:
            message = "model validation context belongs to a different resolution root"
            raise ValueError(message)

    def mark_validated(self, *, root: Model, reachable_only: bool) -> None:
        """Record successful source validation for this invocation's scope."""
        self.bind(root)
        self._validated_scopes.add(reachable_only)

    def ensure_validated(self, *, root: Model, reachable_only: bool) -> None:
        """Complete partial source analysis before using cached placements."""
        self.bind(root)
        if False in self._validated_scopes or reachable_only in self._validated_scopes:
            return
        from ldraw.validation import (  # noqa: PLC0415 - model/validation cycle
            _iter_model_numeric_issues,
            _reject_numeric_issue,
        )

        for issue in _iter_model_numeric_issues(
            root, reachable_only=reachable_only, context=self
        ):
            _reject_numeric_issue(issue)
        self.mark_validated(root=root, reachable_only=reachable_only)

    def record(self, *, piece: Piece, analysis: _NumericAnalysis) -> None:
        """Retain finite effective placements with the required type narrowing."""
        if (
            not analysis.invalid
            and analysis.position is not None
            and analysis.matrix is not None
        ):
            self.placements[piece] = analysis.position, analysis.matrix

    def placement(self, *, model: Model, piece: Piece) -> tuple[Vector, Matrix]:
        """Validate a missing cache entry instead of exposing a dictionary error."""
        if (placement := self.placements.get(piece)) is not None:
            return placement
        from ldraw.validation import (  # noqa: PLC0415 - exceptional partial cache
            _numeric_issue,
            _object_analysis,
            _reject_numeric_issue,
        )

        analysis = _object_analysis(piece)
        if issue := _numeric_issue(
            analysis,
            number=model.source_line_for(piece),
            path=None,
            section=model.name or None,
        ):
            _reject_numeric_issue(issue)
        self.record(piece=piece, analysis=analysis)
        if (placement := self.placements.get(piece)) is None:
            message = "source placement analysis did not provide a position and matrix"
            raise ValueError(message)
        return placement

    def resolve(self, *, root: Model, piece: Piece) -> Model | None:
        """Resolve a source reference once against this operation's root table."""
        if self._root is not root:
            self.bind(root)
        if piece not in self.targets:
            self.targets[piece] = root.submodel_for(piece)
        return self.targets[piece]


def _resolve_reference(
    *, root: Model, piece: Piece, context: ModelValidationContext | None
) -> Model | None:
    """Resolve references through the invocation cache when one is available."""
    return (
        context.resolve(root=root, piece=piece)
        if context is not None
        else root.submodel_for(piece)
    )
