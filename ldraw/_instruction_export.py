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
    from ldraw.instructions import InstructionDocument, InstructionSection
    from ldraw.model import Model
    from ldraw.part import ParsedObject


@dataclass(slots=True)
class _ExportState:
    source: Model
    aliases: tuple[Model, ...] = ()
    registry: _DefinitionRegistry = field(init=False)
    dependencies: dict[str, Model] = field(default_factory=dict)
    targets: dict[Piece, Model | None] = field(default_factory=dict)

    def __post_init__(self: Self) -> None:
        self.registry = _DefinitionRegistry(selected=self.source, aliases=self.aliases)

    def register(self: Self, *, piece: Piece, target: Model) -> bool:
        """Keep file identities exact and recognize explicit selected replacements."""
        name = normalize_ref(target.name)
        added = self.add(target)
        reference = normalize_ref(piece.reference)
        if reference != name:
            message = (
                f"reference {piece.reference!r} resolves to section {target.name!r}; "
                "cannot serialize without rewriting the reference"
            )
            raise ValueError(message)
        return added

    def add(self, target: Model) -> bool:
        """Select one file definition; spelling was checked by preparation."""
        if not self.registry.register(target):
            return False
        self.dependencies[normalize_ref(target.name)] = target
        return True


def instruction_dependencies(
    *,
    resolution: InstructionResolution,
    source: Model,
    objects: Iterable[ParsedObject],
    state: _ExportState | None = None,
    targets: dict[Piece, Model | None] | None = None,
) -> dict[str, Model]:
    """Close dependencies independently of occurrence cycle cuts and counts."""
    state = (
        state
        if state is not None
        else _ExportState(source=source, aliases=resolution.equivalents(source))
    )
    _collect_dependencies(
        resolution=resolution, state=state, objects=objects, targets=targets
    )
    return state.dependencies


def _collect_dependencies(
    *,
    resolution: InstructionResolution,
    state: _ExportState,
    objects: Iterable[ParsedObject],
    targets: dict[Piece, Model | None] | None = None,
) -> None:
    """Inspect each registered dependency once within the supplied definition set."""
    pending = deque([tuple(objects)])
    while pending:
        for obj in pending.popleft():
            if not isinstance(obj, Piece) or obj in state.targets:
                continue
            target = _prepared_target(resolution=resolution, piece=obj, targets=targets)
            state.targets[obj] = target
            if target is not None and (
                state.register(piece=obj, target=target)
                if targets is None
                else state.add(target)
            ):
                pending.append(tuple(target.objects))


def _prepared_target(
    *,
    resolution: InstructionResolution,
    piece: Piece,
    targets: dict[Piece, Model | None] | None,
) -> Model | None:
    if targets is None:
        return resolution.resolve(piece)
    if piece not in targets:
        message = "source placements changed outside the prepared export scope"
        raise ValueError(message)
    return targets[piece]


@dataclass(slots=True)
class _ExportPreparation:
    """Reuse validated closures within one synchronous artifact export only."""

    document: InstructionDocument
    selected: tuple[InstructionSection, ...] | None = field(default=None, kw_only=True)
    sections: tuple[InstructionSection, ...] = field(init=False)
    _targets: dict[Piece, Model | None] = field(init=False, repr=False)
    _closures: dict[tuple[int, str, tuple[int, ...]], tuple[Model, ...]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        selected = self.document.sections if self.selected is None else self.selected
        resolution = self.document._resolution  # noqa: SLF001
        assert resolution is not None  # noqa: S101 - initialized document invariant
        source = selected[0].model
        state = _ExportState(source=source, aliases=resolution.equivalents(source))
        self.sections = selected
        pending = selected
        while pending:
            _collect_dependencies(
                resolution=resolution, state=state, objects=_section_objects(pending)
            )
            chosen = {normalize_ref(section.name) for section in self.sections}
            pending = (
                ()
                if self.selected is None
                else tuple(
                    section
                    for section in self.document.sections
                    if normalize_ref(section.name) in state.dependencies
                    and normalize_ref(section.name) not in chosen
                )
            )
            self.sections = (*self.sections, *pending)
        self._targets = state.targets

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
                resolution.dependencies(
                    source=source, objects=objects, targets=self._targets
                ).values()
            )
        return self._closures[key]


def prepare_export(
    document: InstructionDocument,
    *,
    selected: tuple[InstructionSection, ...] | None = None,
) -> _ExportPreparation:
    """Validate one explicit output scope; materialize writer closures lazily."""
    return _ExportPreparation(document=document, selected=selected)


def _section_objects(sections: Iterable[InstructionSection]) -> dict[Piece, None]:
    """Validate retained and edited step inputs without repeated closure builds."""
    return dict.fromkeys(
        obj
        for section in sections
        for objects in (
            section.model.objects,
            *(step.cumulative_objects for step in section.steps),
        )
        for obj in objects
        if isinstance(obj, Piece)
    )
