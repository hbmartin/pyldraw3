"""Regression coverage for identity, scoped traversal, and shared CLI analysis."""

from collections import Counter
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from ldraw._model_validation import ModelValidationContext
from ldraw.bom import _prepare_model_inventory, bill_of_materials, compare_inventory
from ldraw.cli import main
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.instruction_artifacts import instruction_manifest
from ldraw.model import (
    Model,
    _iter_inventory_occurrences,
    _iter_model_occurrences,
    _load_inventory_model,
    load_model,
    parse_model,
)
from ldraw.part import parse_ldraw_line
from ldraw.parts import Parts
from ldraw.pieces import Group, Piece
from ldraw.validation import _placement_analysis

TEST_LIBRARY = Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst"
IDENTITY = "1 0 0 0 1 0 0 0 1"


@pytest.mark.parametrize(
    ("part", "suffix", "expected"),
    [
        ("custom.v1", ".dat", "custom.v1.dat"),
        ("CUSTOM.DAT.V1", ".DAT", "CUSTOM.DAT.V1.DAT"),
        ("custom.v1", "", "custom.v1"),
        ("custom.v1", ".V1", "custom.v1"),
        ("custom.v1", ".ldr", "custom.v1.ldr"),
        ("custom.v1", ".other", "custom.v1.other"),
        ("body.LDR", ".dat", "body.LDR"),
        ("body.LDR", ".ldr", "body.LDR"),
        ("body.LDR", ".mpd", "body.LDR.mpd"),
        ("body.MPD", ".dat", "body.MPD"),
        ("custom.v1.DAT", ".dat", "custom.v1.DAT"),
        ("custom", ".v1", "custom.v1"),
    ],
)
def test_factory_distinguishes_dotted_codes_and_explicit_suffixes(
    part: str, suffix: str, expected: str
) -> None:
    piece = Piece.place(part, suffix=suffix)
    assert piece.reference == expected
    assert parse_ldraw_line(piece.to_ldraw()).reference == expected


def test_dotted_factory_matches_constructor_and_its_exported_inventory() -> None:
    placed = Piece.place("custom.v1", colour=4)
    constructed = Piece(
        colour=4, position=Vector(0, 0, 0), matrix=Identity(), part="custom.v1"
    )
    assert placed.reference == constructed.reference == "custom.v1.dat"
    model = Model(objects=[placed, constructed])
    rows = bill_of_materials(model)
    assert [(row.part, row.quantity) for row in rows] == [("custom.v1", 2)]
    assert compare_inventory(model, rows).matched


@pytest.mark.parametrize("suffix", [".ldr", ".MPD"])
def test_manifest_v1_distinguishes_submodel_references_in_both_placement_views(
    suffix: str,
) -> None:
    text = (
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} 3001{suffix}\n"
        f"1 4 20 0 0 {IDENTITY} 3001.dat\n"
    )
    model = parse_model(text)
    parts = Parts(parts_lst=TEST_LIBRARY)
    manifest = instruction_manifest(
        model.instruction_document(parts=parts), parts=parts
    )
    assert manifest["schema_version"] == 1
    step = manifest["sections"][0]["steps"][0]
    for field in ("direct_placements", "added_occurrences"):
        assert [item["part"] for item in step[field]] == [f"3001{suffix}", "3001"]
        assert step[field][0]["description"] is None
        assert step[field][1]["description"] == parts.description_for("3001")
    assert model.pieces[0].part == "3001"
    assert model.pieces[0].reference == f"3001{suffix}"


def test_root_name_view_checks_only_reachable_sections_and_stays_live() -> None:
    reachable = Model(name="child.ldr", objects=[Piece.place("3001")])
    sibling = Model(name="orphan.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    root = Model(name="main.ldr", submodels={"orphan.ldr": sibling})
    root.add_submodel(reachable)
    view = root.submodel_view("MAIN.LDR")
    assert compare_inventory(view, bill_of_materials(view)).matched
    assert compare_inventory(
        view.submodel_view(view.name), bill_of_materials(view)
    ).matched
    with pytest.raises(ValueError, match=r"orphan.ldr.*point1.x=nan"):
        compare_inventory(root, [])
    reachable.add(parse_ldraw_line("2 24 inf 0 0 1 1 1"))
    with pytest.raises(ValueError, match=r"child.ldr.*point1.x=inf"):
        compare_inventory(view, [])


@pytest.mark.parametrize("with_context", [False, True])
def test_generic_traversal_composes_parent_transform_with_source_cache(
    *, with_context: bool
) -> None:
    group = Group(position=Vector(2, 0, 0))
    piece = Piece.place("3001", position=Vector(3, 0, 0), group=group)
    model = Model(objects=[piece])
    context = ModelValidationContext(
        placements={piece: piece._transformed()}  # noqa: SLF001 - cached group transform
    )
    occurrence = next(
        _iter_model_occurrences(
            root=model,
            model=model,
            position=Vector(10, 0, 0),
            matrix=Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]),
            inherited_colour=None,
            visiting=frozenset(),
            inherited_step=None,
            path=(),
            expand_submodels=True,
            include_steps=False,
            context=context if with_context else None,
        )
    )
    assert occurrence.position == Vector(20, 0, 0)
    assert occurrence.matrix == Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]])


@pytest.mark.parametrize("terminal", ["empty", "geometry"])
def test_composition_overflow_is_rejected_before_entering_leafless_submodel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], terminal: str
) -> None:
    end = "" if terminal == "empty" else "2 24 0 0 0 1 1 1\n"
    text = (
        "0 FILE main.ldr\n"
        "1 4 0 0 0 1e200 0 0 0 1 0 0 0 1 middle.ldr\n"
        "0 FILE middle.ldr\n"
        "1 16 0 0 0 1e200 0 0 0 1 0 0 0 1 end.ldr\n"
        f"0 FILE end.ldr\n{end}"
    )
    model = parse_model(text)
    source = tmp_path / "overflow.mpd"
    source.write_text(text)
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n")
    output = tmp_path / "comparison.json"
    output.write_text("existing output")
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match=r"middle.ldr:4:.*matrix\[0\]\[0\]=inf"):
            compare_inventory(model, [])
        assert (
            main(["bom", str(source), "--compare", str(inventory), "-o", str(output)])
            == 2
        )
    assert "middle.ldr:4:" in capsys.readouterr().err
    assert output.read_text() == "existing output"


def test_comparison_reuses_view_discovery_resolutions_and_repeated_targets() -> None:
    leaf = Model(name="leaf.ldr", objects=[Piece.place("3001")])
    selected = Model(name="selected.ldr")
    selected.add_submodel(leaf)
    selected.add_submodel(leaf)
    root = Model(
        name="main.ldr", submodels={"selected.ldr": selected, "leaf.ldr": leaf}
    )
    view = root.submodel_view(selected.name)
    expected = bill_of_materials(view)
    original = Model.submodel_for
    calls: Counter[Piece] = Counter()

    def resolve(model: Model, piece: Piece) -> Model | None:
        calls[piece] += 1
        return original(model, piece)

    with patch.object(Model, "submodel_for", resolve):
        assert compare_inventory(view, expected).matched
    assert calls == Counter(dict.fromkeys([*selected.pieces, *leaf.pieces], 1))


def test_cli_and_api_share_preparation_and_check_flat_sources_once(
    tmp_path: Path,
) -> None:
    source = tmp_path / "model.ldr"
    source.write_text(f"1 4 0 0 0 {IDENTITY} 3001.dat\n")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n")
    with (
        patch(
            "ldraw.validation._placement_analysis", wraps=_placement_analysis
        ) as numeric,
        patch(
            "ldraw.cli._bom._prepare_model_inventory", wraps=_prepare_model_inventory
        ) as prepare,
        patch(
            "ldraw.model._iter_inventory_occurrences", wraps=_iter_inventory_occurrences
        ) as expansion,
        patch("ldraw.cli._bom._parts_lst_path", side_effect=AssertionError("listing")),
    ):
        assert main(["bom", str(source), "--compare", str(inventory)]) == 0
    numeric.assert_called_once()
    prepare.assert_called_once()
    expansion.assert_called_once()
    model = parse_model(source.read_text())
    expected = bill_of_materials(model)
    with patch(
        "ldraw.validation._placement_analysis", wraps=_placement_analysis
    ) as numeric:
        assert compare_inventory(model, expected).matched
    numeric.assert_called_once()


@pytest.mark.parametrize(
    "content", [None, b"\xff", b"1 4 invalid\n", b"2 24 nan 0 0 1 1 1\n"]
)
def test_private_comparison_loading_preserves_public_reports(
    tmp_path: Path, content: bytes | None
) -> None:
    source = tmp_path / "model.ldr"
    if content is not None:
        source.write_bytes(content)
    expected = load_model(source)
    result, _ = _load_inventory_model(source)
    assert result.complete == expected.complete
    assert result.valid == expected.valid
    assert [issue.to_dict() for issue in result.diagnostics] == [
        issue.to_dict() for issue in expected.diagnostics
    ]
