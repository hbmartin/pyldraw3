"""BOM identities, comparison scope, and numeric-analysis regressions."""

from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.analysis import analyze_model
from ldraw.bom import (
    _prepare_inventory_occurrences,
    bill_of_materials,
    compare_inventory,
)
from ldraw.cli import main
from ldraw.diagnostics import DiagnosticCode
from ldraw.errors import SubmodelCycleError
from ldraw.geometry import Matrix, Vector
from ldraw.model import Model, ModelOccurrence
from ldraw.part import parse_ldraw_line
from ldraw.pieces import Group, Piece
from ldraw.validation import (
    _iter_section_issues,
    _placement_analysis,
    iter_object_issues,
)


@pytest.mark.parametrize("suffix", [".ldr", ".MPD"])
def test_submodel_leaves_do_not_merge_with_same_named_parts(suffix: str) -> None:
    model = Model(
        objects=[Piece.place(f"body{suffix}", colour=4), Piece.place("body", colour=4)]
    )
    assert model.pieces[0].part == "body"
    assert [(row.part, row.quantity) for row in bill_of_materials(model)] == [
        ("body", 1),
        (f"body{suffix}", 1),
    ]
    with pytest.raises(ValueError, match="unresolved submodel"):
        compare_inventory(model, bill_of_materials(model))


def test_unexpanded_submodel_identities_and_overrides() -> None:
    child = Model(name="Body.LDR", objects=[Piece.place("3001", colour=4)])
    root = Model(name="main.ldr")
    root.add_submodel(child)
    occurrences = tuple(root.iter_occurrences(expand_submodels=False))
    assert occurrences[0].part_code == "Body.LDR"
    assert bill_of_materials(occurrences=occurrences)[0].part == "Body.LDR"
    override = replace(occurrences[0], part_code="External")
    assert bill_of_materials(occurrences=[override])[0].part == "External"
    assert bill_of_materials(root)[0].part == "3001"


@pytest.mark.parametrize("first", ["s/1", "s\\1", "S\\1"])
def test_bom_order_is_independent_of_displayed_separators(first: str) -> None:
    model = Model(objects=[Piece.place(first, colour=4), Piece.place("s0", colour=4)])
    assert [row.part for row in bill_of_materials(model)] == [first, "s0"]


def test_summary_keeps_raw_keys_while_bom_aggregates() -> None:
    model = Model(
        objects=[Piece.place("S\\3001", colour=4), Piece.place("s/3001", colour=4)]
    )
    analysis = analyze_model(model)
    assert analysis.summary.part_counts == {"S\\3001": 1, "s/3001": 1}
    assert [(row.part, row.quantity) for row in analysis.bom] == [("S\\3001", 2)]


def test_submodel_view_ignores_unrelated_siblings_but_checks_reachable_geometry() -> (
    None
):
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001", colour=4)])
    selected = Model(name="selected.ldr")
    selected.add_submodel(leaf)
    sibling = Model(
        name="sibling.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")]
    )
    root = Model(name="main.ldr")
    root.add_submodel(selected)
    root.submodels["sibling.ldr"] = sibling
    view = root.submodel_view("selected.ldr")
    assert compare_inventory(view, bill_of_materials(view)).matched
    assert compare_inventory(
        view.submodel_view("leaf.ldr"), bill_of_materials(leaf)
    ).matched
    with pytest.raises(ValueError, match=r"sibling.ldr.*point1.x=nan"):
        compare_inventory(root, [])
    leaf.add(parse_ldraw_line("3 24 0 0 0 inf 0 0 1 1 1"))
    with pytest.raises(ValueError, match=r"leaf.ldr.*point2.x=inf"):
        compare_inventory(view, [])
    with pytest.raises(ValueError, match=r"sibling.ldr.*point1.x=nan"):
        compare_inventory(view.submodel_view("sibling.ldr"), [])


def test_comparison_reuses_source_analysis_and_recomputes_after_mutation() -> None:
    piece = Piece.place("3001", colour=4)
    root = Model(objects=[piece])
    expected = bill_of_materials(root)
    with patch(
        "ldraw.validation._placement_analysis", wraps=_placement_analysis
    ) as check:
        assert compare_inventory(root, expected).matched
    assert check.call_count == 1
    piece.position.x = float("nan")
    with pytest.raises(ValueError, match=r"position\.x=nan"):
        compare_inventory(root, expected)


def test_repeated_source_object_is_checked_once_and_counted_twice() -> None:
    piece = Piece.place("3001", colour=4)
    model = Model(objects=[piece, piece])
    with patch(
        "ldraw.validation._placement_analysis", wraps=_placement_analysis
    ) as check:
        comparison = compare_inventory(model, bill_of_materials(model))
    assert comparison.matched
    assert check.call_count == 1
    assert bill_of_materials(model)[0].quantity == 2


def test_group_effective_transforms_are_shared_for_repeated_submodels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = Group(matrix=Matrix.rotation(x=17, y=31, z=23))
    leaf = Piece.place("3001", colour=4, group=group)
    child = Model(name="child.ldr", objects=[leaf])
    root = Model(name="main.ldr")
    root.add_submodel(child)
    root.add_submodel(child)
    expected = bill_of_materials(root)
    calls: Counter[Piece] = Counter()
    original = Piece._transformed  # noqa: SLF001 - invocation reuse regression

    def track(piece: Piece) -> tuple[Vector, Matrix]:
        calls[piece] += 1
        return original(piece)

    monkeypatch.setattr(Piece, "_transformed", track)
    assert compare_inventory(root, expected).matched
    assert calls == Counter(dict.fromkeys([*root.pieces, leaf], 1))


def test_custom_model_traversal_is_checked_as_an_occurrence_provider() -> None:
    class CustomModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            for occurrence in super().iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            ):
                yield replace(occurrence, position=Vector(float("inf"), 0, 0))

    model = CustomModel(objects=[Piece.place("3001")])
    with pytest.raises(ValueError, match=r"position\.x=inf"):
        compare_inventory(model, [])


def test_invalid_placement_of_empty_submodel_is_not_ignored() -> None:
    root = Model(name="main.ldr")
    root.add_submodel(Model(name="empty.ldr"), position=Vector(float("inf"), 0, 0))
    with pytest.raises(ValueError, match=r"position\.x=inf"):
        compare_inventory(root, [])


def test_view_cycles_still_fail_comparison() -> None:
    child = Model(name="child.ldr", objects=[Piece.place("child.ldr")])
    root = Model(name="main.ldr", submodels={"child.ldr": child})
    with pytest.raises(SubmodelCycleError):
        compare_inventory(root.submodel_view("child.ldr"), [])


@pytest.mark.parametrize("singular", [False, True])
def test_nonfinite_group_does_not_hide_local_matrix_warnings(*, singular: bool) -> None:
    group = Group(matrix=Matrix([[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]]))
    piece = Piece.place(
        "3001",
        matrix=Matrix([[0 if singular else 2, 0, 0], [0, 1, 0], [0, 0, 1]]),
        group=group,
    )
    codes = {
        issue.code
        for issue in iter_object_issues(piece, number=7, parts=None, submodels=set())
    }
    assert DiagnosticCode.MODEL_NON_FINITE_NUMERIC in codes
    assert (
        DiagnosticCode.MODEL_SINGULAR_MATRIX
        if singular
        else DiagnosticCode.MODEL_NON_ORTHONORMAL_MATRIX
    ) in codes


def test_section_validation_skips_geometry_without_source_lines() -> None:
    model = Model(objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    with patch(
        "ldraw.validation._object_analysis", side_effect=AssertionError("unused")
    ):
        assert (
            list(_iter_section_issues(model, parts=None, submodels=set(), path=None))
            == []
        )
    with pytest.raises(ValueError, match=r"point1\.x=nan"):
        compare_inventory(model, [])


def test_cli_prepares_and_rejects_submodels_once_before_listing(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 missing.ldr\n")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n")
    with (
        patch(
            "ldraw.bom._prepare_inventory_occurrences",
            wraps=_prepare_inventory_occurrences,
        ) as guard,
        patch("ldraw.cli._bom._inventory_parts", side_effect=AssertionError("listing")),
    ):
        assert main(["bom", str(model), "--compare", str(inventory)]) == 2
    guard.assert_called_once()


def test_valid_comparison_prepares_structure_and_expands_once() -> None:
    from ldraw.model import _iter_inventory_occurrences

    model = Model(objects=[Piece.place("3001", colour=4)])
    with (
        patch(
            "ldraw.bom._prepare_inventory_occurrences",
            wraps=_prepare_inventory_occurrences,
        ) as guard,
        patch(
            "ldraw.model._iter_inventory_occurrences", wraps=_iter_inventory_occurrences
        ) as expansion,
    ):
        assert compare_inventory(model, bill_of_materials(model)).matched
    guard.assert_called_once()
    expansion.assert_called_once()
