"""Construction protocols, descriptor caches, shared discovery and instructions."""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Never, Self
from unittest.mock import patch

import pytest

from ldraw._model_cycles import _custom_occurrences
from ldraw._model_validation import ModelValidationContext
from ldraw._model_views import _resolution_root, _selected_model
from ldraw.analysis import analyze_model
from ldraw.bom import bill_of_materials, compare_inventory
from ldraw.errors import SubmodelCycleError
from ldraw.instruction_artifacts import (
    _write_snapshot_ldr,
    _write_snapshot_mpd,
    instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.instructions import iter_instruction_issues
from ldraw.model import (
    Model,
    ModelOccurrence,
    _iter_occurrences_skip_cycles,
    parse_model,
)
from ldraw.model_summary import ModelSummary
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.validation import _piece_analysis

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# ruff: noqa: FBT001 - exercising positional-only legacy signatures


class Constructible(Model):
    """Use the receiver's class to make a normal instance."""

    def rebuild(self: Self) -> Model:
        """Construct an ordinary object from this receiver's visible class."""
        return self.__class__(name="replacement.ldr", objects=self.objects)


@pytest.mark.parametrize("model_type", [Model, Constructible])
def test_view_class_and_replace_construct_selected_type(
    model_type: type[Model],
) -> None:
    selected = model_type(name="sub.ldr", objects=[Piece.place("3001")])
    root = Model(name="main.ldr", submodels={selected.name: selected})
    view = root.submodel_view(selected.name)
    assert view.__class__ is model_type
    assert type(view) is not model_type
    assert isinstance(view, model_type)
    rebuilt = replace(view, name="replacement.ldr")
    assert type(rebuilt) is model_type
    assert rebuilt.name == "replacement.ldr"
    assert rebuilt.objects is selected.objects
    assert repr(view).startswith(f"{model_type.__name__}(")
    if isinstance(view, Constructible):
        assert type(view.rebuild()) is model_type
    assert _resolution_root(copy(view)) is root
    assert _resolution_root(deepcopy(view)) is not root


class Reify:
    """Cache a descriptor value by shadowing its name on its receiver."""

    def __init__(
        self: Self, function: Callable[[Model], int], *, dictionary: bool
    ) -> None:
        self.function = function
        self.dictionary = dictionary

    def __get__(
        self: Self, instance: Model | None, _owner: type[Model] | None = None
    ) -> object:
        if instance is None:
            return self
        value = self.function(instance)
        if self.dictionary:
            instance.__dict__[self.function.__name__] = value
        else:
            setattr(instance, self.function.__name__, value)
        return value


class ReifiedModel(Model):
    """Keep descriptors with both common self-shadowing cache implementations."""

    def nsub(self: Self) -> int:
        """Count models using the receiver's own resolution scope."""
        return len(self.submodels)

    nsub = Reify(function=nsub, dictionary=False)

    def dictionary_count(self: Self) -> int:
        """Count models with a dictionary-backed descriptor cache."""
        return len(self.submodels)

    dictionary_count = Reify(function=dictionary_count, dictionary=True)


@pytest.mark.parametrize("name", ["nsub", "dictionary_count"])
def test_custom_descriptor_cache_is_view_owned(name: str) -> None:
    selected = ReifiedModel(name="sub.ldr")
    root = Model(
        name="main.ldr",
        submodels={selected.name: selected, "leaf.ldr": Model(name="leaf.ldr")},
    )
    left = root.submodel_view(selected.name)
    right = root.submodel_view(selected.name)
    assert getattr(left, name) == 2
    assert name not in selected.__dict__
    assert getattr(selected, name) == 0
    assert getattr(left, name) == 2
    # Existing selected instance values remain authoritative to an uncached view.
    assert getattr(right, name) == 0
    setattr(left, name, 7)
    assert getattr(left, name) == 7
    assert getattr(selected, name) == 0
    delattr(left, name)
    assert getattr(left, name) == 0
    left.name = "changed.ldr"
    assert selected.name == "changed.ldr"


def test_descriptor_failure_resets_write_policy_and_data_setters_stay_live() -> None:
    class Failure:
        def __get__(
            self: Self, instance: Model, _owner: type[Model] | None = None
        ) -> Never:
            message = "descriptor failed"
            raise RuntimeError(message)

    class Selected(Model):
        broken = Failure()

        @property
        def label(self: Self) -> str:
            self.name = "read.ldr"
            return self.name

        @label.setter
        def label(self: Self, value: str) -> None:
            self.name = value

    selected = Selected(name="sub.ldr")
    view = selected.submodel_view(selected.name)
    with pytest.raises(RuntimeError, match="descriptor failed"):
        _ = view.broken
    view.broken = "override"
    assert selected.broken == "override"
    assert view.label == selected.name == "read.ldr"
    view.__dict__["label"] = "ignored"
    view.label = "setter.ldr"
    assert selected.name == "setter.ldr"
    assert view.label == "read.ldr"


@pytest.mark.parametrize("name", ["__class__", "__dict__"])
def test_view_special_attributes_cannot_change_selected_state(name: str) -> None:
    selected = ReifiedModel(name="sub.ldr")
    view = selected.submodel_view(selected.name)
    with pytest.raises(AttributeError):
        setattr(view, name, {} if name == "__dict__" else Model)
    with pytest.raises(AttributeError):
        delattr(view, name)
    assert type(selected) is ReifiedModel
    assert selected.__dict__ == {}
    other = Model(name="other.ldr")
    with pytest.raises(AttributeError, match="cannot change"):
        view.__setstate__((other, other))
    assert _selected_model(view) is selected


def test_required_metaclass_hooks_and_registries_do_not_run_for_adapters() -> None:
    class Registry(type):
        entries: ClassVar[list[tuple[str, str]]] = []

        def __new__(
            metaclass: type[Registry],
            name: str,
            bases: tuple[type, ...],
            namespace: dict[str, object],
            *,
            marker: str,
        ) -> Registry:
            assert marker == "user"
            metaclass.entries.append(("new", name))
            return super().__new__(metaclass, name, bases, namespace)

        def __init__(
            cls: Registry,
            name: str,
            bases: tuple[type, ...],
            namespace: dict[str, object],
            *,
            marker: str,
        ) -> None:
            assert marker == "user"
            cls.entries.append(("init", name))
            super().__init__(name, bases, namespace)

    class Selected(Model, metaclass=Registry, marker="user"):
        def __init_subclass__(cls: type[Self], *, registration: str) -> None:
            Registry.entries.append(("subclass", cls.__name__))

    selected = Selected(name="sub.ldr")
    view = selected.submodel_view(selected.name)
    assert isinstance(view, Selected)
    assert type(type(view)) is Registry
    assert Registry.entries == [("new", "Selected"), ("init", "Selected")]
    assert type(copy(view)) is type(view)


def test_existing_views_reflect_class_descriptor_replacements() -> None:
    class Selected(Model):
        @property
        def value(self: Self) -> str:
            return self.name

    def context_value(instance: Model) -> int:
        return len(instance.submodels)

    selected = Selected(name="sub.ldr")
    view = selected.submodel_view(selected.name)
    assert view.value == "sub.ldr"
    with patch.object(
        target=Selected,
        attribute="value",
        new=property(context_value),
    ):
        assert view.value == 0
    assert view.value == "sub.ldr"


class ExpansionOnly(Model):
    """Accept only the expansion keyword."""

    def iter_occurrences(
        self: Self, *, expand_submodels: bool = True
    ) -> Iterable[ModelOccurrence]:
        """Delegate using the accepted traversal options."""
        return super().iter_occurrences(expand_submodels=expand_submodels)


class NoFlags(Model):
    """Accept no traversal options."""

    def iter_occurrences(self: Self) -> Iterable[ModelOccurrence]:
        """Keep the provider's default traversal options."""
        return super().iter_occurrences()


class PositionalFlags(Model):
    """Accept traversal options only by position."""

    def iter_occurrences(
        self: Self, expand_submodels: bool = True, include_steps: bool = True, /
    ) -> Iterable[ModelOccurrence]:
        """Delegate using the accepted traversal options."""
        return super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        )


class PositionalGap(Model):
    """Place a defaulted argument before a positional traversal flag."""

    def iter_occurrences(
        self: Self,
        marker: str = "default",
        expand_submodels: bool = True,
        /,
        *,
        include_steps: bool = True,
    ) -> Iterable[ModelOccurrence]:
        """Delegate after confirming the intervening default argument."""
        assert marker == "default"
        return super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        )


class KeywordFlags(Model):
    """Accept traversal options through a keyword dictionary."""

    def iter_occurrences(self: Self, **kwargs: bool) -> Iterable[ModelOccurrence]:
        """Forward both supported keyword options."""
        return super().iter_occurrences(**kwargs)


@pytest.mark.parametrize(
    "model_type", [ExpansionOnly, NoFlags, PositionalFlags, PositionalGap, KeywordFlags]
)
def test_custom_flags_work_through_all_analysis_entrypoints(
    model_type: type[Model],
) -> None:
    model = model_type(name="main.ldr", objects=[Piece.place("3001", colour=4)])
    rows = bill_of_materials(model)
    assert rows == model.bill_of_materials()
    assert compare_inventory(model, rows).matched
    assert list(analyze_model(model).bom) == rows
    assert ModelSummary.from_model(model, parts=None).occurrence_count == 1
    if model_type is NoFlags:
        with pytest.raises(TypeError, match="does not support"):
            list(_iter_occurrences_skip_cycles(model, expand_submodels=False))
    else:
        assert (
            len(list(_iter_occurrences_skip_cycles(model, expand_submodels=False))) == 1
        )


def test_positional_gap_required_argument_is_rejected_before_calling_body() -> None:
    def required_occurrences(
        self: Model, marker: str, expand_submodels: bool = True, /
    ) -> Never:
        message = f"body must not run: {marker} {expand_submodels}"
        raise AssertionError(message)

    with (
        patch.object(
            target=Model, attribute="iter_occurrences", new=required_occurrences
        ),
        pytest.raises(TypeError, match="requires argument 'marker'"),
    ):
        _custom_occurrences(model=Model(), expand_submodels=True, include_steps=False)


def lattice(layers: int) -> Model:
    sections = [
        Model(name=f"{level}-{branch}.ldr")
        for level in range(layers)
        for branch in ("a", "b")
    ]
    for level in range(layers - 1):
        for section in sections[2 * level : 2 * level + 2]:
            section.objects = [
                Piece.place(f"{level + 1}-{branch}.ldr") for branch in ("a", "b")
            ]
    return Model(
        name="main.ldr",
        objects=[Piece.place("0-a.ldr"), Piece.place("0-b.ldr")],
        submodels={section.name: section for section in sections},
    )


def test_shared_graph_discovery_expands_each_source_once() -> None:
    root = lattice(24)
    context = ModelValidationContext()
    with (
        patch.object(
            target=ModelValidationContext,
            attribute="edges",
            autospec=True,
            side_effect=ModelValidationContext.edges,
        ) as edges,
        patch(
            target="ldraw.validation._piece_analysis", wraps=_piece_analysis
        ) as placements,
    ):
        context.ensure_validated(root=root, reachable_only=True)
        assert edges.call_count == 49
        assert placements.call_count == 94
        context.ensure_validated(root=root, reachable_only=True)
        assert edges.call_count == 49
    assert len(context.validated_sections) == 49


def test_resolved_instruction_targets_are_shared_across_consumers(
    tmp_path: Path,
) -> None:
    stale = Model(name="sub.ldr", objects=[Piece.place("3001", colour=4)])
    fresh = Model(name="sub.ldr", objects=[Piece.place("3002", colour=4)])
    external = Model(name="external.ldr", objects=[Piece.place("3003", colour=4)])

    class Resolver(Model):
        calls = 0

        def submodel_for(self: Self, piece: Piece) -> Model | None:
            self.calls += 1
            return {"sub.ldr": fresh, "external.ldr": external}.get(piece.reference)

    root = Resolver(
        name="main.ldr",
        objects=[Piece.place("sub.ldr"), Piece.place("external.ldr")],
        submodels={"sub.ldr": stale},
    )
    document = root.instruction_document()
    assert [section.name for section in document.sections] == [
        "main.ldr",
        "sub.ldr",
        "external.ldr",
    ]
    assert document.sections[1].model is fresh
    step = document.root.steps[0]
    assert [occ.part_code for occ in step.added_occurrences()] == ["3002", "3003"]
    assert [row.part for row in step.added_bill_of_materials()] == ["3002", "3003"]
    assert [row.part for row in step.cumulative_bill_of_materials()] == ["3002", "3003"]
    parts = Parts(
        parts_lst=Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst"
    )
    manifest = instruction_manifest(document, parts=parts)
    assert manifest["schema_version"] == 1
    assert {issue.code for issue in iter_instruction_issues(document)} == {
        "no-step-boundaries"
    }
    _write_snapshot_mpd(
        document, section=document.root, step=step, path=tmp_path / "snapshot.mpd"
    )
    _write_snapshot_ldr(
        document, section=document.root, step=step, path=tmp_path / "snapshot.ldr"
    )
    assert "3002.dat" in (tmp_path / "snapshot.mpd").read_text()
    assert "3001.dat" not in (tmp_path / "snapshot.mpd").read_text()
    assert [
        piece.part
        for piece in parse_model((tmp_path / "snapshot.ldr").read_text()).pieces
    ] == ["3002", "3003"]
    assert root.calls == 4
    fresh.objects = [Piece.place("3004")]
    assert root.instruction_document().sections[1].model.pieces[0].part == "3004"


def test_private_cyclic_mpd_remains_permissive_public_export_rejects(
    tmp_path: Path,
) -> None:
    root = Model(name="main.ldr", objects=[Piece.place("sub.ldr")])
    root.submodels = {
        "sub.ldr": Model(name="sub.ldr", objects=[Piece.place("main.ldr")])
    }
    document = root.instruction_document()
    section = document.sections[1]
    path = tmp_path / "cyclic.mpd"
    _write_snapshot_mpd(document, section=section, step=section.steps[0], path=path)
    assert path.read_text().count("0 FILE ") == 2
    with pytest.raises(SubmodelCycleError):
        list(parse_model(path.read_text()).iter_occurrences())
    parts = Parts(
        parts_lst=Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst"
    )
    destination = tmp_path / "output"
    with pytest.raises(SubmodelCycleError):
        write_instruction_snapshots(document, parts=parts, output=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".output-*"))


def test_deferred_closing_targets_retry_through_a_shared_parent() -> None:
    original = Model(name="a.ldr", objects=[Piece.place("shared.ldr")])
    shared = Model(name="shared.ldr", objects=[Piece.place("closing-a.ldr")])
    closing = Model(name="a.ldr", objects=[Piece.place("bad.dat")])
    alternate = Model(name="d.ldr", objects=[Piece.place("shared.ldr")])
    bad = parse_model("0 FILE bad.dat\n2 24 nan 0 0 1 1 1\n")
    targets = {
        "original-a.ldr": original,
        "shared.ldr": shared,
        "closing-a.ldr": closing,
        "d.ldr": alternate,
        "bad.dat": bad,
    }

    class Resolver(Model):
        def submodel_for(self: Self, piece: Piece) -> Model | None:
            return targets.get(piece.reference)

    root = Resolver(
        name="main.ldr", objects=[Piece.place("original-a.ldr"), Piece.place("d.ldr")]
    )
    with pytest.raises(ValueError, match=r"bad.dat:2:.*point1.x=nan"):
        ModelValidationContext().ensure_validated(root=root, reachable_only=True)


def test_unexpanded_step_inventory_and_embedded_dat_stay_leaves() -> None:
    root = Model(
        name="main.ldr", objects=[Piece.place("sub.ldr"), Piece.place("embedded.dat")]
    )
    root.submodels = {
        "sub.ldr": Model(name="sub.ldr", objects=[Piece.place("3001")]),
        "embedded.dat": Model(name="embedded.dat", objects=[Piece.place("3002")]),
    }
    step = root.instruction_document().root.steps[0]
    assert [
        row.part for row in step.added_bill_of_materials(expand_submodels=False)
    ] == ["embedded", "sub.ldr"]
    assert [occ.part_code for occ in step.added_occurrences()] == ["3001", "embedded"]
    assert [
        occ.part_code for occ in step.added_occurrences(expand_submodels=False)
    ] == ["sub.ldr", "embedded"]


def test_manual_document_constructor_keeps_snapshot_compatibility(
    tmp_path: Path,
) -> None:
    root = Model(name="main.ldr", objects=[Piece.place("3001")])
    document = replace(root.instruction_document())
    assert document._resolution_context() is None  # noqa: SLF001
    path = tmp_path / "manual.mpd"
    _write_snapshot_mpd(
        document, section=document.root, step=document.root.steps[0], path=path
    )
    assert "3001.dat" in path.read_text()


def test_dynamic_callout_target_uses_document_resolution() -> None:
    target = Model(name="external.ldr", objects=[Piece.place("3001")])

    class Resolver(Model):
        def submodel_for(self: Self, piece: Piece) -> Model | None:
            return target if piece.reference == "external.ldr" else None

    from ldraw.lines import MetaCommand

    root = Resolver(
        name="main.ldr",
        objects=[
            MetaCommand("LPUB", "CALLOUT BEGIN ASSEMBLED"),
            Piece.place("external.ldr"),
            MetaCommand("LPUB", "CALLOUT END"),
        ],
    )
    assert not list(iter_instruction_issues(root.instruction_document()))
