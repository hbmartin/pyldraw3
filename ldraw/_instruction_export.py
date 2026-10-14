"""Validate document resolution before serializing source definitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from ldraw._model_views import _selected_model
from ldraw.errors import DuplicateSubmodelError
from ldraw.model import _serialization_origins
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw._instruction_resolution import InstructionResolution
    from ldraw.model import Model
    from ldraw.part import ParsedObject


@dataclass(slots=True)
class _ExportState:
    source: Model
    names: dict[str, Model] = field(init=False)
    origins: set[int] = field(init=False)
    dependencies: dict[str, Model] = field(default_factory=dict)

    def __post_init__(self: Self) -> None:
        self.names = {normalize_ref(self.source.name): _selected_model(self.source)}
        self.origins = _serialization_origins(self.source)

    def register(self: Self, *, piece: Piece, target: Model) -> bool:
        """Keep file identities exact and recognize explicit selected replacements."""
        name = normalize_ref(target.name)
        source = _selected_model(target)
        if name == normalize_ref(self.source.name) and id(source) in self.origins:
            source = _selected_model(self.source)
        if (previous := self.names.get(name)) is not None and previous is not source:
            raise DuplicateSubmodelError(target.name)
        reference = normalize_ref(piece.reference)
        if reference != name:
            message = (
                f"reference {piece.reference!r} resolves to section {target.name!r}; "
                "cannot serialize without rewriting the reference"
            )
            raise ValueError(message)
        if name in self.names:
            return False
        self.names[name] = source
        self.dependencies[name] = target
        return True


def instruction_dependencies(
    *, resolution: InstructionResolution, source: Model, objects: Iterable[ParsedObject]
) -> dict[str, Model]:
    """Close dependencies independently of occurrence cycle cuts and counts."""
    state = _ExportState(source=source)
    pending = deque([tuple(objects)])
    while pending:
        for obj in pending.popleft():
            if not isinstance(obj, Piece):
                continue
            target = resolution.resolve(obj)
            if target is not None and state.register(piece=obj, target=target):
                pending.append(tuple(target.objects))
    return state.dependencies
