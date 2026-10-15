"""Isolated instruction bindings, directional copies and scoped export work."""

from __future__ import annotations

import gc
import json
import pickle
import random
from copy import copy, deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self, get_type_hints
from unittest.mock import patch
from weakref import ref

import pytest

from ldraw._instruction_export import _ExportPreparation, _ExportState
from ldraw._instruction_resolution import InstructionResolution
from ldraw._model_definitions import _DefinitionRegistry, _SourceOrigin
from ldraw._model_structure import iter_structure_edges
from ldraw._model_validation import ModelValidationContext
from ldraw.errors import DuplicateSubmodelError
from ldraw.instruction_artifacts import (
    instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.instructions import iter_instruction_issues
from ldraw.model import Model, _model_structure_diagnostics, parse_model_result
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldraw.instructions import InstructionDocument

PARTS = Parts(Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst")


def cyclic_document() -> InstructionDocument:
    child = Model(
        name="sub.ldr", objects=[Piece.place("main.ldr"), Piece.place("3001")]
    )
    stand = Model(
        name="stand.ldr", objects=[Piece.place("main.ldr"), Piece.place("3002")]
    )
    return Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child, stand.name: stand},
    ).instruction_document()


def test_copy_lineage_does_not_make_an_orphan_reachable() -> None:
    root = Model(name="main.ldr", objects=[Piece.place("3001")])
    orphan = replace(
        root.submodel_view(root.name),
        name="stand.ldr",
        objects=[Piece.place(root.name), Piece.place("3002")],
        submodels={},
    )
    root.submodels[orphan.name] = orphan
    document = root.instruction_document()
    step = document.orphan_sections[0].steps[0]
    assert [occ.part_code for occ in step.added_occurrences()] == ["3001", "3002"]
    assert [row.part for row in step.added_bill_of_materials()] == ["3001", "3002"]
    assert document._resolution.equivalents(orphan) == (orphan,)  # noqa: SLF001


def test_document_role_replacement_cannot_mutate_the_original() -> None:
    document = cyclic_document()
    step = document.orphan_sections[0].steps[0]
    before = [occ.part_code for occ in step.added_occurrences()]
    derived = replace(document, root=document.orphan_sections[0])
    assert document._resolution is not derived._resolution  # noqa: SLF001
    assert document._resolution.context is derived._resolution.context  # noqa: SLF001
    assert [occ.part_code for occ in step.added_occurrences()] == before
    assert derived.root.steps[0]._resolution is derived._resolution  # noqa: SLF001
    assert [occ.part_code for occ in derived.root.steps[0].added_occurrences()] == [
        "main.ldr",
        "3002",
    ]


class WeakModel(Model):
    """Allow source lifetime assertions without changing base model layout."""


def test_resolution_retains_the_source_and_checks_identity() -> None:
    target = Model(name="child.ldr")
    root = Model(
        name="main.ldr",
        objects=[Piece.place(target.name)],
        submodels={target.name: target},
    )
    resolution = InstructionResolution(root=root)
    source = WeakModel(name=target.name)
    weak_source = ref(source)
    resolution.bind_sources(selected=root, sources=[source])
    del source
    gc.collect()
    assert weak_source() is not None
    assert resolution.equivalents(weak_source()) == (target,)
    unrelated = Model(name="other.ldr")
    resolution._sources[id(unrelated)] = (weak_source(), target)  # noqa: SLF001
    assert resolution.equivalents(unrelated) == ()


@pytest.mark.parametrize("view", [False, True])
def test_sibling_replacements_conflict_but_descendants_supersede(*, view: bool) -> None:
    raw = Model(name="main.ldr", objects=[Piece.place("3001")])
    raw.submodels[raw.name] = raw
    source = raw.submodel_view(raw.name) if view else raw
    first = replace(source, objects=[Piece.place("3002")])
    sibling = replace(source, objects=[Piece.place("3003")])
    first.submodels = {sibling.name: sibling}
    with pytest.raises(DuplicateSubmodelError):
        first.to_ldraw()
    descendant = replace(
        first, objects=[Piece.place("3004")], submodels={first.name: first}
    )
    assert parse_model_result(descendant.to_ldraw()).model.pieces[0].part == "3004"


def pickle_model(model: Model) -> Model:
    """Round-trip trusted test state through the standard pickle protocol."""
    return pickle.loads(pickle.dumps(model))  # noqa: S301 - trusted local roundtrip


@pytest.mark.parametrize("factory", [copy, deepcopy, pickle_model])
def test_directional_graph_copy_protocols(factory: Callable[[Model], Model]) -> None:
    raw = Model(name="main.ldr", objects=[Piece.place("3001")])
    raw.submodels[raw.name] = raw
    edited = replace(raw, objects=[Piece.place("3002")])
    restored = factory(edited)
    assert parse_model_result(restored.to_ldraw()).model.pieces[0].part == "3002"
    sibling = replace(restored, objects=[Piece.place("3003")])
    other = replace(restored, objects=[Piece.place("3004")])
    sibling.submodels = {other.name: other}
    with pytest.raises(DuplicateSubmodelError):
        sibling.to_ldraw()


def test_raw_lineage_is_json_and_pickle_compatible() -> None:
    model = Model(name="main.ldr")
    assert get_type_hints(Model)
    assert json.loads(json.dumps(asdict(model)))["name"] == model.name
    assert b"_SourceOrigin" not in pickle.dumps(model)
    old_state = model.__getstate__()
    old_state[1]["_serialization_origin"] = _SourceOrigin()
    restored = object.__new__(Model)
    restored.__setstate__(old_state)
    assert isinstance(restored._serialization_origin, dict)
    assert json.dumps(asdict(restored))


class Observer:
    """Record writes reached through cooperative Model setter dispatch."""

    writes: ClassVar[list[str]] = []

    def __setattr__(self: Self, name: str, value: object) -> None:
        self.writes.append(name)
        super().__setattr__(name, value)


class ObservedModel(Model, Observer):
    """Keep the observer after Model in the MRO."""


class StateMixin:
    """Restore saved fields through ordinary cooperative attribute writes."""

    restores: ClassVar[int] = 0

    def __setstate__(
        self: Self, state: tuple[dict[str, object] | None, dict[str, object]]
    ) -> None:
        StateMixin.restores += 1
        dictionary, slots = state
        if dictionary is not None:
            self.__dict__.update(dictionary)
        for name, value in slots.items():
            setattr(self, name, value)


class StateModel(Model, StateMixin):
    """Exercise state-hook delegation after the Model base."""


@pytest.mark.parametrize("factory", [copy, deepcopy, pickle_model])
def test_cooperative_state_hooks_preserve_directional_graphs(
    factory: Callable[[Model], Model],
) -> None:
    raw = StateModel(name="main.ldr", objects=[Piece.place("3001")])
    raw.submodels[raw.name] = raw
    edited = replace(raw, objects=[Piece.place("3002")])
    StateMixin.restores = 0
    restored = factory(edited)
    assert StateMixin.restores > 0
    assert parse_model_result(restored.to_ldraw()).model.pieces[0].part == "3002"
    reset = replace(restored)
    reset._serialization_origin = None  # noqa: SLF001
    with pytest.raises(DuplicateSubmodelError):
        reset.to_ldraw()


def test_copy_and_state_hook_exceptions_propagate() -> None:
    class Failing(Model):
        def __getstate__(self: Self) -> object:
            message = "custom state failure"
            raise RuntimeError(message)

    for operation in (copy, deepcopy, pickle.dumps):
        with pytest.raises(RuntimeError, match="custom state failure"):
            operation(Failing())


def test_copy_hook_after_model_remains_authoritative() -> None:
    class CopyMixin:
        def __copy__(self: Self) -> Model:
            return Model(name="custom.ldr")

    class Copied(Model, CopyMixin):
        pass

    assert copy(Copied()).name == "custom.ldr"


def test_model_setter_observes_construction_mutation_and_restoration() -> None:
    Observer.writes.clear()
    model = ObservedModel(name="main.ldr")
    assert "name" in Observer.writes
    Observer.writes.clear()
    model.name = "changed.ldr"
    assert Observer.writes == ["name"]
    Observer.writes.clear()
    assert deepcopy(model).name == "changed.ldr"
    assert "name" in Observer.writes


def scoped_document() -> InstructionDocument:
    good = Model(name="good.ldr", objects=[Piece.place("3001")])
    bad = Model(name="bad.ldr", objects=[Piece.place("3002")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(good.name), Piece.place(bad.name)],
        submodels={good.name: good, bad.name: bad},
    )
    document = root.instruction_document()
    invalid = Piece.place("alias.ldr")
    root.submodels[invalid.reference] = Model(
        name="different.ldr", objects=[Piece.place("3003")]
    )
    section = document.section(bad.name)
    changed = replace(
        section,
        steps=(
            replace(
                section.steps[0], objects=(invalid,), _cumulative_objects=(invalid,)
            ),
        ),
    )
    return replace(
        document,
        sections=tuple(changed if s is section else s for s in document.sections),
    )


def test_selected_export_omits_unrelated_conflicting_sections(tmp_path: Path) -> None:
    document = scoped_document()
    with pytest.raises(ValueError, match="without rewriting"):
        instruction_manifest(document, parts=PARTS)
    output = tmp_path / "selected"
    path = write_instruction_snapshots(
        document, parts=PARTS, output=output, section_name="good.ldr"
    )
    manifest = json.loads(path.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["root_section"] == "good.ldr"
    assert [s["name"] for s in manifest["sections"]] == ["good.ldr"]
    assert manifest["orphan_sections"] == []
    original = path.read_bytes()
    document.section("good.ldr").model.objects.append(Piece.place("alias.ldr"))
    with pytest.raises(ValueError, match="without rewriting"):
        write_instruction_snapshots(
            document, parts=PARTS, output=output, section_name="good.ldr", force=True
        )
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".selected-*"))


def test_scoped_manifest_keeps_required_dependency_metadata(tmp_path: Path) -> None:
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001")])
    child = Model(name="child.ldr", objects=[Piece.place(leaf.name)])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child, leaf.name: leaf},
    )
    output = tmp_path / "selected"
    path = write_instruction_snapshots(
        root.instruction_document(), parts=PARTS, output=output, section_name=child.name
    )
    manifest = json.loads(path.read_text())
    assert [s["name"] for s in manifest["sections"]] == [child.name, leaf.name]
    assert manifest["sections"][1]["steps"][0]["artifacts"] == {}
    report = parse_model_result((output / "001-child" / "step-0001.mpd").read_text())
    assert report.complete
    assert report.model is not None
    assert [occ.part_code for occ in report.model.iter_occurrences()] == ["3001"]


def test_manifests_do_not_materialize_step_closures() -> None:
    sections = [
        Model(name=f"child-{i}.ldr", objects=[Piece.place("3001")]) for i in range(40)
    ]
    root = Model(
        name="main.ldr",
        objects=[Piece.place(s.name) for s in sections],
        submodels={s.name: s for s in sections},
    )
    document = root.instruction_document()
    with patch.object(
        target=InstructionResolution,
        attribute="dependencies",
        autospec=True,
        side_effect=AssertionError("manifest computed a step closure"),
    ):
        assert len(instruction_manifest(document, parts=PARTS)["sections"]) == 41


def test_temporary_serialization_creates_one_definition_registry() -> None:
    document = cyclic_document()
    temporary = (
        document.section("sub.ldr").steps[0].added_occurrences()[-1].source_model
    )
    with patch(
        target="ldraw._instruction_export._DefinitionRegistry",
        wraps=_DefinitionRegistry,
    ) as registered:
        report = parse_model_result(temporary.to_ldraw())
    assert registered.call_count == 1
    assert report.complete
    assert report.model is not None
    assert repr(temporary)


def test_shared_cycle_locations_are_complete_and_route_independent() -> None:
    a = Model(name="a.ldr", objects=[Piece.place("s.ldr")])
    b = Model(name="b.ldr", objects=[Piece.place("s.ldr")])
    shared = Model(name="s.ldr", objects=[Piece.place(b.name)])
    b._source_lines[b.pieces[0]] = 9  # noqa: SLF001
    shared._source_lines[shared.pieces[0]] = 12  # noqa: SLF001
    for order in ((a, b), (b, a)):
        root = Model(
            name="main.ldr",
            objects=[Piece.place(s.name) for s in order],
            submodels={s.name: s for s in (a, b, shared)},
        )
        issues = _model_structure_diagnostics(root, path=None)
        assert [(d.section, d.line_number) for d in issues] == [
            (b.name, 9),
            (shared.name, 12),
        ]


def test_instruction_cycle_scope_stops_at_embedded_dat_parts() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("child.ldr")])
    embedded = Model(name="shape.dat", objects=[Piece.place(child.name)])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(embedded.name)],
        submodels={child.name: child, embedded.name: embedded},
    )
    assert any(
        d.code.value == "mpd.cycle"
        for d in _model_structure_diagnostics(root, path=None)
    )
    document = root.instruction_document()
    assert [section.name for section in document.sections] == [root.name]
    assert "cyclic-submodel" not in {
        issue.code for issue in iter_instruction_issues(document)
    }


def test_preparation_validation_is_once_and_closures_are_lazy() -> None:
    document = Model(
        name="main.ldr", objects=[Piece.place("3001")]
    ).instruction_document()
    with patch.object(
        target=InstructionResolution,
        attribute="dependencies",
        autospec=True,
        side_effect=InstructionResolution.dependencies,
    ) as closures:
        prepared = _ExportPreparation(document=document)
        assert closures.call_count == 0
        assert (
            prepared.dependencies(source=document.model, objects=document.model.objects)
            == ()
        )
        assert (
            prepared.dependencies(source=document.model, objects=document.model.objects)
            == ()
        )
    assert closures.call_count == 1


def test_paired_writers_use_prepared_reference_bindings(tmp_path: Path) -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child},
    )
    with patch.object(
        target=_ExportState,
        attribute="register",
        autospec=True,
        side_effect=_ExportState.register,
    ) as checked:
        write_instruction_snapshots(
            root.instruction_document(), parts=PARTS, output=tmp_path / "bundle"
        )
    assert checked.call_count == 1


def test_preparation_rejects_new_inputs_and_new_calls_validate_them() -> None:
    root = Model(name="main.ldr", objects=[Piece.place("3001")])
    document = root.instruction_document()
    prepared = _ExportPreparation(document=document)
    root.objects.append(Piece.place("3002"))
    with pytest.raises(ValueError, match="outside the prepared export scope"):
        prepared.dependencies(source=root, objects=root.objects)
    fresh = _ExportPreparation(document=document)
    assert fresh.dependencies(source=root, objects=root.objects) == ()


class GraphResolver(Model):
    """Resolve finite graph edges by placement identity."""

    def __init__(self: Self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.targets: dict[Piece, Model] = {}

    def submodel_for(self: Self, piece: Piece) -> Model | None:
        """Use explicit targets, including duplicate section names."""
        return self.targets.get(piece)


def exhaustive_cycles(root: GraphResolver) -> set[tuple[int, int]]:
    """Collect path cycle segments and identity cycles independently of production."""
    edges: dict[int, list[tuple[Piece, Model]]] = {}
    cyclic: set[tuple[int, int]] = set()

    def walk(
        *, source: Model, names: tuple[str, ...], path: tuple[tuple[int, int], ...]
    ) -> None:
        visiting = (*names, normalize_ref(source.name))
        edges[id(source)] = [
            (p, root.targets[p]) for p in source.pieces if p in root.targets
        ]
        for piece, target in edges[id(source)]:
            marker = id(source), id(piece)
            name = normalize_ref(target.name)
            if name in visiting:
                cyclic.update((*path[visiting.index(name) :], marker))
            else:
                walk(source=target, names=visiting, path=(*path, marker))

    walk(source=root, names=(), path=())
    for source, outgoing in edges.items():
        for piece, target in outgoing:
            pending = [id(target)]
            visited: set[int] = set()
            while pending:
                identity = pending.pop()
                if identity == source:
                    cyclic.add((source, id(piece)))
                    break
                if identity not in visited:
                    visited.add(identity)
                    pending.extend(id(t) for _, t in edges.get(identity, ()))
    return cyclic


def test_ambiguous_cycle_reporting_matches_exhaustive_oracle() -> None:
    randomizer = random.Random(86)
    for _ in range(500):
        root = GraphResolver(name="main.ldr")
        nodes = [
            root,
            *(Model(name=f"{randomizer.choice('abcde')}.ldr") for _ in range(6)),
        ]
        for source in nodes:
            for _ in range(randomizer.randrange(start=0, stop=4)):
                piece = Piece.place("edge.ldr")
                source.objects.append(piece)
                root.targets[piece] = randomizer.choice(nodes)
        actual = {
            (id(source), id(piece))
            for source, piece, _, cyclic in iter_structure_edges(root=root)
            if cyclic
        }
        assert actual == exhaustive_cycles(root)


def test_ambiguity_outside_a_shared_lattice_does_not_repeat_discovery() -> None:
    root = GraphResolver(name="main.ldr")
    levels = [[Model(name=f"layer-{i}-{j}.ldr") for j in range(2)] for i in range(24)]
    for parents, children in zip([[root], *levels[:-1]], levels, strict=True):
        for parent in parents:
            for child in children:
                piece = Piece.place(child.name)
                parent.objects.append(piece)
                root.targets[piece] = child
    for _ in range(2):
        piece = Piece.place("duplicate.ldr")
        root.objects.append(piece)
        root.targets[piece] = Model(name=piece.reference)
    context = ModelValidationContext()
    with patch.object(
        target=root, attribute="submodel_for", wraps=root.submodel_for
    ) as resolved:
        assert not _model_structure_diagnostics(root, path=None, context=context)
    assert resolved.call_count == 96
    assert len(context._edges) == 51  # noqa: SLF001
