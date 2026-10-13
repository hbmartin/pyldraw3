"""Live forwarding, custom occurrence authority, and edge-only validation."""

from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from types import MethodType
from typing import Never
from unittest.mock import patch

import numpy as np
import pytest

from ldraw._model_validation import ModelValidationContext
from ldraw.analysis import analyze_model
from ldraw.bom import bill_of_materials, compare_inventory
from ldraw.errors import SubmodelCycleError
from ldraw.instructions import iter_instruction_issues
from ldraw.model import (
    Model,
    ModelOccurrence,
    _composition_check,
    _iter_occurrences_skip_cycles,
    parse_model,
)
from ldraw.part import parse_ldraw_line
from ldraw.pieces import Piece
from ldraw.validation import _piece_analysis


class RelabeledModel(Model):
    """Require slotted custom state and forbid copying hooks."""

    __slots__ = ("part_code", "resolver_cache")

    def __init__(self, *, part_code: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.part_code = part_code
        self.resolver_cache = {}

    def __copy__(self) -> Never:
        message = "a view must not invoke a copying hook"
        raise AssertionError(message)

    def __getstate__(self) -> Never:
        message = "a view must not invoke a state hook"
        raise AssertionError(message)

    @property
    def label(self) -> str:
        """Read current state through a property bound to the view."""
        return self.part_code

    def submodel_for(self, piece: Piece) -> Model | None:
        """Cache resolution against this model's own table."""
        if piece.reference not in self.resolver_cache:
            self.resolver_cache[piece.reference] = super().submodel_for(piece)
        return self.resolver_cache[piece.reference]

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Keep the custom part identity authoritative."""
        for occurrence in super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        ):
            yield replace(occurrence, part_code=self.part_code)


@pytest.mark.parametrize("root_view", [False, True])
def test_views_forward_state_without_copying_and_keep_root_resolution(
    *, root_view: bool
) -> None:
    selected = RelabeledModel(
        part_code="alternate", name="selected.ldr", objects=[Piece.place("leaf.ldr")]
    )
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001", colour=4)])
    root = selected if root_view else Model(name="main.ldr")
    root.submodels = {"selected.ldr": selected, "leaf.ldr": leaf}
    view = root.submodel_view(selected.name)
    assert isinstance(view, RelabeledModel)
    assert type(view) is not type(selected)
    assert next(view.iter_occurrences()).reference == "3001.dat"
    assert compare_inventory(view, bill_of_materials(view)).matched
    if not root_view:
        assert selected.resolver_cache == {}
        assert selected.submodel_for(selected.pieces[0]) is None
    selected.part_code = "changed"
    assert view.label == "changed"
    assert next(view.iter_occurrences()).part_code == "changed"
    view.part_code = "written-through"
    assert selected.part_code == "written-through"
    selected.objects = [Piece.place("3002", colour=4)]
    assert view.objects is selected.objects
    piece = selected.pieces[0]
    selected._source_lines = {piece: 17}  # noqa: SLF001
    assert view.source_line_for(piece) == 17
    view.objects = [Piece.place("3003", colour=4)]
    assert selected.pieces[0].part == "3003"
    assert view.bill_of_materials() == bill_of_materials(view)


def test_nested_views_retain_original_root_and_live_table_replacements() -> None:
    selected = RelabeledModel(
        part_code="alternate", name="selected.ldr", objects=[Piece.place("leaf.ldr")]
    )
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001", colour=4)])
    root = Model(
        name="main.ldr", submodels={"selected.ldr": selected, "leaf.ldr": leaf}
    )
    view = root.submodel_view("selected.ldr")
    nested = view.submodel_view("leaf.ldr")
    assert nested.submodel_view("main.ldr").objects is root.objects
    root.submodels = {"selected.ldr": selected, "leaf.ldr": leaf}
    assert nested.submodels is root.submodels
    view.submodels = {"leaf.ldr": leaf}
    assert root.submodels is view.submodels
    assert selected.submodels == {}
    with pytest.raises(AttributeError, match="selected-section scope"):
        view._is_submodel_view = False  # noqa: SLF001
    with pytest.raises(AttributeError, match="view binding"):
        del view._view_root  # noqa: SLF001
    with pytest.raises(AttributeError, match="view binding"):
        view._view_root = Model()  # noqa: SLF001
    assert view._view_selected is selected  # noqa: SLF001


def test_view_forwards_added_attributes_deletion_and_instance_methods() -> None:
    class StatefulModel(Model):
        pass

    selected = StatefulModel(objects=[Piece.place("3001", colour=4)])
    selected.extra = "first"
    view = selected.submodel_view("")
    selected.extra = "second"
    assert view.extra == "second"
    del view.extra
    assert not hasattr(selected, "extra")

    def occurrences(self, **kwargs) -> Iterator[ModelOccurrence]:
        for occurrence in Model.iter_occurrences(self, **kwargs):
            yield replace(occurrence, part_code="instance-override")

    selected.iter_occurrences = MethodType(occurrences, selected)
    assert next(view.iter_occurrences()).part_code == "instance-override"
    assert compare_inventory(view, view.bill_of_materials()).matched
    selected.iter_occurrences = lambda **_kwargs: iter(())
    assert view.bill_of_materials() == []
    assert compare_inventory(view, []).matched


def test_custom_bom_and_analysis_honor_relabelling_and_delegated_cycles() -> None:
    model = RelabeledModel(
        part_code="alternate",
        name="main.ldr",
        objects=[Piece.place("3001", colour=4), Piece.place("main.ldr")],
    )
    rows = bill_of_materials(model)
    assert [(row.part, row.quantity) for row in rows] == [("alternate", 1)]
    assert model.bill_of_materials() == rows
    analysis = analyze_model(model)
    assert list(analysis.bom) == rows
    assert analysis.summary.part_counts == {"alternate": 1}
    assert len(analysis.diagnostics) == 1
    with pytest.raises(SubmodelCycleError):
        list(model.iter_occurrences())
    with pytest.raises(SubmodelCycleError):
        compare_inventory(model, rows)
    tolerant = _iter_occurrences_skip_cycles(model)
    assert next(tolerant).part_code == "alternate"
    with pytest.raises(SubmodelCycleError):
        list(model.iter_occurrences())
    tolerant.close()


def test_view_class_factories_construct_the_original_class() -> None:
    source = Model(name="main.ldr")
    view = source.submodel_view(source.name)
    created = view.from_pieces([Piece.place("3001")], name="new.ldr")
    assert type(created) is Model
    assert created.name == "new.ldr"
    assert source.objects == []


def test_custom_exceptions_are_not_suppressed_and_cycle_policy_is_reset() -> None:
    class FailingModel(Model):
        def iter_occurrences(self, **_kwargs) -> Never:
            name = "custom failure"
            raise SubmodelCycleError(name)

    with pytest.raises(SubmodelCycleError, match="custom failure"):
        bill_of_materials(FailingModel())
    cyclic = Model(name="main.ldr", objects=[Piece.place("main.ldr")])
    with pytest.raises(SubmodelCycleError):
        list(cyclic.iter_occurrences())


class DynamicModel(Model):
    """Resolve references from a separate mapping with lookup-style misses."""

    def __init__(self, *, targets: dict[str, Model], **kwargs) -> None:
        super().__init__(**kwargs)
        self.targets = targets

    def submodel_for(self, piece: Piece) -> Model | None:
        """Permit external targets, including targets ending in .dat."""
        return self.targets[piece.reference]


@pytest.mark.parametrize("view", [False, True])
@pytest.mark.parametrize(
    "geometry",
    [
        "2 24 nan 0 0 1 1 1",
        "3 24 nan 0 0 1 1 1 2 2 2",
        "4 24 nan 0 0 1 1 1 2 2 2 3 3 3",
        "5 24 nan 0 0 1 1 1 2 2 2 3 3 3",
    ],
)
def test_custom_resolution_checks_external_geometry_in_roots_and_views(
    geometry: str, *, view: bool
) -> None:
    external = parse_model(f"0 FILE external.dat\n{geometry}\n")
    root = DynamicModel(
        name="main.ldr",
        targets={"external.dat": external},
        objects=[Piece.place("external.dat")],
    )
    model = root.submodel_view(root.name) if view else root
    with pytest.raises(ValueError, match=r"external.dat:2:.*point1.x=nan"):
        compare_inventory(model, [])


def test_dynamic_dat_submodels_expand_and_mapping_part_misses_are_leaves() -> None:
    external = Model(name="external.dat", objects=[Piece.place("3001", colour=4)])
    root = DynamicModel(
        targets={"external.dat": external}, objects=[Piece.place("external.dat")]
    )
    assert next(root.iter_occurrences()).reference == "3001.dat"
    assert compare_inventory(root, bill_of_materials(root)).matched
    assert compare_inventory(root.submodel_view(""), bill_of_materials(root)).matched


def test_mapping_misses_are_shared_by_instruction_and_structure_diagnostics() -> None:
    piece = Piece.place("child.mpd")
    piece.part, piece.suffix = "child.mpd", ""

    class StemResolver(Model):
        def submodel_for(self, _piece: Piece) -> Never:
            raise KeyError("child")

    model = StemResolver(name="main.ldr", objects=[piece])
    assert next(model.iter_occurrences()).reference == "child.mpd"
    issues = list(iter_instruction_issues(model.instruction_document()))
    assert [issue.code for issue in issues] == ["unknown-submodel"]


@pytest.mark.parametrize("key", ["3001.dat", "3001", "3001.DAT"])
def test_custom_resolver_lookup_misses_do_not_break_authoritative_providers(
    key: str,
) -> None:
    known = Model(objects=[Piece.place("3001", colour=4)])

    class Provider(Model):
        def submodel_for(self, _piece: Piece) -> Never:
            raise KeyError(key)

        def iter_occurrences(self, **kwargs) -> Iterator[ModelOccurrence]:
            return known.iter_occurrences(**kwargs)

    assert compare_inventory(
        Provider(objects=known.objects), bill_of_materials(known)
    ).matched


@pytest.mark.parametrize("args", [("unrelated",), (17,), ("3001.dat", "extra")])
def test_unrelated_resolver_errors_remain_visible(args: tuple[object, ...]) -> None:
    class BrokenResolver(Model):
        def submodel_for(self, _piece: Piece) -> Never:
            raise KeyError(*args)

    with pytest.raises(KeyError) as raised:
        compare_inventory(BrokenResolver(objects=[Piece.place("3001")]), [])
    assert raised.value.args == args


def test_section_completion_does_not_claim_dynamic_reachable_geometry() -> None:
    external = Model(
        name="external.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")]
    )
    root = DynamicModel(
        targets={"external.ldr": external}, objects=[Piece.place("external.ldr")]
    )
    context = ModelValidationContext()
    context.mark_validated(root=root, reachable_only=False)
    with pytest.raises(ValueError, match=r"external.ldr.*point1.x=nan"):
        context.ensure_validated(root=root, reachable_only=True)


def test_context_binds_views_to_original_root_without_conflating_sections() -> None:
    selected = Model(name="selected.ldr", objects=[Piece.place("3001", colour=4)])
    orphan = Model(name="orphan.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    root = Model(
        name="main.ldr", submodels={"selected.ldr": selected, "orphan.ldr": orphan}
    )
    context = ModelValidationContext()
    context.ensure_validated(
        root=root.submodel_view("selected.ldr"), reachable_only=True
    )
    assert context.resolve(root=root, piece=Piece.place("selected.ldr")) is selected
    with pytest.raises(ValueError, match=r"orphan.ldr"):
        context.ensure_validated(root=root, reachable_only=False)


def test_reachable_completion_records_real_sections_and_stops_cycles() -> None:
    root = Model(name="main.ldr", objects=[Piece.place("child.ldr")])
    child = Model(name="child.ldr", objects=[Piece.place("main.ldr")])
    orphan = Model(name="orphan.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    root.submodels = {"child.ldr": child, "orphan.ldr": orphan}
    view = root.submodel_view(root.name)
    context = ModelValidationContext()
    context.ensure_validated(root=view, reachable_only=True)
    context.mark_validated(root=view, reachable_only=True)
    assert context.validated_sections == {id(root), id(child)}
    with pytest.raises(ValueError, match=r"orphan.ldr.*point1.x=nan"):
        context.ensure_validated(root=root, reachable_only=False)


def test_cached_edge_lookup_rejects_another_resolution_root() -> None:
    section = Model(name="child.ldr")
    root = Model(submodels={"child.ldr": section})
    context = ModelValidationContext()
    assert context.edges(root=root, section=section) == ()
    with pytest.raises(ValueError, match="different resolution root"):
        context.edges(root=Model(), section=section)


class FilteredModel(Model):
    """Filter part leaves while preserving ordinary submodel expansion."""

    def iter_occurrences(self, **kwargs) -> Iterator[ModelOccurrence]:
        """Omit the part whose composed transform can overflow."""
        for occurrence in super().iter_occurrences(**kwargs):
            if occurrence.part_code != "3001":
                yield occurrence


def test_filtered_part_overflow_is_ignored_but_emitted_overflow_is_rejected() -> None:
    source = parse_model(
        "0 FILE main.ldr\n"
        "1 4 0 0 0 1e200 0 0 0 1 0 0 0 1 child.ldr\n"
        "0 FILE child.ldr\n"
        "1 16 1e200 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
    )
    filtered = FilteredModel(
        name=source.name, objects=source.objects, submodels=source.submodels
    )
    with np.errstate(over="ignore", invalid="ignore"):
        assert bill_of_materials(filtered) == []
        assert compare_inventory(filtered, []).matched
        with pytest.raises(ValueError, match=r"position.x=inf"):
            compare_inventory(source, [])


def test_filtered_submodel_overflow_is_still_rejected() -> None:
    source = parse_model(
        "0 FILE main.ldr\n"
        "1 4 0 0 0 1e200 0 0 0 1 0 0 0 1 middle.ldr\n"
        "0 FILE middle.ldr\n"
        "1 16 0 0 0 1e200 0 0 0 1 0 0 0 1 empty.ldr\n"
        "0 FILE empty.ldr\n"
    )
    filtered = FilteredModel(
        name=source.name, objects=source.objects, submodels=source.submodels
    )
    with (
        np.errstate(over="ignore", invalid="ignore"),
        pytest.raises(ValueError, match=r"middle.ldr:4:.*matrix\[0\]\[0\]=inf"),
    ):
        compare_inventory(filtered, [])


def test_edge_audit_discovers_sections_once_and_never_composes_part_leaves() -> None:
    known = Model(objects=[Piece.place("3001", colour=4) for _ in range(10)])
    resolutions = Counter()
    traversals = Counter()

    class Provider(Model):
        def submodel_for(self, piece: Piece) -> Model | None:
            resolutions[piece] += 1
            return super().submodel_for(piece)

        def iter_occurrences(self, **kwargs) -> Iterator[ModelOccurrence]:
            traversals["provider"] += 1
            return known.iter_occurrences(**kwargs)

    leaf = Model(
        name="leaf.ldr", objects=[Piece.place("3001", colour=4) for _ in range(5)]
    )
    middle = Model(name="middle.ldr")
    middle.add_submodel(leaf)
    root = Provider(name="main.ldr")
    root.add_submodel(middle)
    root.add_submodel(middle)
    with (
        patch("ldraw.validation._piece_analysis", wraps=_piece_analysis) as sources,
        patch(
            "ldraw.model._composition_check", wraps=_composition_check
        ) as compositions,
    ):
        assert compare_inventory(root, bill_of_materials(known)).matched
    assert sources.call_count == 8
    assert compositions.call_count == 2
    assert len(resolutions) == 8
    assert set(resolutions.values()) == {1}
    assert traversals == {"provider": 1}


@pytest.mark.parametrize("suffix", [".ldr", ".LDR", ".mpd", ".MPD"])
def test_instruction_validation_uses_full_mutated_reference(suffix: str) -> None:
    piece = Piece.place("3001")
    piece.part, piece.suffix = f"child{suffix}", ""
    model = Model(name="main.ldr", objects=[piece])
    issues = list(iter_instruction_issues(model.instruction_document()))
    assert [issue.code for issue in issues] == ["unknown-submodel"]
