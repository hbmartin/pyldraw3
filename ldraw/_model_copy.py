"""Standard copying protocols with directional lineage creation and restoration."""

from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from copyreg import dispatch_table
from typing import TYPE_CHECKING, Any, cast

from ldraw._model_definitions import _flat_origin, _new_origin, _SourceOrigin

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldraw.model import Model

_RESTORING: ContextVar[frozenset[int]] = ContextVar(
    "model_state_restore", default=frozenset()
)


def _origin_assignment(*, model: Model, value: object) -> object:
    """Distinguish derivation from restoration, including overriding state hooks."""
    if id(model) in _RESTORING.get() and not isinstance(value, _SourceOrigin):
        if isinstance(value, dict) and value.get("version") != 2:
            return _flat_origin(value)
        return value
    return _new_origin(value)


def _pickle_reduction(reduced: Any) -> Any:  # noqa: ANN401 - standard reduction protocol
    """Wrap the state setter before pickle dispatches any subclass state hook."""
    if isinstance(reduced, str) or len(reduced) < 3 or reduced[2] is None:
        return reduced
    constructor, arguments, state, *options = reduced
    options += [None] * (3 - len(options))
    list_items, dict_items, setter = options
    return (
        constructor,
        arguments,
        (state, setter),
        list_items,
        dict_items,
        _setstate_guarded,
    )


def _setstate_guarded(
    model: Model, payload: tuple[Any, Callable[..., None] | None]
) -> None:
    """Restore a reduction's original state under one per-object guard."""
    state, setter = payload
    token = _RESTORING.set(_RESTORING.get() | {id(model)})
    try:
        if setter is not None:
            setter(model, state)
        elif hook := getattr(model, "__setstate__", None):
            hook(state)
        else:
            _restore_fields(model=model, state=state)
    finally:
        _RESTORING.reset(token)


def _reconstruct[T: Model](
    *,
    model: T,
    memo: dict[int, Any] | None,
    reduced: tuple[Any, ...],
) -> T:
    """Follow copy's reconstruction order and also support pickle state setters."""
    constructor, arguments, *options = reduced
    options += [None] * (4 - len(options))
    state, list_items, dict_items, setter = options
    if memo is not None:
        arguments = tuple(deepcopy(arg, memo) for arg in arguments)
    copied = cast("T", constructor(*arguments))
    if memo is not None:
        memo[id(model)] = copied
    if state is not None:
        if memo is not None:
            state = deepcopy(state, memo)
        _setstate_guarded(copied, (state, setter))
    if list_items is not None:
        for item in list_items:
            cast("Any", copied).append(
                deepcopy(item, memo) if memo is not None else item
            )
    if dict_items is not None:
        for key, value in dict_items:
            copied_key = deepcopy(key, memo) if memo is not None else key
            copied_value = deepcopy(value, memo) if memo is not None else value
            cast("Any", copied)[copied_key] = copied_value
    return copied


def _copy_model[T: Model](model: T, *, memo: dict[int, Any] | None = None) -> T:
    """Honor standard hooks; only a shallow copy introduces a derivation edge."""
    reducer = dispatch_table.get(type(model))
    reduced = reducer(model) if reducer is not None else model.__reduce_ex__(4)
    if isinstance(reduced, str):
        return model
    copied = _reconstruct(model=model, memo=memo, reduced=reduced)
    if copied is not model and memo is None:
        copied._serialization_origin = getattr(model, "_serialization_origin", None)  # noqa: SLF001
    return copied


def _restore_fields(*, model: Model, state: Any) -> None:  # noqa: ANN401 - standard arbitrary object state
    dictionary, slots = state if isinstance(state, tuple) else (state, {})
    if dictionary is not None:
        object.__getattribute__(model, "__dict__").update(dictionary)
    if slots is not None:
        for name, value in slots.items():
            setattr(model, name, value)


def _restore_model_state(*, model: Model, state: Any) -> None:  # noqa: ANN401 - standard arbitrary object state
    """Honor cooperative state hooks and normal subclass attribute dispatch."""
    from ldraw.model import Model  # noqa: PLC0415 - runtime model cycle

    token = _RESTORING.set(_RESTORING.get() | {id(model)})
    try:
        if setter := getattr(super(Model, model), "__setstate__", None):
            setter(state)
        else:
            _restore_fields(model=model, state=state)
    finally:
        _RESTORING.reset(token)
