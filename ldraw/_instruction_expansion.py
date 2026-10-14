"""Step-local expansion models, imported after core model initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._instruction_common import _is_instruction_model
from ldraw._model_cycles import _cycle_callback
from ldraw._model_views import _selected_model
from ldraw.errors import DuplicateSubmodelError
from ldraw.model import Model, _occurrences_at_origin
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

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Keep step expansion finite and retain closing references as leaves."""
        source = (
            self if self._serialization_origin is None else self._serialization_origin
        )
        return _occurrences_at_origin(
            model=self,
            expand_submodels=expand_submodels,
            include_steps=include_steps,
            on_cycle=_cycle_callback(self),
            cycle_leaf=True,
            visiting=self.resolution.ancestry(source),
        )

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
        if self.expand:
            dependencies = self.resolution.dependencies(
                source=self, objects=self.objects
            )
            for key, target in dependencies.items():
                if (
                    previous := self.submodels.get(key)
                ) is not None and _selected_model(previous) is not _selected_model(
                    target
                ):
                    raise DuplicateSubmodelError(target.name)
                self.submodels.setdefault(key, target)
        return super(_InstructionExpansion, self).to_ldraw()
