"""Flat ancestry, standard restoration hooks, and persisted-state compatibility."""

from __future__ import annotations

import base64
import gc
import json
import pickle
from copy import copy, deepcopy
from copyreg import dispatch_table
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self
from unittest.mock import patch
from weakref import ref

import pytest

from ldraw._model_definitions import _SourceOrigin
from ldraw.errors import DuplicateSubmodelError
from ldraw.model import Model
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from collections.abc import Callable


def pickle_model(model: Model) -> Model:
    return pickle.loads(pickle.dumps(model))  # noqa: S301 - trusted test graph


@pytest.mark.parametrize("derive", [copy, replace])
def test_twenty_thousand_derivations_keep_flat_serializable_ancestry(
    derive: Callable[[Model], Model],
) -> None:
    original = Model(name="main.ldr")
    current = original
    ancestors = [original]
    for index in range(20_000):
        current = derive(current)
        if index in {100, 1_000, 10_000}:
            ancestors.append(current)
    assert json.loads(json.dumps(asdict(current)))["name"] == original.name
    for restored in (deepcopy(current), pickle_model(current)):
        assert restored.to_ldraw() == ""
    current.submodels = {f"ancestor-{i}": model for i, model in enumerate(ancestors)}
    for protocol in (4, 5):
        restored = pickle.loads(pickle.dumps(current, protocol=protocol))  # noqa: S301
        assert restored.to_ldraw().count("0 FILE main.ldr") == 1
    assert deepcopy(current).to_ldraw().count("0 FILE main.ldr") == 1
    sibling = derive(ancestors[-1])
    current.submodels["sibling"] = sibling
    with pytest.raises(DuplicateSubmodelError):
        current.to_ldraw()


def test_separately_copied_graphs_cannot_claim_shared_ancestry() -> None:
    ancestor = Model(name="main.ldr")
    descendant = replace(ancestor)
    first, second = deepcopy((ancestor, descendant))
    second.submodels = {"ancestor": first}
    assert second.to_ldraw().count("0 FILE main.ldr") == 1
    second.submodels["separate"] = deepcopy(ancestor)
    with pytest.raises(DuplicateSubmodelError):
        second.to_ldraw()


def test_ordinary_derivations_release_predecessor_models() -> None:
    class WeakModel(Model):
        pass

    original = WeakModel(name="main.ldr")
    weak_original = ref(original)
    child = replace(original)
    copied = copy(child)
    del original
    gc.collect()
    assert weak_original() is None
    assert copied._serialization_origin["path"].count("/") == 2  # noqa: SLF001
    assert child.to_ldraw() == copied.to_ldraw()


def test_flat_model_serialization_does_not_discover_lineage() -> None:
    class Minimal(Model):
        def __init__(self: Self) -> None:
            self.name = "main.ldr"
            self.objects = [Piece.place("3001")]
            self.submodels = {}

    with patch(
        "ldraw._model_definitions._serialization_origins",
        side_effect=AssertionError("flat export inspected lineage"),
    ):
        assert "3001.dat" in Minimal().to_ldraw()
    minimal = Minimal()
    minimal.submodels["self"] = minimal
    assert minimal.to_ldraw().count("0 FILE main.ldr") == 1


class Writes:
    """Observe cooperative attribute restoration."""

    fields: ClassVar[list[str]] = []

    def __setattr__(self: Self, name: str, value: object) -> None:
        Writes.fields.append(name)
        super().__setattr__(name, value)


class State:
    """Restore standard dictionary and slot state through setters."""

    calls: ClassVar[int] = 0

    def __setstate__(
        self: Self, state: tuple[dict[str, object] | None, dict[str, object]]
    ) -> None:
        State.calls += 1
        dictionary, slots = state
        if dictionary:
            self.__dict__.update(dictionary)
        for name, value in slots.items():
            setattr(self, name, value)


class Before(State, Writes, Model):
    """Put both state and attribute hooks before Model."""


class After(Model, State, Writes):
    """Put both hooks after Model."""


class SetterBefore(Writes, Model):
    """Observe Model field restoration through an overriding setter."""


class SetterAfter(Model, Writes):
    """Observe cooperative setter dispatch after Model."""


@pytest.mark.parametrize("kind", [Before, After, SetterBefore, SetterAfter])
@pytest.mark.parametrize("operation", [copy, deepcopy, pickle_model])
def test_restoration_honors_hooks_and_setters_in_both_mro_orders(
    kind: type[Model],
    operation: Callable[[Model], Model],
) -> None:
    raw = kind(name="main.ldr", objects=[Piece.place("3001")])
    raw.submodels[raw.name] = raw
    raw.extra = raw
    edited = replace(raw, objects=[Piece.place("3002")])
    edited.extra = raw
    Writes.fields.clear()
    State.calls = 0
    restored = operation(edited)
    assert {"name", "objects", "submodels", "_serialization_origin"} <= set(
        Writes.fields
    )
    if kind in {Before, After}:
        assert State.calls >= 1
    assert "3002.dat" in restored.to_ldraw()
    if operation is not copy:
        assert restored.extra is restored.submodels[raw.name]
    other = replace(raw)
    restored.submodels = {"sibling": other}
    with pytest.raises(DuplicateSubmodelError):
        restored.to_ldraw()


class ArbitraryState(Model):
    """Use an arbitrary state payload rather than standard field dictionaries."""

    def __getstate__(self: Self) -> list[object]:
        return [self.name, self.objects, self.submodels, self._serialization_origin]

    def __setstate__(self: Self, state: list[Any]) -> None:
        self.name, self.objects, self.submodels, self._serialization_origin = state


@pytest.mark.parametrize("operation", [copy, deepcopy, pickle_model])
def test_arbitrary_state_payload_remains_authoritative(
    operation: Callable[[Model], Model],
) -> None:
    raw = ArbitraryState(name="main.ldr")
    raw.submodels[raw.name] = raw
    assert operation(replace(raw)).to_ldraw().count("0 FILE main.ldr") == 1


class Reduced(Model):
    """Keep an overriding reduction authoritative."""

    def __reduce__(self: Self) -> tuple[object, ...]:
        return type(self), (), self.__getstate__()


class StringReduced(Model):
    """Return the same instance through a singleton reduction."""

    def __reduce_ex__(self: Self, _protocol: object) -> str:
        return "SINGLETON"


class DeepCopyMixin:
    """Supply a cooperative custom deepcopy result."""

    def __deepcopy__(self: Self, _memo: dict[int, object]) -> Model:
        return Model(name="custom.ldr")


class CustomDeepCopy(Model, DeepCopyMixin):
    """Keep a deepcopy mixin after Model."""


def set_custom_state(model: Model, state: tuple[object, ...]) -> None:
    model.name, model.objects, model.submodels, model._serialization_origin = state  # noqa: SLF001 - private state restoration


class SetterReduced(Model):
    """Supply a reduction with an explicit state setter."""

    def __reduce__(self: Self) -> tuple[object, ...]:
        state = self.name, self.objects, self.submodels, self._serialization_origin
        return type(self), (), state, None, None, set_custom_state


class ContainerReduced(Model):
    """Exercise both list and dictionary iterators in a reduction."""

    def __init__(self: Self) -> None:
        super().__init__()
        self.appended: list[object] = []
        self.assigned: dict[object, object] = {}

    def __reduce__(self: Self) -> tuple[object, ...]:
        piece = Piece.place("3001")
        return (
            type(self),
            (),
            self.__getstate__(),
            iter([piece]),
            iter([("key", piece)]),
        )

    def append(self: Self, item: object) -> None:
        """Record a reduction's list items."""
        self.appended.append(item)

    def __setitem__(self: Self, key: object, value: object) -> None:
        self.assigned[key] = value


class StatelessReduced(Model):
    """Honor a complete custom reduction that has no state to restore."""

    def __reduce_ex__(self: Self, _protocol: object) -> tuple[object, ...]:
        return Model, ("custom.ldr",)


class FailingState(Model):
    """Raise inside restoration, including when invoked by unpickling."""

    def __setstate__(self: Self, _state: object) -> None:
        message = "restoration failed"
        raise RuntimeError(message)


@pytest.mark.parametrize("operation", [copy, deepcopy])
def test_reduction_iterators_preserve_shared_item_identity(
    operation: Callable[[Model], Model],
) -> None:
    restored = operation(ContainerReduced())
    assert len(restored.appended) == 1
    assert restored.appended[0] is restored.assigned["key"]


@pytest.mark.parametrize("operation", [copy, deepcopy, pickle_model])
def test_stateless_reduction_is_authoritative(
    operation: Callable[[Model], Model],
) -> None:
    assert operation(StatelessReduced()).name == "custom.ldr"
    with pytest.raises(RuntimeError, match="restoration failed"):
        operation(FailingState())


@pytest.mark.parametrize("operation", [copy, deepcopy, pickle_model])
@pytest.mark.parametrize("kind", [Reduced, SetterReduced])
def test_custom_reduce_hook_is_honored(
    operation: Callable[[Model], Model], kind: type[Model]
) -> None:
    raw = kind(name="main.ldr")
    raw.submodels[raw.name] = raw
    assert operation(replace(raw)).to_ldraw().count("0 FILE main.ldr") == 1


@pytest.mark.parametrize("operation", [copy, deepcopy])
def test_custom_state_setter_and_copyreg_reduction(
    operation: Callable[[Model], Model],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = Model(name="main.ldr")
    raw.submodels[raw.name] = raw
    monkeypatch.setitem(
        dispatch_table,
        Model,
        lambda model: (
            Model,
            (),
            (model.name, model.objects, model.submodels, model._serialization_origin),  # noqa: SLF001
            None,
            None,
            set_custom_state,
        ),
    )
    assert operation(replace(raw)).to_ldraw().count("0 FILE main.ldr") == 1


def test_authoritative_copy_hooks_and_restoration_failures() -> None:
    singleton = StringReduced()
    assert copy(singleton) is singleton
    assert deepcopy(singleton) is singleton
    assert deepcopy(CustomDeepCopy()).name == "custom.ldr"

    class Failing(Model):
        def __setstate__(self: Self, _state: object) -> None:
            message = "restoration failed"
            raise RuntimeError(message)

    for operation in (copy, deepcopy):
        with pytest.raises(RuntimeError, match="restoration failed"):
            operation(Failing())
    # A failure must not leave a restoration guard active for later derivations.
    raw = Model(name="main.ldr")
    first, second = replace(raw), replace(raw)
    first.submodels["sibling"] = second
    with pytest.raises(DuplicateSubmodelError):
        first.to_ldraw()


@pytest.mark.parametrize("format_name", ["token", "dictionary"])
@pytest.mark.parametrize("model_name", ["self_table", "edited"])
def test_saved_pickle_formats(format_name: str, model_name: str) -> None:
    path = Path(__file__).parent / "fixtures/model_lineage.json"
    fixture = json.loads(path.read_text())[format_name]
    model = pickle.loads(base64.b64decode(fixture["models"][model_name]))  # noqa: S301 - committed local fixture
    if format_name == "token" and model_name == "edited":
        with pytest.raises(DuplicateSubmodelError) as caught:
            model.to_ldraw()
        assert "Legacy pickle tokens" in caught.value.__notes__[0]
    else:
        assert model.to_ldraw().count("0 FILE main.ldr") == 1
        assert deepcopy(model).to_ldraw() == model.to_ldraw()


def test_old_dictionary_migration_is_iterative_and_keeps_shared_records() -> None:
    ancestor = Model(name="main.ldr")
    record = {"parent": None}
    object.__setattr__(ancestor, "_serialization_origin", record)
    for _ in range(5_000):
        record = {"parent": record}
    descendant = Model(name="main.ldr", submodels={"ancestor": ancestor})
    object.__setattr__(descendant, "_serialization_origin", record)
    assert descendant.to_ldraw().count("0 FILE main.ldr") == 1
    assert deepcopy(descendant).to_ldraw().count("0 FILE main.ldr") == 1


def test_unconverted_legacy_tokens_cannot_establish_ancestry() -> None:
    token = _SourceOrigin()
    original, edited = Model(name="main.ldr"), Model(name="main.ldr")
    # A custom state hook can restore slots directly, bypassing Model's setter.
    for model in (original, edited):
        object.__setattr__(model, "_serialization_origin", token)
    edited.submodels["original"] = original
    with pytest.raises(DuplicateSubmodelError) as caught:
        edited.to_ldraw()
    assert "Legacy pickle tokens" in caught.value.__notes__[0]


def test_restored_dictionary_history_can_be_copied_before_serialization() -> None:
    model = Model(name="main.ldr")
    model.submodels[model.name] = model
    state = model.__getstate__()
    record = state[1]["_serialization_origin"]
    for _ in range(2_000):
        record = {"parent": record}
    state[1]["_serialization_origin"] = record
    restored = object.__new__(Model)
    restored.__setstate__(state)
    assert deepcopy(restored).to_ldraw().count("0 FILE main.ldr") == 1
    assert pickle_model(restored).to_ldraw().count("0 FILE main.ldr") == 1


def test_cyclic_old_dictionary_state_is_migrated_without_looping() -> None:
    record: dict[str, object] = {}
    record["parent"] = record
    model = Model(name="main.ldr")
    object.__setattr__(model, "_serialization_origin", record)
    model.submodels[model.name] = model
    assert model.to_ldraw().count("0 FILE main.ldr") == 1
    assert pickle_model(model).to_ldraw() == model.to_ldraw()
