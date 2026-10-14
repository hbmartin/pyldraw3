"""Validate document resolution before serializing source definitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

from ldraw._model_definitions import _DefinitionRegistry
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw._instruction_resolution import InstructionResolution
    from ldraw.instructions import InstructionDocument
    from ldraw.model import Model
    from ldraw.part import ParsedObject


@dataclass(slots=True)
class _ExportState:
    source: Model
    aliases: tuple[Model, ...] = ()
    registry: _DefinitionRegistry = field(init=False)
    dependencies: dict[str, Model] = field(default_factory=dict)

    def __post_init__(self: Self) -> None:
        self.registry = _DefinitionRegistry(selected=self.source, aliases=self.aliases)

    def register(self: Self, *, piece: Piece, target: Model) -> bool:
        """Keep file identities exact and recognize explicit selected replacements."""
        name = normalize_ref(target.name)
        added = self.registry.register(target)
        reference = normalize_ref(piece.reference)
        if reference != name:
            message = (
                f"reference {piece.reference!r} resolves to section {target.name!r}; "
                "cannot serialize without rewriting the reference"
            )
            raise ValueError(message)
        if not added:
            return False
        self.dependencies[name] = target
        return True


def instruction_dependencies(
    *, resolution: InstructionResolution, source: Model, objects: Iterable[ParsedObject]
) -> dict[str, Model]:
    """Close dependencies independently of occurrence cycle cuts and counts."""
    state = _ExportState(source=source, aliases=resolution.equivalents(source))
    pending = deque([tuple(objects)])
    while pending:
        for obj in pending.popleft():
            if not isinstance(obj, Piece):
                continue
            target = resolution.resolve(obj)
            if target is not None and state.register(piece=obj, target=target):
                pending.append(tuple(target.objects))
    return state.dependencies


@dataclass(slots=True)
class _ExportPreparation:
    """Reuse validated closures within one synchronous artifact export only."""

    document: InstructionDocument
    _closures: dict[tuple[int, str, tuple[int, ...]], tuple[Model, ...]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        self.document._validate_export(preparation=self)  # noqa: SLF001
        for section in self.document.sections:
            for step in section.steps:
                self.dependencies(source=section.model, objects=step.cumulative_objects)

    def dependencies(
        self, *, source: Model, objects: Iterable[ParsedObject]
    ) -> tuple[Model, ...]:
        """Ignore descriptive objects when identifying equivalent source closures."""
        objects = tuple(objects)
        key = (
            id(source),
            normalize_ref(source.name),
            tuple(id(obj) for obj in objects if isinstance(obj, Piece)),
        )
        if key not in self._closures:
            resolution = self.document._resolution  # noqa: SLF001
            if resolution is None:
                message = "instruction document has no resolution context"
                raise ValueError(message)
            self._closures[key] = tuple(
                resolution.dependencies(source=source, objects=objects).values()
            )
        return self._closures[key]
