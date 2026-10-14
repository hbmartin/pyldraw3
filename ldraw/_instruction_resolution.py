"""Document-local reference targets shared by instruction consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._instruction_common import _is_instruction_model
from ldraw._model_views import _resolution_root, _selected_model
from ldraw.utils import normalize_ref

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
    _reachable_sources: set[int] = field(default_factory=set, init=False, repr=False)
    _reachable_models: list[_model.Model] | None = field(
        default=None, init=False, repr=False
    )
    _sources: dict[int, tuple[_model.Model, _model.Model]] = field(
        default_factory=dict, init=False, repr=False
    )

    def bind_document(self, *, model: _model.Model) -> None:
        """Reject attaching one document's resolution to a different source scope."""
        if _resolution_root(model) is not _resolution_root(
            self.root
        ) or _selected_model(model) is not _selected_model(self.root):
            message = "instruction resolution belongs to a different document root"
            raise ValueError(message)

    def resolve(self, piece: Piece) -> _model.Model | None:
        """Resolve once; canonical definitions belong to discovery and export."""
        return self.context.resolve(root=self.root, piece=piece)

    def bind_sources(
        self, *, selected: _model.Model, sources: Iterable[_model.Model]
    ) -> None:
        """Associate retained content with this resolver's canonical source roles."""
        discovered = self.reachable_models()
        canonical = {
            normalize_ref(model.name): model for model in self.root.submodels.values()
        }
        canonical.update({normalize_ref(model.name): model for model in discovered})
        for source in sources:
            target = (
                self.root
                if source is selected
                else canonical.get(normalize_ref(source.name))
            )
            if target is not None:
                selected_source = _selected_model(source)
                self._sources[id(selected_source)] = (
                    selected_source,
                    _selected_model(target),
                )

    def for_sources(
        self, *, selected: _model.Model, sources: Iterable[_model.Model]
    ) -> InstructionResolution:
        """Fork correspondence ownership while retaining authoritative resolutions."""
        resolution = InstructionResolution(root=self.root, context=self.context)
        resolution._reachable_models = self.reachable_models()
        resolution._reachable_sources = self._reachable_sources.copy()
        resolution.bind_sources(selected=selected, sources=sources)
        return resolution

    def equivalents(self, source: _model.Model) -> tuple[_model.Model, ...]:
        """Expose only explicitly bound selected-source correspondences."""
        selected = _selected_model(source)
        binding = self._sources.get(id(selected))
        return (binding[1],) if binding is not None and binding[0] is selected else ()

    def reachable_models(self) -> list[_model.Model]:
        """Record root reachability while keeping declaration and discovery order."""
        if self._reachable_models is not None:
            return self._reachable_models
        pending = [self.root]
        discovered = {normalize_ref(self.root.name): self.root}
        self._reachable_sources.add(id(_selected_model(self.root)))
        index = 0
        while index < len(pending):
            current = pending[index]
            index += 1
            for piece in current.pieces:
                target = self.resolve(piece)
                if target is None or not _is_instruction_model(target):
                    continue
                self._reachable_sources.add(id(_selected_model(target)))
                if (key := normalize_ref(target.name)) not in discovered:
                    discovered[key] = target
                    pending.append(target)
        ordered = dict.fromkeys(
            (
                normalize_ref(self.root.name),
                *(normalize_ref(model.name) for model in self.root.submodels.values()),
                *discovered,
            )
        )
        self._reachable_models = [
            discovered[key] for key in ordered if key in discovered
        ]
        return self._reachable_models

    def ancestry(self, source: _model.Model) -> frozenset[str]:
        """Keep the owning root an ancestor only for root-reachable sections."""
        self.reachable_models()
        return (
            frozenset({normalize_ref(self.root.name)})
            if any(
                id(_selected_model(target)) in self._reachable_sources
                for target in (source, *self.equivalents(source))
            )
            else frozenset()
        )

    def dependencies(
        self,
        *,
        source: _model.Model,
        objects: Iterable[ParsedObject],
        targets: dict[Piece, _model.Model | None] | None = None,
    ) -> dict[str, _model.Model]:
        """Reject ambiguous bindings before materializing serialized dependencies."""
        from ldraw._instruction_export import instruction_dependencies  # noqa: PLC0415 - runtime model cycle

        return instruction_dependencies(
            resolution=self, source=source, objects=objects, targets=targets
        )

    def expansion(
        self, *, source: _model.Model, objects: Iterable[ParsedObject], expand: bool
    ) -> _model.Model:
        """Build a step-local model using the document's authoritative targets."""
        from ldraw._instruction_expansion import _InstructionExpansion  # noqa: PLC0415 - runtime cycle

        return _InstructionExpansion(
            name=source.name,
            objects=list(objects),
            _source_lines=source._source_lines,  # noqa: SLF001
            _object_source_lines=source._object_source_lines,  # noqa: SLF001
            resolution=self,
            expand=expand,
            source=source,
            _serialization_origin=source,
        )
