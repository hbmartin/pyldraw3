"""Subclass traversal, live-view, and invocation-cache regressions."""

import builtins
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from ldraw._model_validation import ModelValidationContext
from ldraw.bom import BomRow, _prepare_model_inventory, compare_inventory
from ldraw.cli import main
from ldraw.geometry import Vector
from ldraw.instructions import iter_instruction_issues
from ldraw.model import Model, ModelOccurrence, _iter_inventory_occurrences, parse_model
from ldraw.part import ParsedObject, parse_ldraw_line
from ldraw.pieces import Piece
from ldraw.validation import _placement_analysis

IDENTITY = "1 0 0 0 1 0 0 0 1"


class InheritedModel(Model):
    """Keep the built-in traversal through a subclass."""


class CustomModel(Model):
    """Override traversal without changing its emitted leaves."""

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Use a custom entry point with otherwise unchanged traversal."""
        return super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        )


class RelabeledModel(Model):
    """Require custom constructor state used by an authoritative traversal."""

    def __init__(
        self, *, part_code: str, name: str = "", objects: Iterable[ParsedObject] = ()
    ) -> None:
        super().__init__(name=name, objects=list(objects))
        self.part_code = part_code

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Apply the subclass's stored identity override."""
        for occurrence in super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        ):
            yield replace(occurrence, part_code=self.part_code)


def expected_row(part: str = "3001", *, quantity: int = 1) -> list[BomRow]:
    return [
        BomRow(
            part=part,
            description=None,
            colour_code=4,
            colour_name=None,
            quantity=quantity,
        )
    ]


@pytest.mark.parametrize("model_type", [InheritedModel, CustomModel])
@pytest.mark.parametrize("terminal", ["empty", "geometry", "part"])
def test_subclasses_reject_overflow_before_entering_any_submodel(
    model_type: type[Model], terminal: str
) -> None:
    ending = {
        "empty": "",
        "geometry": "2 24 0 0 0 1 1 1\n",
        "part": f"1 16 0 0 0 {IDENTITY} 3001.dat\n",
    }[terminal]
    source = parse_model(
        "0 FILE main.ldr\n"
        "1 4 0 0 0 1e200 0 0 0 1 0 0 0 1 middle.ldr\n"
        "0 FILE middle.ldr\n"
        "1 16 0 0 0 1e200 0 0 0 1 0 0 0 1 end.ldr\n"
        f"0 FILE end.ldr\n{ending}"
    )
    model = model_type(
        name=source.name, objects=source.objects, submodels=source.submodels
    )
    with (
        np.errstate(over="ignore", invalid="ignore"),
        pytest.raises(ValueError, match=r"middle.ldr:4:.*matrix\[0\]\[0\]=inf"),
    ):
        compare_inventory(model, [])


def test_inherited_traversal_uses_one_source_analysis_and_one_expansion() -> None:
    model = InheritedModel(
        objects=[
            Piece.place("3001", colour=4, position=Vector(i, 0, 0)) for i in range(5)
        ]
    )
    with (
        patch(
            "ldraw.validation._placement_analysis", wraps=_placement_analysis
        ) as analyses,
        patch(
            "ldraw.model._iter_inventory_occurrences", wraps=_iter_inventory_occurrences
        ) as traversals,
    ):
        assert compare_inventory(model, expected_row(quantity=5)).matched
    assert analyses.call_count == 5
    assert traversals.call_count == 1


@pytest.mark.parametrize("root_view", [False, True])
def test_views_preserve_subclass_state_overrides_sources_and_scope(
    *, root_view: bool
) -> None:
    piece = Piece.place("3001", colour=4)
    selected = RelabeledModel(
        part_code="alternate", name="selected.ldr", objects=[piece]
    )
    selected._source_lines[piece] = 7  # noqa: SLF001 - source sharing regression
    sibling = Model(name="orphan.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    root = selected if root_view else Model(name="main.ldr")
    root.submodels = {"orphan.ldr": sibling}
    if not root_view:
        root.add_submodel(selected)
    with patch.object(
        target=RelabeledModel,
        attribute="__init__",
        side_effect=AssertionError("views must not invoke custom constructors"),
    ):
        view = root.submodel_view(selected.name)
    assert isinstance(view, RelabeledModel)
    assert view is not selected
    assert view.objects is selected.objects
    assert view.submodels is root.submodels
    assert view.part_code == "alternate"
    assert view.source_line_for(piece) == 7
    assert next(view.iter_occurrences()).part_code == "alternate"
    assert compare_inventory(view, expected_row("alternate")).matched
    with pytest.raises(ValueError, match=r"orphan.ldr.*point1.x=nan"):
        compare_inventory(root, [])
    selected.add(Piece.place("3001", colour=4))
    assert compare_inventory(view, expected_row("alternate", quantity=2)).matched
    selected.add(parse_ldraw_line("2 24 inf 0 0 1 1 1"))
    with pytest.raises(ValueError, match=r"selected.ldr.*point1.x=inf"):
        compare_inventory(view, [])


@pytest.mark.parametrize("cycle", [False, True])
def test_custom_numeric_audit_keeps_override_leaves_and_ignores_source_structure(
    *, cycle: bool
) -> None:
    known = Model(objects=[Piece.place("3001", colour=4)])

    class FixedModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            return known.iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            )

    root = FixedModel(name="main.ldr", objects=[Piece.place("missing.ldr")])
    if cycle:
        child = Model(name="child.ldr", objects=[Piece.place("main.ldr")])
        root.add_submodel(child)
    assert compare_inventory(root, expected_row()).matched


def test_custom_transformed_occurrences_are_still_checked() -> None:
    class ShiftedModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            for occurrence in super().iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            ):
                yield replace(occurrence, position=Vector(float("inf"), 0, 0))

    with pytest.raises(ValueError, match=r"position.x=inf"):
        compare_inventory(ShiftedModel(objects=[Piece.place("3001", colour=4)]), [])


def test_custom_resolver_is_audited_even_with_an_empty_submodel_table() -> None:
    known = Model(objects=[Piece.place("3001", colour=4)])
    middle = Model(
        name="middle.ldr",
        objects=[parse_ldraw_line("1 16 0 0 0 1e200 0 0 0 1 0 0 0 1 end.ldr")],
    )
    end = Model(name="end.ldr")

    class DynamicModel(Model):
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            return known.iter_occurrences(
                expand_submodels=expand_submodels, include_steps=include_steps
            )

        def submodel_for(self, reference: Piece | str) -> Model | None:
            reference = (
                reference.reference if isinstance(reference, Piece) else reference
            )
            return {"middle.ldr": middle, "end.ldr": end}.get(reference)

    root = DynamicModel(
        name="main.ldr",
        objects=[parse_ldraw_line("1 4 0 0 0 1e200 0 0 0 1 0 0 0 1 middle.ldr")],
    )
    with (
        np.errstate(over="ignore", invalid="ignore"),
        pytest.raises(ValueError, match=r"middle.ldr:.*matrix\[0\]\[0\]=inf"),
    ):
        compare_inventory(root, expected_row())


def test_partial_context_completes_validation_and_restores_missing_placements() -> None:
    model = Model(
        objects=[Piece.place("3001", colour=4), Piece.place("3001", colour=4)]
    )
    context = ModelValidationContext()
    first = model.pieces[0]
    context.placements[first] = first.position, first.matrix
    assert len(_prepare_model_inventory(model, context=context)) == 2
    context.placements.clear()
    assert len(list(_iter_inventory_occurrences(model, context=context))) == 2
    assert set(context.placements) == set(model.pieces)


def test_partial_context_does_not_skip_programmatic_geometry() -> None:
    model = Model(objects=[Piece.place("3001"), parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    context = ModelValidationContext()
    piece = model.pieces[0]
    context.placements[piece] = piece.position, piece.matrix
    with pytest.raises(ValueError, match=r"point1.x=nan"):
        _prepare_model_inventory(model, context=context)


def test_missing_cached_invalid_placement_reports_source_location() -> None:
    model = parse_model(f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} 3001.dat\n")
    context = ModelValidationContext()
    _prepare_model_inventory(model, context=context)
    context.placements.clear()
    model.pieces[0].position = Vector(float("nan"), 0, 0)
    with pytest.raises(ValueError, match=r"main.ldr:2:.*position.x=nan"):
        list(_iter_inventory_occurrences(model, context=context))


@pytest.mark.parametrize("prepare", [False, True])
def test_context_rejects_other_resolution_roots(*, prepare: bool) -> None:
    piece = Piece.place("child.ldr")
    first = Model(objects=[piece], submodels={"child.ldr": Model(name="child.ldr")})
    second = Model(objects=[piece], submodels={"child.ldr": Model(name="child.ldr")})
    context = ModelValidationContext()
    assert context.resolve(root=first, piece=piece) is first.submodels["child.ldr"]
    if prepare:
        with pytest.raises(ValueError, match="different resolution root"):
            _prepare_model_inventory(second, context=context)
    else:
        with pytest.raises(ValueError, match="different resolution root"):
            context.resolve(root=second, piece=piece)


def test_scope_completion_can_expand_from_reachable_to_declared_sections() -> None:
    root = Model(
        name="main.ldr",
        objects=[Piece.place("3001")],
        submodels={
            "orphan.ldr": Model(objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
        },
    )
    context = ModelValidationContext()
    context.ensure_validated(root=root, reachable_only=True)
    with pytest.raises(ValueError, match=r"point1.x=nan"):
        context.ensure_validated(root=root, reachable_only=False)


def test_validation_context_is_fresh_after_mutation() -> None:
    model = InheritedModel(objects=[Piece.place("3001", colour=4)])
    assert compare_inventory(model, expected_row()).matched
    model.pieces[0].position = Vector(float("nan"), 0, 0)
    with pytest.raises(ValueError, match=r"position.x=nan"):
        compare_inventory(model, expected_row())


def test_provider_keeps_immediate_unresolved_reference_precedence() -> None:
    source = Model(objects=[Piece.place("missing.ldr"), Piece.place("3001")])
    calls: Counter[int] = Counter()

    class Provider:
        def iter_occurrences(
            self, *, expand_submodels: bool = True, include_steps: bool = True
        ) -> Iterator[ModelOccurrence]:
            for index, occurrence in enumerate(
                source.iter_occurrences(
                    expand_submodels=expand_submodels, include_steps=include_steps
                )
            ):
                calls[index] += 1
                yield (
                    replace(occurrence, position=Vector(float("nan"), 0, 0))
                    if index
                    else occurrence
                )

    with pytest.raises(ValueError, match="unresolved submodel reference"):
        compare_inventory(Provider(), [])
    assert calls == Counter({0: 1})


def test_concrete_numeric_error_precedes_structure_without_listing_access(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} missing.ldr\n"
        f"1 4 nan 0 0 {IDENTITY} 3001.dat\n"
        f"1 4 0 0 0 {IDENTITY} custom.v1\n"
    )
    with pytest.raises(ValueError, match=r"model.non_finite_numeric.*main.ldr:3:"):
        compare_inventory(parse_model(text), [])
    source = tmp_path / "model.mpd"
    source.write_text(text)
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n")
    with patch(
        "ldraw.cli._bom._parts_lst_path",
        side_effect=AssertionError("invalid models must not request configuration"),
    ):
        assert main(["bom", str(source), "--compare", str(inventory)]) == 2
    assert "model.non_finite_numeric" in capsys.readouterr().err


@pytest.mark.parametrize("suffix", [".ldr", ".LDR", ".mpd", ".MPD"])
@pytest.mark.parametrize("resolved", [False, True])
def test_instruction_reference_issues_cover_both_submodel_suffixes(
    suffix: str, *, resolved: bool
) -> None:
    text = f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} child{suffix}\n"
    if resolved:
        text = f"{text}0 FILE child{suffix}\n1 16 0 0 0 {IDENTITY} 3001.dat\n"
    document = parse_model(text).instruction_document()
    issues = [
        issue
        for issue in iter_instruction_issues(document)
        if issue.code == "unknown-submodel"
    ]
    assert len(issues) == (0 if resolved else 1)
    if issues:
        assert issues[0].line_number == 2


def test_unchecked_nested_traversal_does_not_import_validation_services() -> None:
    root = Model(name="main.ldr")
    root.add_submodel(Model(name="child.ldr", objects=[Piece.place("3001")]))
    with patch("builtins.__import__", wraps=builtins.__import__) as imports:
        assert len(list(root.iter_occurrences())) == 1
    assert not any(
        call.args[0] == "ldraw.validation" for call in imports.call_args_list
    )
