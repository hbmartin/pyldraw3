"""Explicit export roots, manifest roles, and traversal-local graph discovery."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest

from ldraw import instructions
from ldraw._model_structure import iter_structure_edges
from ldraw._model_validation import ModelValidationContext
from ldraw._model_views import _model_view
from ldraw.instruction_artifacts import (
    instruction_manifest,
    write_instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.lines import Comment
from ldraw.model import Model
from ldraw.parts import Parts
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.instructions import InstructionDocument

PARTS = Parts(Path(__file__).parent / "test_ldraw/ldraw/parts.lst")


def changed_root_document() -> InstructionDocument:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child},
    )
    document = root.instruction_document()
    invalid = Piece.place("alias.ldr")
    root.submodels[invalid.reference] = Model(name="different.ldr")
    changed = replace(document.root, model=replace(root, objects=[invalid]))
    return replace(document, root=changed)


def test_full_export_validates_root_outside_sections_and_preserves_output(
    tmp_path: Path,
) -> None:
    document = changed_root_document()
    assert all(section is not document.root for section in document.sections)
    with pytest.raises(ValueError, match="without rewriting"):
        instruction_manifest(document, parts=PARTS)
    output = tmp_path / "manifest.json"
    output.write_text("existing")
    with pytest.raises(ValueError, match="without rewriting"):
        write_instruction_manifest(document, parts=PARTS, output=output, force=True)
    assert output.read_text() == "existing"


def test_selected_export_excludes_independently_changed_root(tmp_path: Path) -> None:
    document = changed_root_document()
    path = write_instruction_snapshots(
        document, parts=PARTS, output=tmp_path / "selected", section_name="child.ldr"
    )
    manifest = json.loads(path.read_text())
    assert manifest["root_section"] == "child.ldr"
    assert [(s["name"], s["is_root"]) for s in manifest["sections"]] == [
        ("child.ldr", True)
    ]
    assert document.section("child.ldr").is_root is False
    original = path.read_bytes()
    document.section("child.ldr").model.objects.append(Piece.place("alias.ldr"))
    with pytest.raises(ValueError, match="without rewriting"):
        write_instruction_snapshots(
            document,
            parts=PARTS,
            output=path.parent,
            section_name="child.ldr",
            force=True,
        )
    assert path.read_bytes() == original


def test_selected_manifest_marks_only_export_root_and_keeps_dependency_metadata(
    tmp_path: Path,
) -> None:
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001")])
    child = Model(name="child.ldr", objects=[Piece.place(leaf.name)])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name)],
        submodels={child.name: child, leaf.name: leaf},
    )
    path = write_instruction_snapshots(
        root.instruction_document(),
        parts=PARTS,
        output=tmp_path / "selected",
        section_name=child.name,
    )
    manifest = json.loads(path.read_text())
    assert [(s["name"], s["is_root"]) for s in manifest["sections"]] == [
        (child.name, True),
        (leaf.name, False),
    ]
    assert manifest["sections"][1]["steps"][0]["artifacts"] == {}


class GraphResolver(Model):
    """Resolve source placements by identity, including ambiguous section names."""

    def __init__(self: Self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.targets: dict[Piece, Model] = {}

    def submodel_for(self: Self, piece: Piece) -> Model | None:
        """Return the explicitly associated target for this placement."""
        return self.targets.get(piece)


@pytest.mark.parametrize("selected_first", [False, True])
def test_reused_edge_cache_matches_fresh_graphs_in_both_scope_orders(
    *,
    selected_first: bool,
) -> None:
    root = GraphResolver(name="main.ldr")
    first, second, leaf = (
        Model(name="same.ldr"),
        Model(name="same.ldr"),
        Model(name="leaf.ldr"),
    )
    for source, target in [(root, first), (first, second), (second, leaf)]:
        piece = Piece.place(target.name)
        source.objects.append(piece)
        root.targets[piece] = target
    selected = _model_view(selected=second, root=root)
    scopes = (selected, root) if selected_first else (root, selected)
    context = ModelValidationContext()
    for scope in scopes:
        assert list(iter_structure_edges(root=scope, context=context)) == list(
            iter_structure_edges(root=scope)
        )
    assert len(list(iter_structure_edges(root=root, context=context))) == 2


def test_fresh_document_retains_built_sections_and_replacements_own_bindings() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("3001")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place(child.name), Comment("STEP"), Piece.place("3002")],
        submodels={child.name: child},
    )
    built = []
    build_section = instructions._build_section  # noqa: SLF001

    def capture(**kwargs: object) -> instructions.InstructionSection:
        section = build_section(**kwargs)
        built.append(section)
        return section

    with patch.object(instructions, "_build_section", side_effect=capture):
        document = root.instruction_document()
    assert all(a is b for a, b in zip(document.sections, built, strict=True))
    derived = replace(document)
    assert derived._resolution is not document._resolution  # noqa: SLF001
    assert derived._resolution.context is document._resolution.context  # noqa: SLF001
    assert derived.root.steps[0] is not document.root.steps[0]
    assert [o.part_code for o in derived.root.steps[0].added_occurrences()] == [
        o.part_code for o in document.root.steps[0].added_occurrences()
    ]
