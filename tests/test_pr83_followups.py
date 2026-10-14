"""Complete numeric discovery, instruction contexts and forwarding construction."""

from __future__ import annotations

import gc
import pickle
import random
from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar, Self
from unittest.mock import patch
from weakref import ref

import pytest

from ldraw import _model_views
from ldraw._instruction_resolution import InstructionResolution
from ldraw._model_validation import ModelValidationContext
from ldraw._model_views import _resolution_root, _selected_model
from ldraw.bom import compare_inventory
from ldraw.errors import DuplicateSubmodelError, SubmodelCycleError
from ldraw.geometry import Vector
from ldraw.instructions import InstructionDocument, iter_instruction_issues
from ldraw.lines import MetaCommand
from ldraw.model import Model, parse_model, parse_model_result
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref
from ldraw.validation import _piece_analysis

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ldraw.model import ModelOccurrence


class GraphResolver(Model):
    """Resolve by source identity while exposing an authoritative empty inventory."""

    def __init__(self: Self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.targets: dict[Piece, Model] = {}

    def submodel_for(self: Self, piece: Piece) -> Model | None:
        """Resolve only the source placements registered for this graph."""
        return self.targets.get(piece)

    def iter_occurrences(self: Self, **_flags: bool) -> Iterable[ModelOccurrence]:
        """Expose an empty authoritative inventory independently of the sources."""
        return ()


def resolved_graph(*, names: list[str], edges: list[list[int]]) -> list[Model]:
    root = GraphResolver(name=names[0])
    nodes: list[Model] = [root, *(Model(name=name) for name in names[1:])]
    for source, outgoing in enumerate(edges):
        for index, target in enumerate(outgoing):
            piece = Piece.place(f"edge-{source}-{index}.ldr")
            nodes[source].objects.append(piece)
            root.targets[piece] = nodes[target]
    return nodes


def exhaustive_sources(*, root: GraphResolver) -> set[int]:
    """Walk exhaustively without merging context-sensitive states."""
    visited: set[int] = set()
    explored: set[tuple[int, frozenset[str]]] = set()

    def walk(*, section: Model, ancestry: frozenset[str]) -> None:
        visited.add(id(section))
        name = normalize_ref(section.name)
        if name in ancestry or (state := (id(section), ancestry)) in explored:
            return
        explored.add(state)
        for piece in section.pieces:
            if target := root.targets.get(piece):
                walk(section=target, ancestry=ancestry | {name})

    walk(section=root, ancestry=frozenset())
    return visited


def test_discovery_rejects_nan_after_blockers_change() -> None:
    nodes = resolved_graph(
        names=[
            "root.ldr",
            "a.ldr",
            "e.ldr",
            "c.ldr",
            "d.ldr",
            "e.ldr",
            "e.ldr",
            "a.ldr",
        ],
        edges=[[2, 4], [3], [3], [5], [1, 3], [7], [], [6]],
    )
    bad = parse_model("0 FILE e.ldr\n2 24 nan 0 0 1 1 1\n")
    nodes[6].objects = bad.objects
    nodes[6]._object_source_lines = bad._object_source_lines  # noqa: SLF001
    root = nodes[0]
    with pytest.raises(ValueError, match=r"e.ldr:2:.*point1.x=nan"):
        ModelValidationContext().ensure_validated(root=root, reachable_only=True)
    with pytest.raises(ValueError, match=r"e.ldr:2:.*point1.x=nan"):
        compare_inventory(root, [])


@pytest.mark.parametrize("seed", range(5))
def test_discovery_matches_exhaustive_oracle(seed: int) -> None:
    randomizer = random.Random(seed)
    for _ in range(4_000):
        size = randomizer.randrange(start=6, stop=12)
        names = [
            "root.ldr",
            *(f"{randomizer.choice('abcde')}.ldr" for _ in range(size - 1)),
        ]
        edges = [
            [
                randomizer.randrange(start=1, stop=size)
                for _ in range(randomizer.randrange(start=1, stop=4))
            ]
            for _ in range(size)
        ]
        nodes = resolved_graph(names=names, edges=edges)
        root = nodes[0]
        assert isinstance(root, GraphResolver)
        context = ModelValidationContext()
        actual = {
            id(section) for section in context.sections(root=root, reachable_only=True)
        }
        assert actual == exhaustive_sources(root=root)


def test_numeric_discovery_handles_deep_graph_without_recursive_calls() -> None:
    size = 1_200
    nodes = resolved_graph(
        names=[f"section-{index}.ldr" for index in range(size)],
        edges=[[index + 1] if index + 1 < size else [] for index in range(size)],
    )
    context = ModelValidationContext()
    with patch(
        target="ldraw.validation._piece_analysis", wraps=_piece_analysis
    ) as analysis:
        context.ensure_validated(root=nodes[0], reachable_only=True)
    assert len(context.validated_sections) == size
    assert len(context._edges) == size  # noqa: SLF001
    assert analysis.call_count == size - 1
    context.ensure_validated(root=nodes[0], reachable_only=True)


def test_declared_discovery_keeps_unreferenced_section_and_identity_cycles() -> None:
    root = Model(name="main.ldr")
    orphan = parse_model("0 FILE orphan.ldr\n2 24 nan 0 0 1 1 1\n")
    root.submodels = {"main.ldr": root, "orphan.ldr": orphan}
    with pytest.raises(ValueError, match=r"orphan.ldr:2:.*point1.x=nan"):
        compare_inventory(root, [])


def dynamic_instruction_root() -> GraphResolver:
    """Expose resolved models that differ from the declared source table."""
    first = Piece.place("child.ldr")
    second = Piece.place("external.ldr")
    root = GraphResolver(
        name="main.ldr",
        objects=[first, second, Piece.place("3004")],
        submodels={"child.ldr": Model(name="child.ldr", objects=[Piece.place("3001")])},
    )
    root.targets = {
        first: Model(name="child.ldr", objects=[Piece.place("3002")]),
        second: Model(name="external.ldr", objects=[Piece.place("3003")]),
    }
    return root


def test_instruction_replacement_retains_resolution_and_occurrence_authority() -> None:
    document = dynamic_instruction_root().instruction_document()
    step = document.root.steps[0]
    copied = replace(step)
    assert copied == step
    assert copied._resolution is step._resolution  # noqa: SLF001
    assert [occ.part_code for occ in copied.added_occurrences()] == [
        "3002",
        "3003",
        "3004",
    ]
    assert copied.added_bill_of_materials() == step.added_bill_of_materials()
    assert [occ.part_code for occ in copied.cumulative_occurrences()] == [
        "3002",
        "3003",
        "3004",
    ]
    copied_document = replace(document)
    assert copied_document._resolution is not document._resolution  # noqa: SLF001
    assert copied_document._resolution.context is document._resolution.context  # noqa: SLF001
    assert copied_document.root.steps[0].objects is step.objects


def test_document_context_rebinding_is_explicit_and_immutable() -> None:
    root = dynamic_instruction_root()
    document = root.instruction_document()
    context = InstructionResolution(root=root)
    rebound = replace(document, _resolution=context)
    assert rebound.root.steps[0]._resolution.context is context.context  # noqa: SLF001
    assert document.root.steps[0]._resolution is not context  # noqa: SLF001
    assert rebound.sections[0] is rebound.root
    assert (
        rebound.root.steps[0].added_bill_of_materials()
        == document.root.steps[0].added_bill_of_materials()
    )
    with pytest.raises(ValueError, match="different document root"):
        replace(document, _resolution=InstructionResolution(root=Model()))
    manual = InstructionDocument(
        root=document.root,
        sections=document.sections,
        orphan_sections=document.orphan_sections,
        model=root,
    )
    assert manual.root.steps[0]._resolution is manual._resolution  # noqa: SLF001
    assert manual.root.steps[0] is not document.root.steps[0]
    assert (
        manual.root.steps[0].added_bill_of_materials()
        == document.root.steps[0].added_bill_of_materials()
    )


@pytest.mark.parametrize("expanded", [False, True])
def test_step_dependency_tables_are_owned_and_contain_only_encountered_targets(
    *,
    expanded: bool,
) -> None:
    root = dynamic_instruction_root()
    root.submodels["unused.ldr"] = Model(name="unused.ldr")
    step = root.instruction_document().root.steps[0]
    occurrences = step.added_occurrences(expand_submodels=expanded)
    source = next(occ.source_model for occ in occurrences if occ.part_code == "3004")
    assert source.submodels is not root.submodels
    assert set(source.submodels) == (
        {"child.ldr", "external.ldr"} if expanded else set()
    )
    text = source.to_ldraw()
    assert "unused.ldr" not in text
    if expanded:
        assert "3002.dat" in text
        assert "3001.dat" not in text
    else:
        assert "0 FILE" not in text
    source.submodels.clear()
    source.submodels["injected.ldr"] = Model(name="injected.ldr")
    assert "injected.ldr" not in root.submodels
    assert "child.ldr" in root.submodels


def test_cyclic_step_inspection_keeps_root_reference_and_finishes_diagnostics() -> None:
    root = Model(name="main.ldr", objects=[Piece.place("sub.ldr")])
    root.submodels["sub.ldr"] = Model(
        name="sub.ldr", objects=[Piece.place("3001"), Piece.place("main.ldr")]
    )
    document = root.instruction_document()
    step = document.section("sub.ldr").steps[0]
    assert [occ.part_code for occ in step.added_occurrences()] == ["3001", "main.ldr"]
    assert {row.part for row in step.added_bill_of_materials()} == {"3001", "main.ldr"}
    issues = list(iter_instruction_issues(document, max_parts=1))
    assert "cyclic-submodel" in {issue.code for issue in issues}
    assert "step-too-large" in {issue.code for issue in issues}
    with pytest.raises(SubmodelCycleError):
        list(root.iter_occurrences())


def test_non_root_cycle_leaf_preserves_composed_transform_and_location() -> None:
    root = parse_model(
        "0 FILE main.ldr\n1 4 10 0 0 1 0 0 0 1 0 0 0 1 a.ldr\n"
        "0 FILE a.ldr\n1 16 20 0 0 1 0 0 0 1 0 0 0 1 b.mpd\n"
        "0 FILE b.mpd\n1 16 30 0 0 1 0 0 0 1 0 0 0 1 a.ldr\n"
    )
    document = root.instruction_document()
    occurrence = document.root.steps[0].added_occurrences()[0]
    assert occurrence.part_code == "a.ldr"
    assert occurrence.position == Vector(60, 0, 0)
    assert occurrence.colour.code == 4
    assert occurrence.source_model.name == "b.mpd"
    assert occurrence.source_line == 6
    assert len(occurrence.path) == 3
    assert [row.part for row in document.root.steps[0].added_bill_of_materials()] == [
        "a.ldr"
    ]
    (cumulative,) = document.root.steps[0].cumulative_occurrences()
    assert cumulative.part_code == occurrence.part_code
    assert cumulative.position == occurrence.position
    assert cumulative.source_model is occurrence.source_model
    assert cumulative.source_line == occurrence.source_line
    assert "cyclic-submodel" in {
        issue.code for issue in iter_instruction_issues(document, max_parts=10)
    }


def test_callout_resolves_actual_pieces_not_an_incidental_alias() -> None:
    alias = Piece.place("alias.ldr")
    missing = Piece.place("external.ldr")
    root = GraphResolver(
        name="main.ldr",
        objects=[
            alias,
            MetaCommand("LPUB", "CALLOUT BEGIN"),
            missing,
            MetaCommand("LPUB", "CALLOUT END"),
        ],
    )
    root.targets[alias] = Model(name="external.ldr", objects=[Piece.place("3001")])
    document = root.instruction_document()
    assert {"empty-callout", "unknown-submodel"} <= {
        issue.code for issue in iter_instruction_issues(document)
    }
    callout = document.root.steps[0].callouts[0]
    assert callout._pieces == (missing,)  # noqa: SLF001
    assert replace(callout)._pieces == (missing,)  # noqa: SLF001
    assert "_pieces" not in repr(callout)


def test_identity_sensitive_callouts_and_manual_source_recovery() -> None:
    outside = Piece.place("same.ldr")
    inside = Piece.place("same.ldr")
    root = GraphResolver(
        name="main.ldr",
        objects=[
            outside,
            MetaCommand("LPUB", "CALLOUT BEGIN"),
            inside,
            MetaCommand("LPUB", "CALLOUT END"),
        ],
    )
    root.targets[outside] = Model(name="same.ldr")
    document = root.instruction_document()
    assert "empty-callout" in {
        issue.code for issue in iter_instruction_issues(document)
    }
    callout = document.root.steps[0].callouts[0]
    valid_root = GraphResolver(name="main.ldr", objects=[inside])
    valid_root.targets[inside] = Model(name="same.ldr")
    valid_document = valid_root.instruction_document()
    manual_callout = replace(callout, _pieces=None)
    manual_step = replace(valid_document.root.steps[0], callouts=(manual_callout,))
    section = replace(valid_document.root, steps=(manual_step,))
    manual_document = replace(valid_document, root=section, sections=(section,))
    assert "empty-callout" not in {
        issue.code for issue in iter_instruction_issues(manual_document)
    }
    missing_callout = replace(manual_callout, references=("missing.ldr",))
    section = replace(
        section, steps=(replace(manual_step, callouts=(missing_callout,)),)
    )
    missing_document = replace(valid_document, root=section, sections=(section,))
    assert "empty-callout" in {
        issue.code for issue in iter_instruction_issues(missing_document)
    }


def test_callout_fragments_keep_source_pieces_across_steps() -> None:
    first = Piece.place("first.ldr")
    second = Piece.place("second.ldr")
    from ldraw.lines import Comment

    root = GraphResolver(
        name="main.ldr",
        objects=[
            MetaCommand("LPUB", "CALLOUT BEGIN"),
            first,
            Comment("STEP"),
            second,
            MetaCommand("LPUB", "CALLOUT END"),
        ],
    )
    root.targets = {first: Model(name="first.ldr"), second: Model(name="second.ldr")}
    document = root.instruction_document()
    assert document.root.steps[0].callouts[0]._pieces == (first,)  # noqa: SLF001
    assert document.root.steps[1].callouts[0]._pieces == (first, second)  # noqa: SLF001
    assert not list(iter_instruction_issues(document))


@dataclass(slots=True, eq=False)
class FactoryModel(Model):
    """Require a constructor field and rebuild using the actual receiver type."""

    label: str = field(kw_only=True)

    def rebuild(self: Self) -> Self:
        """Construct a normal instance even when this receiver is a live view."""
        return type(self)(
            name="replacement.ldr", objects=self.objects, label=self.label
        )

    @staticmethod
    def plain_static() -> int:
        """Expose a standard descriptor with no receiver-side caching."""
        return 7


def test_adapter_construction_preserves_factories_and_copy_graphs() -> None:
    selected = FactoryModel(
        name="sub.ldr", objects=[Piece.place("leaf.ldr")], label="original"
    )
    root = Model(
        name="main.ldr",
        submodels={
            selected.name: selected,
            "leaf.ldr": Model(name="leaf.ldr", objects=[Piece.place("3001")]),
        },
    )
    view = root.submodel_view(selected.name)
    constructed = type(view)(name="new.ldr", label="new")
    assert type(constructed) is FactoryModel
    assert constructed.label == "new"
    assert type(view.rebuild()) is FactoryModel
    assert isinstance(view, FactoryModel)
    assert type(replace(view)) is FactoryModel
    assert repr(view).startswith("FactoryModel(")
    assert _selected_model(copy(view)) is selected
    for copied in (deepcopy(view), pickle.loads(pickle.dumps(view))):  # noqa: S301 - trusted local roundtrip
        assert isinstance(copied, FactoryModel)
        assert _resolution_root(copied) is not root
        assert copied.label == "original"
        assert [occ.part_code for occ in copied.iter_occurrences()] == ["3001"]
    nested = view.submodel_view("leaf.ldr")
    assert type(type(nested)(name="new.ldr")) is Model


def test_constructor_dispatch_calls_metaclass_once_and_skips_creation_hooks() -> None:
    events: list[tuple[str, str]] = []

    class Registry(type):
        def __new__(
            mcls: type[Registry],
            name: str,
            bases: tuple[type, ...],
            namespace: dict[str, object],
            *,
            required: str,
        ) -> Registry:
            assert required == "selected"
            events.append(("create", name))
            return super().__new__(mcls, name, bases, namespace)

        def __init__(
            cls: Registry,
            name: str,
            bases: tuple[type, ...],
            namespace: dict[str, object],
            *,
            required: str,
        ) -> None:
            assert required == "selected"
            events.append(("initialize", name))
            super().__init__(name, bases, namespace)

        def __init_subclass__(cls: type[Registry], *, required: str) -> None:
            events.append(("metaclass-subclass", required))

        def __call__(cls: Registry, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - arbitrary constructors
            events.append(("construct", cls.__name__))
            return super().__call__(*args, **kwargs)

    class Selected(FactoryModel, metaclass=Registry, required="selected"):
        def __init_subclass__(cls: type[Self], *, required: str) -> None:
            events.append(("subclass", required))

    selected = Selected(name="sub.ldr", label="source")
    root = Model(name="main.ldr", submodels={selected.name: selected})
    events.clear()
    view = root.submodel_view(selected.name)
    assert not events
    assert isinstance(type(view), Registry)
    result = view.rebuild()
    assert type(result) is Selected
    assert events == [("construct", "Selected")]
    events.clear()
    assert _selected_model(copy(view)) is selected
    assert not events


def test_generated_adapter_and_dispatcher_are_weakly_owned() -> None:
    def temporary_types() -> tuple[object, object, object]:
        class Temporary(Model):
            pass

        selected = Temporary(name="sub.ldr")
        root = Model(name="main.ldr", submodels={selected.name: selected})
        view = root.submodel_view(selected.name)
        return ref(Temporary), ref(type(view)), ref(type(type(view)))

    references = temporary_types()
    gc.collect()
    assert all(reference() is None for reference in references)


def test_plain_descriptor_binding_skips_context_but_custom_staticmethods_keep_it() -> (
    None
):
    class CachingStatic(staticmethod):
        def __get__(
            self: Self, instance: Model, _owner: type[Model] | None = None
        ) -> int:
            instance.cached_static = 9
            return 9

    class Selected(FactoryModel):
        cached_static: ClassVar[CachingStatic] = CachingStatic(lambda: None)

    selected = Selected(name="sub.ldr", label="original")
    view = Model(name="main.ldr", submodels={selected.name: selected}).submodel_view(
        selected.name
    )
    with patch.object(
        target=_model_views,
        attribute="_bound_descriptor",
        wraps=_model_views._bound_descriptor,  # noqa: SLF001
    ) as guarded:
        assert view.plain_static() == 7
        assert view.rebuild().label == "original"
        assert not guarded.call_count
        assert view.cached_static == 9
        assert guarded.call_count == 1
    assert "cached_static" not in selected.__dict__
    assert view.__dict__["cached_static"] == 9
    replacement = staticmethod(lambda: 11)
    with patch.object(target=Selected, attribute="plain_static", new=replacement):
        assert view.plain_static() == 11


def test_serialization_keeps_selected_section_once_and_collapses_aliases() -> None:
    selected = Model(name="Sub.LDR", objects=[Piece.place("leaf.ldr")])
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001")])
    root = Model(
        name="main.ldr",
        submodels={"sub.ldr": selected, "leaf.ldr": leaf, "alias.ldr": leaf},
    )
    view = root.submodel_view(selected.name)
    for model in (view, replace(view), root.submodel_view(root.name)):
        text = model.to_ldraw()
        assert text.count("0 FILE Sub.LDR") == 1
        assert text.count("0 FILE leaf.ldr") == 1
        report = parse_model_result(text)
        assert report.complete
        assert report.model is not None
        assert report.model.name == model.name
    changed = replace(view, objects=[Piece.place("3002")])
    parsed = parse_model(changed.to_ldraw())
    assert parsed.pieces[0].part == "3002"
    assert parsed.name == "Sub.LDR"


def test_serialization_rejects_conflicting_dependencies_and_preserves_existing_file(
    tmp_path: Path,
) -> None:
    model = Model(
        name="main.ldr",
        submodels={
            "first.ldr": Model(name="folder\\CHILD.LDR"),
            "second.ldr": Model(name="folder/child.ldr"),
        },
    )
    path = tmp_path / "model.mpd"
    path.write_text("original")
    with pytest.raises(DuplicateSubmodelError, match=r"child.ldr"):
        model.save(path)
    assert path.read_text() == "original"
