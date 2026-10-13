"""Iterable providers, forwarding descriptors, cyclic discovery, and snapshots."""

import gc
import pickle
import weakref
from collections.abc import Callable, Iterable, Iterator
from copy import copy, deepcopy
from dataclasses import replace
from functools import cached_property, lru_cache, partialmethod, singledispatchmethod
from pathlib import Path
from types import MethodType
from typing import ClassVar, Never
from unittest.mock import patch

import pytest

from ldraw._model_validation import ModelValidationContext
from ldraw._model_views import _resolution_root, _selected_model
from ldraw.analysis import analyze_model
from ldraw.bom import bill_of_materials, compare_inventory
from ldraw.errors import SubmodelCycleError
from ldraw.instruction_artifacts import _write_snapshot_mpd, instruction_manifest
from ldraw.model import (
    Model,
    ModelOccurrence,
    _iter_occurrences_skip_cycles,
    parse_model,
)
from ldraw.model_summary import ModelSummary
from ldraw.part import ParsedObject
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.validation import _piece_analysis


class RequiredModel(Model):
    """Require constructor state while retaining the normal copying protocols."""

    __slots__ = ("label",)

    def __init__(
        self, *, label: str, name: str = "", objects: Iterable[ParsedObject] = ()
    ) -> None:
        super().__init__(name=name, objects=list(objects))
        self.label = label

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Use slotted state and super() during authoritative traversal."""
        for occurrence in super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        ):
            yield replace(occurrence, part_code=self.label)


class RootDescriptor:
    """Bind a custom descriptor to the receiver's resolution context."""

    def __get__(
        self, instance: Model | None, _owner: type[Model] | None = None
    ) -> object:
        if instance is None:
            return self
        return instance.submodel_for(instance.pieces[0])


class DescriptorModel(Model):
    """Exercise Python descriptors beyond functions and properties."""

    custom_target = RootDescriptor()

    @lru_cache  # noqa: B019 - regression for existing cached method overrides
    def cached_target(self, piece: Piece) -> Model | None:
        """Keep selected and view receiver keys distinct."""
        return self.submodel_for(piece)

    @singledispatchmethod
    def dispatched_target(self, piece: Piece) -> Model | None:
        """Bind the default dispatched implementation to the receiver."""
        return self.submodel_for(piece)

    def _target(self, piece: Piece, *, enabled: bool) -> Model | None:
        return self.submodel_for(piece) if enabled else None

    partial_target = partialmethod(_target, enabled=True)

    @cached_property
    def sources(self) -> dict[str, Model]:
        """Cache a context-dependent value on the correct receiver."""
        return self.submodels

    @property
    def contextual_label(self) -> str:
        """Read and write state through descriptors bound to the view."""
        return f"{self.name}:{len(self.submodels)}"

    @contextual_label.setter
    def contextual_label(self, value: str) -> None:
        self.name = f"{value}:{len(self.submodels)}"

    @contextual_label.deleter
    def contextual_label(self) -> None:
        self.name = f"deleted:{len(self.submodels)}"


def nested_root(selected: Model) -> tuple[Model, Model]:
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001", colour=4)])
    root = Model(
        name="main.ldr",
        submodels={selected.name.casefold(): selected, "leaf.ldr": leaf},
    )
    return root, leaf


def test_general_descriptors_bind_to_views_and_keep_method_overrides() -> None:
    selected = DescriptorModel(name="sub.ldr", objects=[Piece.place("leaf.ldr")])
    root, leaf = nested_root(selected)
    view = root.submodel_view(selected.name)
    piece = selected.pieces[0]
    assert selected.cached_target(piece) is None
    for name in ("cached_target", "dispatched_target", "partial_target"):
        assert getattr(view, name)(piece) is leaf
    assert view.custom_target is leaf
    assert view.contextual_label == "sub.ldr:2"
    view.contextual_label = "changed"
    assert selected.name == "changed:2"
    del view.contextual_label
    assert selected.name == "deleted:2"

    def replacement(self: Model, target: Piece) -> Model | None:
        return self.submodel_for(target)

    selected.cached_target = MethodType(replacement, selected)
    assert view.cached_target(piece) is leaf
    created = view.from_pieces([Piece.place("3002")], name="new.ldr")
    assert type(created) is DescriptorModel
    DescriptorModel.cached_target.cache_clear()


def test_cached_properties_are_isolated_and_explicitly_invalidated() -> None:
    selected = DescriptorModel(name="sub.ldr", objects=[Piece.place("leaf.ldr")])
    assert selected.sources == {}
    first, _ = nested_root(selected)
    second, _ = nested_root(selected)
    left = first.submodel_view(selected.name)
    right = second.submodel_view(selected.name)
    assert left.sources is first.submodels
    assert right.sources is second.submodels
    assert selected.sources == {}
    left.sources = {}
    assert left.sources == {}
    assert right.sources is second.submodels
    del left.sources
    first.submodels = {selected.name: selected}
    assert left.sources is first.submodels
    del left.sources
    with pytest.raises(AttributeError, match="sources"):
        del left.sources
    assert "sources" not in left.__dict__
    assert "sources" in selected.__dict__


@pytest.mark.parametrize("root_view", [False, True])
@pytest.mark.parametrize("operation", [copy, deepcopy, pickle.loads])
def test_copy_and_pickle_preserve_selected_root_graph(
    operation: Callable[..., object], *, root_view: bool
) -> None:
    selected = RequiredModel(
        label="alternate", name="sub.ldr", objects=[Piece.place("leaf.ldr")]
    )
    root, _ = nested_root(selected)
    model = root if root_view else selected
    view = root.submodel_view(model.name)
    restored = (
        operation(pickle.dumps(view)) if operation is pickle.loads else operation(view)
    )
    assert isinstance(restored, Model)
    assert restored._is_submodel_view  # noqa: SLF001
    assert isinstance(restored, type(model))
    if root_view:
        assert _selected_model(restored) is _resolution_root(restored)
    else:
        assert _resolution_root(restored).submodels["sub.ldr"] is _selected_model(
            restored
        )
    assert compare_inventory(restored, bill_of_materials(restored)).matched
    assert (
        next(restored.submodel_view("leaf.ldr").iter_occurrences()).part_code == "3001"
    )
    if operation is copy:
        assert _selected_model(restored) is model
        assert _resolution_root(restored) is root
        model.objects = [Piece.place("3002", colour=4)]
        assert restored.objects is model.objects
    else:
        assert _selected_model(restored) is not model
        assert _resolution_root(restored) is not root


@pytest.mark.parametrize("operation", [copy, deepcopy, pickle.loads])
def test_copy_operations_start_with_empty_derived_caches(
    operation: Callable[..., object],
) -> None:
    selected = DescriptorModel(name="sub.ldr", objects=[Piece.place("leaf.ldr")])
    root, _ = nested_root(selected)
    view = root.submodel_view(selected.name)
    view.sources = {}
    restored = (
        operation(pickle.dumps(view)) if operation is pickle.loads else operation(view)
    )
    assert isinstance(restored, DescriptorModel)
    assert "sources" not in restored.__dict__
    assert restored.sources is _resolution_root(restored).submodels


@pytest.mark.parametrize("operation", [deepcopy, pickle.loads])
def test_view_reconstruction_handles_backreferences(
    operation: Callable[..., object],
) -> None:
    class_root = DescriptorModel(name="main.ldr", objects=[Piece.place("3001")])
    view = class_root.submodel_view(class_root.name)
    class_root.current_view = view
    restored = (
        operation(pickle.dumps(view)) if operation is pickle.loads else operation(view)
    )
    assert isinstance(restored, DescriptorModel)
    assert _resolution_root(restored).current_view is restored
    assert _selected_model(restored) is _resolution_root(restored)


def test_view_creation_and_shallow_copy_do_not_invoke_user_hooks() -> None:
    class HookedModel(Model):
        registry: ClassVar[list[type[Model]]] = []

        def __init_subclass__(cls, *, marker: str) -> None:
            cls.registry.append(cls)
            super().__init_subclass__()

        def __copy__(self) -> Never:
            message = "selected copying hook must not run"
            raise AssertionError(message)

        def __getstate__(self) -> Never:
            message = "selected state hook must not run during creation"
            raise AssertionError(message)

    class Selected(HookedModel, marker="user"):
        pass

    selected = Selected(name="main.ldr")
    with patch.object(
        target=Selected,
        attribute="__init__",
        side_effect=AssertionError("constructor must not run"),
    ):
        view = selected.submodel_view(selected.name)
        restored = copy(view)
    assert isinstance(view, Selected)
    assert isinstance(restored, Selected)
    assert HookedModel.registry == [Selected]
    assert type(view) is type(restored)


def test_underlying_copying_and_state_hooks_are_honored() -> None:
    selected = DescriptorModel(name="sub.ldr")
    root, _ = nested_root(selected)
    view = root.submodel_view(selected.name)
    with (
        patch.object(
            target=DescriptorModel,
            attribute="__deepcopy__",
            create=True,
            side_effect=RuntimeError("underlying deepcopy"),
        ),
        pytest.raises(RuntimeError, match="underlying deepcopy"),
    ):
        deepcopy(view)
    with (
        patch.object(
            target=DescriptorModel,
            attribute="__getstate__",
            side_effect=RuntimeError("underlying state"),
        ),
        pytest.raises(RuntimeError, match="underlying state"),
    ):
        pickle.dumps(view)


def test_generated_classes_have_weak_lifetimes() -> None:
    def make_view() -> tuple[
        Model, weakref.ReferenceType[type[Model]], weakref.ReferenceType[type[Model]]
    ]:
        class TemporaryModel(Model):
            pass

        selected = TemporaryModel(name="main.ldr")
        view = selected.submodel_view(selected.name)
        return view, weakref.ref(TemporaryModel), weakref.ref(type(view))

    view, selected_class, adapter_class = make_view()
    gc.collect()
    assert selected_class() is not None
    assert adapter_class() is type(view)
    del view
    gc.collect()
    assert selected_class() is None
    assert adapter_class() is None


@pytest.mark.parametrize("container", [list, tuple])
def test_custom_iterables_agree_across_bom_analysis_summary_and_comparison(
    container: Callable[[Iterable[ModelOccurrence]], Iterable[ModelOccurrence]],
) -> None:
    class ContainerModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterable[ModelOccurrence]:
            return container(
                super().iter_occurrences(
                    expand_submodels=expand_submodels, include_steps=include_steps
                )
            )

    model = ContainerModel(objects=[Piece.place("3001", colour=4)])
    rows = bill_of_materials(model)
    assert model.bill_of_materials() == rows
    assert compare_inventory(model, rows).matched
    assert list(analyze_model(model).bom) == rows
    assert ModelSummary.from_model(model, parts=None).part_counts == {"3001": 1}


def test_narrower_overrides_work_and_reject_unsupported_explicit_expansion() -> None:
    class NarrowModel(Model):
        def iter_occurrences(
            self, *, include_steps: bool = True
        ) -> list[ModelOccurrence]:
            return list(super().iter_occurrences(include_steps=include_steps))

    model = NarrowModel(objects=[Piece.place("3001", colour=4)])
    rows = model.bill_of_materials()
    assert compare_inventory(model, rows).matched
    assert list(analyze_model(model).bom) == rows
    assert ModelSummary.from_model(model, parts=None).occurrence_count == 1
    with pytest.raises(TypeError, match="does not support expand_submodels=False"):
        list(_iter_occurrences_skip_cycles(model, expand_submodels=False))


def test_iter_conversion_is_inside_cycle_policy_and_never_leaks() -> None:
    class DeferredIterable:
        def __init__(
            self, *, model: Model, expand_submodels: bool, include_steps: bool
        ) -> None:
            self.model = model
            self.expand_submodels = expand_submodels
            self.include_steps = include_steps

        def __iter__(self) -> Iterator[ModelOccurrence]:
            return Model.iter_occurrences(
                self.model,
                expand_submodels=self.expand_submodels,
                include_steps=self.include_steps,
            )

    class DeferredModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterable[ModelOccurrence]:
            return DeferredIterable(
                model=self,
                expand_submodels=expand_submodels,
                include_steps=include_steps,
            )

    model = DeferredModel(
        name="main.ldr", objects=[Piece.place("3001"), Piece.place("main.ldr")]
    )
    assert bill_of_materials(model)[0].quantity == 1
    assert analyze_model(model).summary.occurrence_count == 1
    with pytest.raises(SubmodelCycleError):
        list(model.iter_occurrences())
    events = _iter_occurrences_skip_cycles(model)
    assert next(events).part_code == "3001"
    with pytest.raises(SubmodelCycleError):
        list(model.iter_occurrences())
    events.close()


def test_custom_body_type_errors_are_not_retried() -> None:
    class FailingModel(Model):
        calls = 0

        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Never:
            assert expand_submodels
            assert not include_steps
            self.calls += 1
            message = "custom body"
            raise TypeError(message)

    model = FailingModel()
    with pytest.raises(TypeError, match="custom body"):
        bill_of_materials(model)
    assert model.calls == 1


@pytest.mark.parametrize("failure", [TypeError, ValueError])
def test_opaque_signatures_keep_full_keyword_contract(failure: type[Exception]) -> None:
    class Provider(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            assert expand_submodels
            assert not include_steps
            return super().iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            )

    with patch(target="ldraw._model_cycles.signature", side_effect=failure):
        assert (
            bill_of_materials(Provider(objects=[Piece.place("3001")]))[0].quantity == 1
        )


class FreshResolver(Model):
    """Construct new section identities while referring to the same logical cycle."""

    def __init__(self, *, invalid_closing: bool = False) -> None:
        super().__init__(name="a.ldr", objects=[Piece.place("b.ldr")])
        self.invalid_closing = invalid_closing
        self.calls = 0

    def submodel_for(self, piece: Piece) -> Model | None:
        """Create each edge's target afresh, even when it closes the cycle."""
        self.calls += 1
        if piece.reference == "a.ldr" and self.invalid_closing:
            return parse_model("0 FILE a.ldr\n2 24 nan 0 0 1 1 1\n")
        next_reference = "a.ldr" if piece.reference == "b.ldr" else "b.ldr"
        return Model(name=piece.reference, objects=[Piece.place(next_reference)])


def test_fresh_resolver_cycles_terminate_with_normal_builtin_cycle_error() -> None:
    model = FreshResolver()
    with pytest.raises(SubmodelCycleError):
        compare_inventory(model, [])
    assert model.calls == 2


def test_cycle_closing_new_geometry_is_checked_with_source_location() -> None:
    model = FreshResolver(invalid_closing=True)
    with pytest.raises(ValueError, match=r"a.ldr:2:.*point1.x=nan"):
        compare_inventory(model, [])
    assert model.calls == 2


def test_custom_audits_stop_fresh_cycles_and_keep_authoritative_leaves() -> None:
    known = Model(objects=[Piece.place("3001", colour=4)])

    class CustomFreshResolver(FreshResolver):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            return known.iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            )

    model = CustomFreshResolver()
    assert compare_inventory(model, bill_of_materials(known)).matched
    assert model.calls == 2


def test_same_named_distinct_sibling_sections_are_both_validated() -> None:
    first = Model(name="shared.ldr", objects=[Piece.place("3001")])
    second = parse_model("0 FILE shared.ldr\n2 24 nan 0 0 1 1 1\n")

    class Resolver(Model):
        def submodel_for(self, piece: Piece) -> Model | None:
            return {"first.ldr": first, "second.ldr": second}.get(piece.reference)

    root = Resolver(
        name="main.ldr", objects=[Piece.place("first.ldr"), Piece.place("second.ldr")]
    )
    with pytest.raises(ValueError, match=r"shared.ldr:2:.*point1.x=nan"):
        compare_inventory(root, [])


def test_cycle_closing_section_can_also_have_an_acyclic_route() -> None:
    first = Model(name="a.ldr", objects=[Piece.place("b-entry.ldr")])
    second = Model(name="b.ldr", objects=[Piece.place("closing-a.ldr")])
    closing = Model(name="a.ldr", objects=[Piece.place("bad.dat")])
    alternate = Model(name="d.ldr", objects=[Piece.place("closing-a.ldr")])
    bad = parse_model("0 FILE bad.dat\n2 24 nan 0 0 1 1 1\n")
    targets = {
        "a-entry.ldr": first,
        "b-entry.ldr": second,
        "closing-a.ldr": closing,
        "d-entry.ldr": alternate,
        "bad.dat": bad,
    }

    class Resolver(Model):
        def submodel_for(self, piece: Piece) -> Model | None:
            return targets.get(piece.reference)

    root = Resolver(
        name="main.ldr",
        objects=[Piece.place("a-entry.ldr"), Piece.place("d-entry.ldr")],
    )
    with pytest.raises(ValueError, match=r"bad.dat:2:.*point1.x=nan"):
        ModelValidationContext().ensure_validated(root=root, reachable_only=True)


def test_completed_scopes_skip_scanning_and_declared_completion_is_distinct() -> None:
    model = FreshResolver()
    context = ModelValidationContext()
    context.mark_validated(root=model, reachable_only=False)
    context.ensure_validated(root=model, reachable_only=True)
    assert model.calls == 2
    assert len(context.validated_sections) == 3
    with patch(
        target="ldraw.validation._iter_section_numeric_issues",
        side_effect=AssertionError("completed sections must not be scanned"),
    ):
        context.ensure_validated(root=model, reachable_only=True)
        context.ensure_validated(root=model, reachable_only=False)
    with pytest.raises(ValueError, match="different resolution root"):
        context.ensure_validated(root=Model(), reachable_only=True)


def test_shared_sections_receive_one_source_analysis() -> None:
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001", colour=4)])
    root = Model(name="main.ldr")
    root.add_submodel(leaf)
    root.add_submodel(leaf)
    with patch(
        target="ldraw.validation._piece_analysis", wraps=_piece_analysis
    ) as source:
        assert compare_inventory(root, bill_of_materials(root)).matched
    assert source.call_count == 3


@pytest.mark.parametrize("view_name", ["main.ldr", "sub.ldr"])
def test_instruction_sections_and_manifest_steps_are_unique(view_name: str) -> None:
    source = parse_model(
        "0 FILE main.ldr\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 sub.ldr\n"
        "0 FILE sub.ldr\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 leaf.ldr\n"
        "0 FILE leaf.ldr\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
    )
    document = source.submodel_view(view_name).instruction_document()
    names = [section.name for section in document.sections]
    assert names == (
        ["main.ldr", "sub.ldr", "leaf.ldr"]
        if view_name == "main.ldr"
        else ["sub.ldr", "leaf.ldr"]
    )
    parts = Parts(
        parts_lst=Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst"
    )
    manifest = instruction_manifest(document, parts=parts)
    assert manifest["schema_version"] == 1
    assert [section["name"] for section in manifest["sections"]] == names
    assert all(len(section["steps"]) == 1 for section in manifest["sections"])


@pytest.mark.parametrize("view", [False, True])
def test_snapshots_avoid_duplicate_current_sections_and_keep_other_dependencies(
    tmp_path: Path, *, view: bool
) -> None:
    root = Model(
        name="main.ldr", objects=[Piece.place("sub.ldr"), Piece.place("main.ldr")]
    )
    sub = Model(
        name="sub.ldr", objects=[Piece.place("main.ldr"), Piece.place("sub.ldr")]
    )
    root.submodels = {"sub.ldr": sub}
    document = (root.submodel_view(root.name) if view else root).instruction_document()
    assert [section.name for section in document.sections] == ["main.ldr", "sub.ldr"]
    for section in document.sections:
        path = tmp_path / f"{section.name}.mpd"
        _write_snapshot_mpd(document, section=section, step=section.steps[0], path=path)
        names = [
            line.removeprefix("0 FILE ")
            for line in path.read_text().splitlines()
            if line.startswith("0 FILE ")
        ]
        assert names[0] == section.name
        assert len(names) == len(set(names)) == 2


def test_instruction_sections_include_dynamic_targets_in_discovery_order() -> None:
    external = Model(name="external.ldr", objects=[Piece.place("3001")])

    class Resolver(Model):
        def submodel_for(self, piece: Piece) -> Model | None:
            return external if piece.reference == "external.ldr" else None

    root = Resolver(name="main.ldr", objects=[Piece.place("external.ldr")])
    assert [section.name for section in root.instruction_document().sections] == [
        "main.ldr",
        "external.ldr",
    ]
