"""Private source lineage and serialized section-definition registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ldraw._model_views import _selected_model
from ldraw.errors import DuplicateSubmodelError
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from ldraw.model import Model


class _SourceOrigin:
    """Carry copy lineage without retaining a model or introducing a cycle."""

    __slots__ = ()


def _serialization_origins(model: Model) -> set[int]:
    """Collect explicit source ancestry and the terminal raw-copy token."""
    origins: set[int] = set()
    origin: Model | _SourceOrigin | None = model
    while origin is not None:
        if isinstance(origin, _SourceOrigin):
            origins.add(id(origin))
            break
        origin = _selected_model(origin)
        if id(origin) in origins:
            break
        origins.add(id(origin))
        origin = origin._serialization_origin  # noqa: SLF001
    return origins


@dataclass(slots=True)
class _DefinitionRegistry:
    """Keep selected-source exemptions separate from dependency conflicts."""

    selected: Model
    aliases: tuple[Model, ...] = ()
    names: dict[str, Model] = field(init=False)
    _key: str = field(init=False)
    _origins: set[int] = field(init=False)

    def __post_init__(self) -> None:
        self._key = normalize_ref(self.selected.name)
        self.names = {self._key: _selected_model(self.selected)}
        self._origins = _serialization_origins(self.selected)
        for alias in self.aliases:
            self._origins.update(_serialization_origins(alias))

    def register(self, target: Model) -> bool:
        """Register one exact definition; return whether it is newly encountered."""
        key = normalize_ref(target.name)
        source = _selected_model(target)
        if key == self._key and self._origins.intersection(
            _serialization_origins(source)
        ):
            source = _selected_model(self.selected)
        if (previous := self.names.get(key)) is not None:
            if previous is not source:
                raise DuplicateSubmodelError(target.name)
            return False
        self.names[key] = source
        return True
