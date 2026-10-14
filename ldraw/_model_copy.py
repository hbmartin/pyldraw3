"""Standard copying protocols with directional lineage creation and restoration."""

from __future__ import annotations

import copy
from contextvars import ContextVar
from copyreg import dispatch_table
from typing import TYPE_CHECKING, Any, cast

from ldraw._model_definitions import _new_origin, _SourceOrigin

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldraw.model import Model

_RESTORING: ContextVar[frozenset[int]] = ContextVar(
    "model_state_restore", default=frozenset()
)


def _origin_assignment(*, model: Model, value: object) -> object:
    """Distinguish ordinary lineage assignment from cooperative state restoration."""
    if (
        id(model) in _RESTORING.get()
        and value is not None
        and not isinstance(value, _SourceOrigin)
    ):
        return value
    return _new_origin(value)


def _copy_model[T: Model](model: T) -> T:
    """Honor standard reduction/state hooks before recording a shallow child."""
    reducer = dispatch_table.get(type(model))
    reduced = reducer(model) if reducer is not None else model.__reduce_ex__(4)
    if isinstance(reduced, str):
        return model
    reconstruct = cast("Callable[..., T]", vars(copy)["_reconstruct"])
    copied = reconstruct(model, None, *reduced)
    if copied is not model:
        copied._serialization_origin = model._serialization_origin  # noqa: SLF001
    return copied


def _restore_model_state(*, model: Model, state: Any) -> None:  # noqa: ANN401 - standard arbitrary object state
    """Restore the saved record graph without creating new derivation edges."""
    from ldraw.model import Model  # noqa: PLC0415 - runtime model cycle

    parent = super(Model, model)
    if setter := getattr(parent, "__setstate__", None):
        token = _RESTORING.set(_RESTORING.get() | {id(model)})
        try:
            setter(state)
        finally:
            _RESTORING.reset(token)
        return
    dictionary, slots = state if isinstance(state, tuple) else (state, {})
    if dictionary is not None:
        object.__getattribute__(model, "__dict__").update(dictionary)
    for name, value in slots.items():
        restored = (
            _new_origin(None)
            if name == "_serialization_origin" and isinstance(value, _SourceOrigin)
            else value
        )
        parent.__setattr__(name, restored)
