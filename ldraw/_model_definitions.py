"""Private source lineage and serialized section-definition registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from ldraw._model_views import _selected_model
from ldraw.errors import DuplicateSubmodelError
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from ldraw.model import Model


class _SourceOrigin:
    """Read legacy opaque-token pickles; new models use primitive records."""

    __slots__ = ()


def _new_origin(value: object) -> dict[str, object]:
    """Record an immediate predecessor without opaque pickle dependencies."""
    if value is None or isinstance(value, dict | _SourceOrigin):
        return {"parent": value if isinstance(value, dict) else None}
    from ldraw.model import Model  # noqa: PLC0415 - runtime model cycle

    parent = value if isinstance(value, Model) else None
    return {"parent": parent}


def _serialization_origins(model: Model) -> dict[int, object]:
    """Collect directional model and primitive-record ancestry without looping."""
    origins: dict[int, object] = {}
    origin: object = model
    while origin is not None:
        if isinstance(origin, _SourceOrigin):
            break
        if isinstance(origin, dict):
            if id(origin) in origins:
                break
            origins[id(origin)] = origin
            origin = origin.get("parent")
            continue
        origin = _selected_model(cast("Model", origin))
        if id(origin) in origins:
            break
        origins[id(origin)] = origin
        origin = origin._serialization_origin  # noqa: SLF001
    return origins


@dataclass(slots=True)
class _DefinitionRegistry:
    """Keep selected-source exemptions separate from dependency conflicts."""

    selected: Model
    aliases: tuple[Model, ...] = ()
    names: dict[str, Model] = field(init=False)
    _key: str = field(init=False)
    _origins: dict[int, object] = field(init=False)

    def __post_init__(self) -> None:
        self._key = normalize_ref(self.selected.name)
        self.names = {self._key: _selected_model(self.selected)}
        self._origins = _serialization_origins(self.selected)
        self._origins.update(
            (id(_selected_model(alias)), _selected_model(alias))
            for alias in self.aliases
        )

    def register(self, target: Model) -> bool:
        """Register one exact definition; return whether it is newly encountered."""
        key = normalize_ref(target.name)
        source = _selected_model(target)
        origin = source._serialization_origin  # noqa: SLF001
        if key == self._key and (
            id(source) in self._origins
            or (isinstance(origin, dict) and id(origin) in self._origins)
        ):
            source = _selected_model(self.selected)
        if (previous := self.names.get(key)) is not None:
            if previous is not source:
                raise DuplicateSubmodelError(target.name)
            return False
        self.names[key] = source
        return True
