"""Step-local expansion models, imported after core model initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING

from ldraw._instruction_common import _is_instruction_model
from ldraw._instruction_export import _ExportState, instruction_dependencies
from ldraw._model_cycles import _cycle_callback
from ldraw.model import Model, _models_ldraw, _occurrences_at_origin
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw import _instruction_resolution
    from ldraw.model import ModelOccurrence
    from ldraw.pieces import Piece


@dataclass(slots=True, eq=False)
class _InstructionExpansion(Model):
    resolution: _instruction_resolution.InstructionResolution = field(
        kw_only=True, repr=False
    )
    expand: bool = field(kw_only=True, repr=False)
    source: Model = field(kw_only=True, repr=False)

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Keep step expansion finite and retain closing references as leaves."""
        return _occurrences_at_origin(
            model=self,
            expand_submodels=expand_submodels,
            include_steps=include_steps,
            on_cycle=_cycle_callback(self),
            cycle_leaf=True,
            visiting=self.resolution.ancestry(self.source),
        )

    def iter_pieces(self) -> Iterator[Piece]:
        """Inspect the same finite leaves exposed by instruction occurrences."""
        return (occurrence.piece for occurrence in self.iter_occurrences())

    def _serialization_aliases(self) -> tuple[Model, ...]:
        return self.resolution.equivalents(self.source)

    def submodel_for(self, piece: Piece) -> Model | None:
        """Expand instruction sections while keeping embedded DAT parts as leaves."""
        if not self.expand:
            return None
        target = self.resolution.resolve(piece)
        if target is None or not _is_instruction_model(target):
            return None
        if (key := normalize_ref(target.name)) != normalize_ref(self.name):
            self.submodels.setdefault(key, target)
        return target

    def to_ldraw(self) -> str:
        """Close dependencies and reject lossy bindings before serialization."""
        if not self.expand:
            return super(_InstructionExpansion, self).to_ldraw()
        state = _ExportState(source=self, aliases=self._serialization_aliases())
        for target in self.submodels.values():
            state.add(target)
        dependencies = instruction_dependencies(
            resolution=self.resolution,
            source=self,
            objects=chain(
                self.objects, *(target.objects for target in self.submodels.values())
            ),
            state=state,
        )
        return _models_ldraw(
            models=(self, *dependencies.values()),
            mpd=bool(self.submodels or dependencies),
        )
