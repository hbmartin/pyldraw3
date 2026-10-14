"""Bounded discovery, deep comparison, reference edits and faithful export."""

from __future__ import annotations

import inspect
from copy import copy, deepcopy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest

from ldraw import instructions
from ldraw._model_validation import ModelValidationContext
from ldraw._model_views import _selected_model
from ldraw.bom import BomRow, compare_inventory, rows_to_csv
from ldraw.cli import main
from ldraw.errors import DuplicateSubmodelError, SubmodelCycleError
from ldraw.geometry import Matrix, Vector
from ldraw.instruction_artifacts import (
    _write_snapshot_mpd,
    instruction_manifest,
    write_instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.instructions import InstructionDocument, iter_instruction_issues
from ldraw.lines import MetaCommand
from ldraw.model import Model, parse_model, parse_model_result
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.validation import _piece_analysis

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.model import ModelOccurrence

PARTS = Parts(Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst")


class Resolver(Model):
    """Resolve by source identity, including external and ambiguous sections."""

    def __init__(self: Self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.targets: dict[Piece, Model] = {}

    def submodel_for(self: Self, piece: Piece) -> Model | None:
        """Retain each placement's authoritative target."""
        return self.targets.get(piece)


class Filtered(Model):
    """Emit no leaves while retaining numeric auditing of resolved edges."""

    def iter_occurrences(self: Self, **_flags: bool) -> Iterable[ModelOccurrence]:
        """Keep the empty custom inventory authoritative."""
        return ()


class Inherited(Model):
    """Keep the inherited occurrence implementation."""


def cyclic_lattice(*, layers: int, custom: bool) -> Model:
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
    for section in sections[-2:]:
        section.objects = [Piece.place("main.ldr")]
    root = (Resolver if custom else Model)(
        name="main.ldr",
        objects=[Piece.place("0-a.ldr"), Piece.place("0-b.ldr")],
        submodels={section.name: section for section in sections},
    )
    if isinstance(root, Resolver):
        root.targets = {
            piece: root
            if piece.reference == root.name
            else root.submodels[piece.reference]
            for section in [root, *sections]
            for piece in section.pieces
        }
    return root


@pytest.mark.parametrize("custom", [False, True])
def test_unique_name_cyclic_lattice_expands_each_source_once(*, custom: bool) -> None:
    root = cyclic_lattice(layers=30, custom=custom)
    view = root.submodel_view(root.name)
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
        ) as numeric,
    ):
        context.ensure_validated(root=view, reachable_only=True)
    assert edges.call_count == 61
    assert numeric.call_count == sum(
        len(section.pieces) for section in [root, *root.submodels.values()]
    )
    with pytest.raises(SubmodelCycleError):
        compare_inventory(model=view, expected=[])


@pytest.mark.parametrize("cyclic", [False, True])
def test_ambiguous_names_reuse_completed_or_sensitive_shared_sections(
    *, cyclic: bool
) -> None:
    first = Model(name="a.ldr", objects=[Piece.place("c.ldr")])
    second = Model(name="a.ldr", objects=[Piece.place("c.ldr")])
    shared = Model(name="c.ldr", objects=[Piece.place("c.ldr" if cyclic else "d.ldr")])
    tail = Model(name="d.ldr")
    root = Resolver(
        name="main.ldr", objects=[Piece.place("first.ldr"), Piece.place("second.ldr")]
    )
    root.targets = {
        root.pieces[0]: first,
        root.pieces[1]: second,
        first.pieces[0]: shared,
        second.pieces[0]: shared,
        shared.pieces[0]: shared if cyclic else tail,
    }
    context = ModelValidationContext()
    with patch(
        target="ldraw.validation._piece_analysis", wraps=_piece_analysis
    ) as numeric:
        context.ensure_validated(root=root, reachable_only=True)
    assert numeric.call_count == 5
    assert len(context.validated_sections) == (4 if cyclic else 5)


def deep_model(*, model_type: type[Model], overflow: bool = False) -> Model:
    sections = [
        Model(
            name=f"section-{index}.ldr",
            objects=[
                Piece.place(f"section-{index + 1}.ldr", position=Vector(x=1, y=0, z=0))
            ],
        )
        for index in range(1_200)
    ]
    sections[-1].objects = [
        Piece.place("3001", colour=4, position=Vector(x=1, y=0, z=0))
    ]
    if overflow:
        huge = Matrix([[1e200, 0, 0], [0, 1, 0], [0, 0, 1]])
        for section in sections[1_000:1_002]:
            section.pieces[0].matrix = huge
        sections[1_001]._source_lines[sections[1_001].pieces[0]] = 42  # noqa: SLF001
    return model_type(
        name="main.ldr",
        objects=[Piece.place(sections[0].name)],
        submodels={section.name: section for section in sections},
    )


@pytest.mark.parametrize("model_type", [Model, Inherited, Filtered])
def test_deep_comparison_and_overflow_have_no_recursive_limit(
    model_type: type[Model],
) -> None:
    model = deep_model(model_type=model_type)
    expected = (
        []
        if model_type is Filtered
        else [
            BomRow(
                part="3001",
                description=None,
                colour_code=4,
                colour_name=None,
                quantity=1,
            )
        ]
    )
    assert compare_inventory(model=model, expected=expected).matched
    if model_type is not Filtered:
        (occurrence,) = model.iter_occurrences()
        assert occurrence.position == Vector(x=1_200, y=0, z=0)
        assert len(occurrence.path) == 1_201
    with pytest.raises(ValueError, match=r"section-1001.ldr:42:.*matrix\[0\]\[0\]=inf"):
        compare_inventory(
            model=deep_model(model_type=model_type, overflow=True), expected=expected
        )


def test_deep_cli_reuses_source_analysis(tmp_path: Path) -> None:
    model = deep_model(model_type=Model)
    source, inventory, output = (
        tmp_path / name for name in ("deep.mpd", "bom.csv", "result.json")
    )
    source.write_text(model.to_ldraw())
    inventory.write_text(
        rows_to_csv(
            [
                BomRow(
                    part="3001",
                    description=None,
                    colour_code=4,
                    colour_name=None,
                    quantity=1,
                )
            ]
        )
    )
    with patch(
        target="ldraw.validation._piece_analysis", wraps=_piece_analysis
    ) as numeric:
        assert (
            main(
                [
                    "bom",
                    str(source),
                    "--compare",
                    str(inventory),
                    "--format",
                    "json",
                    "-o",
                    str(output),
                ]
            )
            == 0
        )
    assert numeric.call_count == 1_201
    assert output.is_file()


def test_orphan_root_placement_expands_and_its_saved_counts_agree() -> None:
    stand = Model(
        name="stand.ldr", objects=[Piece.place("main.ldr"), Piece.place("3002")]
    )
    root = Model(
        name="main.ldr", objects=[Piece.place("3001")], submodels={stand.name: stand}
    )
    step = root.instruction_document().orphan_sections[0].steps[0]
    occurrences = step.added_occurrences()
    assert [occ.part_code for occ in occurrences] == ["3001", "3002"]
    source = occurrences[-1].source_model
    text = source.to_ldraw()
    assert text.count("0 FILE main.ldr") == 1
    assert [occ.part_code for occ in parse_model(text).iter_occurrences()] == [
        "3001",
        "3002",
    ]


def test_reachable_root_leaf_registers_complete_dependency_closure(
    tmp_path: Path,
) -> None:
    sub = Model(name="sub.ldr", objects=[Piece.place("main.ldr"), Piece.place("3004")])
    other = Model(name="other.ldr", objects=[Piece.place("3002")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(sub.name), Piece.place(other.name)],
        submodels={sub.name: sub, other.name: other},
    )
    doc = root.instruction_document()
    occurrences = doc.section(sub.name).steps[0].added_occurrences()
    assert [occ.part_code for occ in occurrences] == ["main.ldr", "3004"]
    source = occurrences[-1].source_model
    text = source.to_ldraw()
    for name in ("main.ldr", "sub.ldr", "other.ldr"):
        assert text.count(f"0 FILE {name}") == 1
    assert parse_model_result(text).complete
    with pytest.raises(SubmodelCycleError):
        write_instruction_snapshots(doc, parts=PARTS, output=tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def edited_callout(
    *, populated: bool, references: tuple[str, ...]
) -> InstructionDocument:
    root = Model(
        name="main.ldr",
        objects=[
            MetaCommand("LPUB", "CALLOUT BEGIN"),
            *([Piece.place("child.ldr")] if populated else []),
            MetaCommand("LPUB", "CALLOUT END"),
            *([] if populated else [Piece.place("child.ldr")]),
        ],
        submodels={"child.ldr": Model(name="child.ldr")},
    )
    document = root.instruction_document()
    step = document.root.steps[0]
    callout = replace(step.callouts[0], references=references)
    section = replace(document.root, steps=(replace(step, callouts=(callout,)),))
    return replace(document, root=section, sections=(section,))


@pytest.mark.parametrize(
    ("populated", "references", "empty"),
    [
        (False, ("child.ldr",), False),
        (True, (), True),
        (True, ("CHILD.LDR",), False),
        (True, ("missing.ldr",), True),
    ],
)
def test_callout_reference_edits_are_authoritative(
    *, populated: bool, references: tuple[str, ...], empty: bool
) -> None:
    doc = edited_callout(populated=populated, references=references)
    assert (
        "empty-callout" in {issue.code for issue in iter_instruction_issues(doc)}
    ) is empty


def test_callout_edits_keep_identity_sensitive_retained_sources() -> None:
    outside, inside = Piece.place("child.ldr"), Piece.place("child.ldr")
    root = Resolver(
        name="main.ldr",
        objects=[
            outside,
            MetaCommand("LPUB", "CALLOUT BEGIN"),
            inside,
            MetaCommand("LPUB", "CALLOUT END"),
        ],
    )
    root.targets[outside] = Model(name="child.ldr")
    doc = root.instruction_document()
    step = doc.root.steps[0]
    callout = replace(step.callouts[0], references=("child.ldr", "missing.ldr"))
    section = replace(doc.root, steps=(replace(step, callouts=(callout,)),))
    changed = replace(doc, root=section, sections=(section,))
    assert "empty-callout" in {issue.code for issue in iter_instruction_issues(changed)}


def ambiguous_document(*, alias: bool = False) -> InstructionDocument:
    first, second = Piece.place("child.ldr"), Piece.place("child.ldr")
    root = Resolver(name="main.ldr", objects=[first, second, Piece.place("3004")])
    root.targets = {
        first: Model(name="child.ldr", objects=[Piece.place("3001")]),
        second: Model(
            name="different.ldr" if alias else "child.ldr",
            objects=[Piece.place("3002")],
        ),
    }
    return root.instruction_document()


@pytest.mark.parametrize("alias", [False, True])
def test_ambiguous_export_rejects_loss_without_changing_counts(
    tmp_path: Path, *, alias: bool
) -> None:
    doc = ambiguous_document(alias=alias)
    occurrences = doc.root.steps[0].added_occurrences()
    assert [occ.part_code for occ in occurrences] == ["3001", "3002", "3004"]
    assert {row.part for row in doc.root.steps[0].added_bill_of_materials()} == {
        "3001",
        "3002",
        "3004",
    }
    error = ValueError if alias else DuplicateSubmodelError
    path = tmp_path / "source.mpd"
    path.write_text("original")
    with pytest.raises(error):
        occurrences[-1].source_model.save(path)
    assert path.read_text() == "original"
    with pytest.raises(error):
        instruction_manifest(doc, parts=PARTS)
    with pytest.raises(error):
        write_instruction_manifest(doc, parts=PARTS, output=path, force=True)
    assert path.read_text() == "original"
    with pytest.raises(error):
        write_instruction_snapshots(doc, parts=PARTS, output=tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    private = tmp_path / "private.mpd"
    with pytest.raises(error):
        _write_snapshot_mpd(doc, section=doc.root, step=doc.root.steps[0], path=private)
    assert not private.exists()


def test_selected_conflict_rejects_save_and_view_aliases_collapse(
    tmp_path: Path,
) -> None:
    bad = Model(
        name="main.ldr",
        objects=[Piece.place("3001")],
        submodels={"other.ldr": Model(name="MAIN.LDR", objects=[Piece.place("3002")])},
    )
    path = tmp_path / "model.mpd"
    path.write_text("original")
    with pytest.raises(DuplicateSubmodelError):
        bad.save(path)
    assert path.read_text() == "original"
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(name="main.ldr", submodels={child.name: child})
    root.submodels["alias"] = root.submodel_view(child.name)
    text = root.to_ldraw()
    assert text.count("0 FILE child.ldr") == 1
    assert parse_model_result(text).complete


def test_replaced_views_supersede_only_their_recorded_origin() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(name="main.ldr", submodels={child.name: child})
    view = root.submodel_view(child.name)
    first = replace(view, objects=[Piece.place("3002")])
    second = replace(first, objects=[Piece.place("3003")])
    assert first._serialization_origin is child  # noqa: SLF001
    assert "_serialization_origin" not in repr(first)
    for model in (first, second, copy(view), deepcopy(view)):
        assert parse_model_result(model.to_ldraw()).complete
    assert parse_model(second.to_ldraw()).pieces[0].part == "3003"
    first._serialization_origin = second  # noqa: SLF001
    assert second.to_ldraw()
    second._serialization_origin = first  # noqa: SLF001
    with pytest.raises(DuplicateSubmodelError):
        second.to_ldraw()
    first._serialization_origin = child  # noqa: SLF001
    assert second.to_ldraw()
    root.submodels["unrelated"] = Model(name="CHILD.LDR")
    with pytest.raises(DuplicateSubmodelError):
        second.to_ldraw()
    with pytest.raises(AttributeError, match="view binding"):
        view._serialization_origin = Model()  # noqa: SLF001
    assert _selected_model(view) is child


def test_step_bom_skips_custom_dispatch_and_context_rebinding_clones_once() -> None:
    root = Model(name="main.ldr", objects=[Piece.place("3001")])
    doc = root.instruction_document()
    with patch(
        target="ldraw._model_cycles.signature", wraps=inspect.signature
    ) as signature:
        assert doc.root.steps[0].added_bill_of_materials()
    assert not signature.call_count
    with patch.object(
        target=instructions, attribute="replace", wraps=replace
    ) as clones:
        InstructionDocument(
            root=doc.root,
            sections=doc.sections,
            orphan_sections=doc.orphan_sections,
            model=root,
        )
    assert [type(call.args[0]).__name__ for call in clones.call_args_list] == [
        "InstructionStep",
        "InstructionSection",
    ]


def test_false_boolean_source_keeps_root_ancestry() -> None:
    class FalseModel(Model):
        def __bool__(self: Self) -> bool:
            return False

    sub = FalseModel(name="sub.ldr", objects=[Piece.place("main.ldr")])
    root = Model(
        name="main.ldr", objects=[Piece.place(sub.name)], submodels={sub.name: sub}
    )
    step = root.instruction_document().section(sub.name).steps[0]
    assert [occ.part_code for occ in step.added_occurrences()] == ["main.ldr"]


def test_changed_temporary_dependency_cannot_override_resolved_definition() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name), Piece.place("3004")],
        submodels={child.name: child},
    )
    occurrences = root.instruction_document().root.steps[0].added_occurrences()
    source = occurrences[-1].source_model
    source.submodels[child.name] = Model(name=child.name, objects=[Piece.place("3002")])
    with pytest.raises(DuplicateSubmodelError):
        source.to_ldraw()


def test_serialization_origin_is_optional_keyword_only() -> None:
    parameters = inspect.signature(Model).parameters
    assert list(parameters)[:5] == [
        "name",
        "objects",
        "submodels",
        "_source_lines",
        "_object_source_lines",
    ]
    assert parameters["_serialization_origin"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["_serialization_origin"].default is None


def test_origin_cycle_through_a_view_uses_unwrapped_identity() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(name="main.ldr", submodels={child.name: child})
    view = root.submodel_view(child.name)
    child._serialization_origin = view  # noqa: SLF001
    report = parse_model_result(view.to_ldraw())
    assert report.complete
    assert report.model is not None
    assert report.model.name == child.name
