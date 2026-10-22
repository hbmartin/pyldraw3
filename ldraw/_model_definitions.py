"""Private source lineage and serialized section-definition registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypedDict, cast
from uuid import uuid4

from ldraw._model_views import _selected_model
from ldraw.errors import DuplicateSubmodelError
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from ldraw.model import Model


class _SourceOrigin:
    """Read legacy opaque-token pickles; new models use primitive records."""

    __slots__ = ()


class _Origin(TypedDict):
    version: Literal[2]
    family: dict[str, object]
    path: str
    parent: Model | None
    legacy: bool


def _root_origin(*, parent: Model | None = None, legacy: bool = False) -> _Origin:
    return {"version": 2, "family": {}, "path": "", "parent": parent, "legacy": legacy}


def _child_origin(origin: _Origin) -> _Origin:
    return {**origin, "path": f"{origin['path']}{uuid4().hex}/"}


def _flat_origin(value: dict[str, object]) -> _Origin:
    """Migrate shared directional records in place, without recursive descent."""
    pending: list[dict[str, object]] = []
    seen: set[int] = set()
    current: object = value
    while isinstance(current, dict) and current.get("version") != 2:
        if id(current) in seen:
            current = None
            break
        seen.add(id(current))
        pending.append(current)
        current = current.get("parent")
    origin = (
        cast("_Origin", current)
        if isinstance(current, dict)
        else cast("_Origin", _new_origin(current))
    )
    while pending:
        record = pending.pop()
        replacement = _child_origin(origin)
        record.clear()
        record.update(replacement)
        origin = cast("_Origin", record)
    return cast("_Origin", value)


def _new_origin(value: object) -> dict[str, object]:
    """Extend a flat branch label; explicit model origins stay live."""
    match value:
        case dict():
            origin = _child_origin(_flat_origin(value))
        case _SourceOrigin():
            origin = _root_origin(legacy=True)
        case None:
            origin = _root_origin()
        case _:
            origin = _explicit_origin(value)
    return dict(origin)


def _explicit_origin(value: object) -> _Origin:
    from ldraw.model import Model  # noqa: PLC0415 - runtime model cycle

    return _root_origin(parent=value if isinstance(value, Model) else None)


def _serialization_origins(model: Model) -> dict[int, object]:
    """Visit explicit model links, never the history encoded in branch labels."""
    origins: dict[int, object] = {}
    origin: object = model
    while origin is not None:
        if id(origin) in origins:
            break
        match origin:
            case _SourceOrigin():
                origins[id(origin)] = _root_origin(legacy=True)
                break
            case dict():
                record = _flat_origin(origin)
                origins[id(origin)] = record
                origin = record["parent"]
            case _:
                origin = _selected_model(cast("Model", origin))
                if id(origin) in origins:
                    break
                origins[id(origin)] = origin
                origin = getattr(origin, "_serialization_origin", None)
    return origins


def _ancestor(*, origin: object, records: dict[int, object]) -> bool:
    if not isinstance(origin, dict):
        return False
    candidate = _flat_origin(origin)
    return any(
        isinstance(record, dict)
        and record["family"] is candidate["family"]
        and cast("str", record["path"]).startswith(candidate["path"])
        for record in records.values()
    )


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
        origin = getattr(source, "_serialization_origin", None)
        if key == self._key and (
            id(source) in self._origins
            or _ancestor(origin=origin, records=self._origins)
        ):
            source = _selected_model(self.selected)
        if (previous := self.names.get(key)) is not None:
            if previous is not source:
                error = DuplicateSubmodelError(target.name)
                if isinstance(origin, _SourceOrigin) or any(
                    isinstance(record, dict) and record.get("legacy")
                    for record in (*self._origins.values(), origin)
                ):
                    error.add_note(
                        "Legacy pickle tokens do not establish directional ancestry; "
                        "rebuild from LDraw or supply an explicit model origin."
                    )
                raise error
            return False
        self.names[key] = source
        return True
