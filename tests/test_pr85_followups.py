"""Rebound instructions, copy lineage, bounded loading and deep snapshots."""

from __future__ import annotations

import inspect
import pickle
from copy import copy, deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest

from ldraw._instruction_export import _ExportPreparation
from ldraw._instruction_resolution import InstructionResolution
from ldraw._model_validation import ModelValidationContext
from ldraw.errors import DuplicateSubmodelError, SubmodelCycleError
from ldraw.geometry import Matrix, Vector
from ldraw.instruction_artifacts import (
    _flatten_objects,
    _write_snapshot_mpd,
    instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.model import Model, _model_structure_diagnostics, parse_model_result
from ldraw.parts import Parts
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from collections.abc import Callable

    from ldraw.part import ParsedObject

PARTS = Parts(Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst")


def cyclic_model(*, name: str = "main.ldr", part: str = "3001") -> Model:
    child = Model(
        name="sub.ldr", objects=[Piece.place(name), Piece.place(part, colour=4)]
    )
    orphan = Model(name="stand.ldr", objects=[Piece.place(name), Piece.place("3002")])
    return Model(
        name=name,
        objects=[Piece.place(child.name)],
        submodels={child.name: child, orphan.name: orphan},
    )


def test_rebinding_keeps_source_content_and_restores_ancestor_exports(
    tmp_path: Path,
) -> None:
    old = cyclic_model()
    document = old.instruction_document()
    new = cyclic_model(part="3003")
    rebound = replace(document, model=new, _resolution=None)
    step = rebound.section("sub.ldr").steps[0]
    assert step.objects is document.section("sub.ldr").steps[0].objects
    assert [occ.part_code for occ in step.added_occurrences()] == ["main.ldr", "3001"]
    assert [row.part for row in step.added_bill_of_materials()] == ["3001", "main.ldr"]
    source = step.added_occurrences()[-1].source_model
    text = source.to_ldraw()
    assert text.count("0 FILE sub.ldr") == 1
    assert text.count("0 FILE main.ldr") == 1
    assert parse_model_result(text).complete
    assert instruction_manifest(rebound, parts=PARTS)["schema_version"] == 1
    path = tmp_path / "sub.mpd"
    _write_snapshot_mpd(
        rebound, section=rebound.section("sub.ldr"), step=step, path=path
    )
    assert parse_model_result(path.read_text()).complete
    assert [occ.part_code for occ in document.root.steps[0].added_occurrences()] == [
        "main.ldr",
        "3001",
    ]
    assert [occ.part_code for occ in rebound.root.steps[0].added_occurrences()] == [
        "main.ldr",
        "3003",
    ]


def test_rebinding_orphans_and_root_roles_with_renamed_roots() -> None:
    old = cyclic_model()
    document = old.instruction_document()
    new = cyclic_model(name="renamed.ldr")
    # Retained reference spelling is authoritative; this explicit old-name target
    # remains incompatible with serialization, rather than being rewritten.
    new.submodels["main.ldr"] = new
    rebound = replace(document, model=new, _resolution=None)
    assert [
        occ.part_code for occ in rebound.section("sub.ldr").steps[0].added_occurrences()
    ] == ["main.ldr", "3001"]
    assert [
        occ.part_code for occ in rebound.orphan_sections[0].steps[0].added_occurrences()
    ] == ["renamed.ldr", "3001", "3002"]
    with pytest.raises(ValueError, match="without rewriting"):
        instruction_manifest(rebound, parts=PARTS)


class IdentityResolver(Model):
    """Resolve retained placements independently of declaration-table objects."""

    def __init__(self: Self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.targets: dict[Piece, Model] = {}

    def submodel_for(self: Self, piece: Piece) -> Model | None:
        """Resolve the actual source placement against its saved target."""
        return self.targets.get(piece)


def test_rebinding_respects_identity_sensitive_placements_and_view_scopes() -> None:
    old = cyclic_model()
    document = old.instruction_document()
    new = IdentityResolver(name="main.ldr", objects=[Piece.place("sub.ldr")])
    child = Model(name="sub.ldr", objects=[Piece.place("3003")])
    old_child = old.submodels["sub.ldr"]
    new.targets = {
        new.pieces[0]: child,
        old.pieces[0]: child,
        old_child.pieces[0]: new,
    }
    rebound = replace(document, model=new.submodel_view(new.name), _resolution=None)
    assert [
        occ.part_code for occ in rebound.section("sub.ldr").steps[0].added_occurrences()
    ] == ["main.ldr", "3001"]
    assert instruction_manifest(rebound, parts=PARTS)
    unrelated = Model(name="SUB.LDR", objects=[Piece.place("3004")])
    child.objects.append(Piece.place("other.ldr"))
    new.targets[child.pieces[-1]] = unrelated
    with pytest.raises(DuplicateSubmodelError):
        instruction_manifest(rebound, parts=PARTS)


@pytest.mark.parametrize("factory", [copy, deepcopy, replace])
def test_raw_copies_and_replacements_serialize_self_tables(
    factory: Callable[[Model], Model],
) -> None:
    raw = Model(name="main.ldr", objects=[Piece.place("3001")])
    raw.submodels[raw.name] = raw
    copied = factory(raw)
    assert copied.to_ldraw().count("0 FILE main.ldr") == 1
    replaced = replace(copied, objects=[Piece.place("3002")])
    report = parse_model_result(replaced.to_ldraw())
    assert report.complete
    assert report.model is not None
    assert report.model.pieces[0].part == "3002"
    copied.submodels["conflict"] = Model(name="MAIN.LDR")
    with pytest.raises(DuplicateSubmodelError):
        copied.to_ldraw()


def test_token_conversion_copy_graphs_reset_and_hooks() -> None:
    raw = Model(name="main.ldr")
    assert isinstance(raw._serialization_origin, dict)  # noqa: SLF001
    assert asdict(raw)["name"] == "main.ldr"
    assert inspect.signature(Model).parameters["_serialization_origin"].default is None
    raw.submodels[raw.name] = raw
    for restored in (deepcopy(raw), pickle.loads(pickle.dumps(raw))):  # noqa: S301
        assert restored.submodels[restored.name] is restored
        assert restored.to_ldraw().count("0 FILE main.ldr") == 1
    changed = replace(raw)
    changed._serialization_origin = None  # noqa: SLF001
    with pytest.raises(DuplicateSubmodelError):
        changed.to_ldraw()

    class Hooked(Model):
        def __post_init__(self: Self) -> None:
            pytest.fail("a previously unused subclass hook must not run")

    assert asdict(Hooked())["name"] == ""


@pytest.mark.parametrize("orphan", [False, True])
def test_temporary_piece_inspection_matches_occurrences(*, orphan: bool) -> None:
    document = cyclic_model().instruction_document()
    step = (
        document.orphan_sections[0].steps[0]
        if orphan
        else document.section("sub.ldr").steps[0]
    )
    occurrences = step.added_occurrences()
    source = occurrences[-1].source_model
    assert list(source.iter_pieces()) == [occ.piece for occ in occurrences]
    assert source.find_pieces(recursive=True) == list(source.iter_pieces())
    assert repr(source)
    with pytest.raises(SubmodelCycleError):
        list(document.model.iter_pieces())


def shared_lattice(*, layers: int, cyclic: bool) -> Model:
    sections = [
        Model(name=f"{level}-{branch}.ldr")
        for level in range(layers)
        for branch in ("a", "b")
    ]
    for level in range(layers - 1):
        for section in sections[level * 2 : level * 2 + 2]:
            section.objects = [
                Piece.place(f"{level + 1}-{branch}.ldr") for branch in ("a", "b")
            ]
    for section in sections[-2:]:
        section.objects = [Piece.place("main.ldr" if cyclic else "missing.ldr")]
    return Model(
        name="main.ldr",
        objects=[Piece.place("0-a.ldr"), Piece.place("0-b.ldr")],
        submodels={section.name: section for section in sections},
    )


@pytest.mark.parametrize("cyclic", [False, True])
def test_structural_loading_expands_shared_sources_once(*, cyclic: bool) -> None:
    model = shared_lattice(layers=30, cyclic=cyclic)
    resolver = Model.submodel_for
    with patch.object(
        target=Model, attribute="submodel_for", autospec=True, side_effect=resolver
    ) as resolved:
        report = parse_model_result(model.to_ldraw())
    assert report.complete
    assert resolved.call_count == 120
    relevant = [
        d
        for d in report.diagnostics
        if d.code.value in {"mpd.cycle", "mpd.unresolved_submodel"}
    ]
    assert len(relevant) == (120 if cyclic else 2)


def test_ambiguous_structural_cycle_routes_keep_locations() -> None:
    root = IdentityResolver(
        name="main.ldr", objects=[Piece.place("first.ldr"), Piece.place("second.ldr")]
    )
    a = Model(name="a.ldr", objects=[Piece.place("shared.ldr")])
    b = Model(name="b.ldr", objects=[Piece.place("shared.ldr")])
    shared = Model(name="c.ldr", objects=[Piece.place("closing.ldr")])
    closing = Model(name="a.ldr", objects=[Piece.place("missing.ldr")])
    shared._source_lines[shared.pieces[0]] = 7  # noqa: SLF001
    closing._source_lines[closing.pieces[0]] = 8  # noqa: SLF001
    root.targets = {
        root.pieces[0]: a,
        root.pieces[1]: b,
        a.pieces[0]: shared,
        b.pieces[0]: shared,
        shared.pieces[0]: closing,
    }
    diagnostics = _model_structure_diagnostics(
        root, path=None, context=ModelValidationContext()
    )
    assert {d.line_number for d in diagnostics} == {None, 7, 8}


def deep_model() -> Model:
    sections = [
        Model(
            name=f"section-{i}.ldr",
            objects=[
                Piece.place(f"section-{i + 1}.ldr", position=Vector(x=1, y=0, z=0))
            ],
        )
        for i in range(1_200)
    ]
    points = [Vector(x=i, y=1, z=0) for i in range(4)]
    sections[-1].objects = [
        Piece.place("3001"),
        Line(colour=Piece.place("3001").colour, point1=points[0], point2=points[1]),
        Triangle(
            colour=Piece.place("3001").colour,
            point1=points[0],
            point2=points[1],
            point3=points[2],
        ),
        Quadrilateral(
            colour=Piece.place("3001").colour,
            point1=points[0],
            point2=points[1],
            point3=points[2],
            point4=points[3],
        ),
        OptionalLine(
            colour=Piece.place("3001").colour,
            point1=points[0],
            point2=points[1],
            point3=points[2],
            point4=points[3],
        ),
    ]
    return Model(
        name="main.ldr",
        objects=[Piece.place(sections[0].name, colour=4)],
        submodels={s.name: s for s in sections},
    )


def test_deep_piece_iteration_and_geometry_snapshots(tmp_path: Path) -> None:
    model = deep_model()
    assert len(list(model.iter_pieces())) == 1
    assert len(model.find_pieces(part="3001", recursive=True)) == 1
    document = model.instruction_document()
    output = tmp_path / "bundle"
    write_instruction_snapshots(
        document, parts=PARTS, output=output, section_name=model.name
    )
    flattened = parse_model_result((output / "001-main" / "step-0001.ldr").read_text())
    assert flattened.complete
    assert flattened.model is not None
    assert len(flattened.model.objects) == 5
    assert flattened.model.pieces[0].position.x == 1_199
    assert [obj.colour.code for obj in flattened.model.objects] == [4] * 5
    for obj in flattened.model.objects[1:]:
        assert isinstance(obj, Line | Triangle | Quadrilateral | OptionalLine)
        assert obj.point1.x == 1_199


def test_flattening_preserves_parent_transform_and_embedded_dat() -> None:
    embedded = Model(name="part.dat", objects=[Piece.place("3001")])
    child = Model(
        name="child.ldr",
        objects=[
            Piece.place(embedded.name),
            Piece.place("3002", position=Vector(x=2, y=0, z=0)),
        ],
    )
    model = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child, embedded.name: embedded},
    )
    sidecars: dict[str, Model] = {}
    objects: list[ParsedObject] = list(
        _flatten_objects(
            root=model,
            model=model,
            objects=model.objects,
            position=Vector(x=10, y=0, z=0),
            matrix=Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]),
            inherited_colour=None,
            visiting=frozenset(),
            embedded_parts=sidecars,
        )
    )
    assert all(isinstance(obj, Piece) for obj in objects)
    assert [obj.position.x for obj in objects] == [10, 14]
    assert sidecars == {embedded.name: embedded}


def test_export_preparation_is_reused_and_fresh_between_invocations(
    tmp_path: Path,
) -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    model = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child},
    )
    document = model.instruction_document()
    validate = _ExportPreparation.__post_init__
    dependencies = InstructionResolution.dependencies
    with (
        patch.object(
            target=_ExportPreparation,
            attribute="__post_init__",
            autospec=True,
            side_effect=validate,
        ) as validated,
        patch.object(
            target=InstructionResolution,
            attribute="dependencies",
            autospec=True,
            side_effect=dependencies,
        ) as closures,
    ):
        write_instruction_snapshots(document, parts=PARTS, output=tmp_path / "bundle")
    assert validated.call_count == 1
    assert closures.call_count == 2
    child.objects.append(Piece.place(child.name))
    with pytest.raises(SubmodelCycleError):
        write_instruction_snapshots(
            document, parts=PARTS, output=tmp_path / "bundle", force=True
        )
    assert (tmp_path / "bundle" / "instructions.json").is_file()
    assert not list(tmp_path.glob(".bundle-*"))


def test_temporary_string_serialization_remains_strict(tmp_path: Path) -> None:
    root = IdentityResolver(
        name="main.ldr",
        objects=[
            Piece.place("first.ldr"),
            Piece.place("second.ldr"),
            Piece.place("3004"),
        ],
    )
    root.targets = {piece: Model(name="child.ldr") for piece in root.pieces[:2]}
    source = (
        root.instruction_document().root.steps[0].added_occurrences()[-1].source_model
    )
    assert repr(source)
    with pytest.raises(ValueError, match="without rewriting"):
        str(source)
    with pytest.raises(ValueError):
        source.save(tmp_path / "invalid.mpd")
    assert not (tmp_path / "invalid.mpd").exists()


def test_fresh_identical_definitions_still_require_one_source_identity() -> None:
    class Fresh(Model):
        def submodel_for(self: Self, piece: Piece) -> Model | None:
            """Return a fresh independent definition on each child reference."""
            return (
                Model(name="child.ldr", objects=[Piece.place("3001")])
                if piece.reference == "child.ldr"
                else None
            )

    root = Fresh(
        name="main.ldr",
        objects=[
            Piece.place("child.ldr"),
            Piece.place("child.ldr"),
            Piece.place("3004"),
        ],
    )
    document = root.instruction_document()
    assert [occ.part_code for occ in document.root.steps[0].added_occurrences()] == [
        "3001",
        "3001",
        "3004",
    ]
    with pytest.raises(DuplicateSubmodelError):
        instruction_manifest(document, parts=PARTS)


def test_modified_step_bindings_are_validated_before_private_output(
    tmp_path: Path,
) -> None:
    model = IdentityResolver(name="main.ldr", objects=[Piece.place("3001")])
    document = model.instruction_document()
    invalid = Piece.place("alias.ldr")
    model.targets[invalid] = Model(name="child.ldr")
    step = replace(document.root.steps[0], _cumulative_objects=(invalid,))
    section = replace(document.root, steps=(step,))
    changed = replace(document, root=section, sections=(section,))
    output = tmp_path / "original.mpd"
    output.write_text("original")
    with pytest.raises(ValueError, match="without rewriting"):
        _write_snapshot_mpd(changed, section=section, step=step, path=output)
    assert output.read_text() == "original"
    with pytest.raises(ValueError):
        instruction_manifest(changed, parts=PARTS)


def test_programmatic_cycles_report_each_source_placement_once() -> None:
    model = shared_lattice(layers=10, cyclic=True)
    diagnostics = _model_structure_diagnostics(model, path=None)
    assert len(diagnostics) == 40
    assert {d.section for d in diagnostics} == {"main.ldr", *model.submodels}


def test_flattening_does_not_invoke_geometry_subclass_constructors() -> None:
    class RequiredLine(Line):
        def __init__(self: Self, *, label: str) -> None:
            super().__init__(
                colour=Piece.place("3001").colour,
                point1=Vector(x=1, y=0, z=0),
                point2=Vector(x=2, y=0, z=0),
            )
            self.label = label

    line = RequiredLine(label="source")
    model = Model(name="main.ldr", objects=[line])
    flattened = list(
        _flatten_objects(
            root=model,
            model=model,
            objects=model.objects,
            position=Vector(x=10, y=0, z=0),
            matrix=Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]),
            inherited_colour=None,
            visiting=frozenset(),
            embedded_parts={},
        )
    )
    assert type(flattened[0]) is Line
    assert flattened[0].point1.x == 12
    assert line.point1.x == 1
