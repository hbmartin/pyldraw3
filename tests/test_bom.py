"""Tests for bill-of-materials extraction."""

import json
from pathlib import Path

from ldraw.bom import BOM_FIELDS, BomRow, bill_of_materials, rows_to_csv, rows_to_json
from ldraw.colour import Colour
from ldraw.model import Model, read_model
from ldraw.parts import Parts
from ldraw.pieces import Piece

TESTS_DIR = Path(__file__).resolve().parent
MODELS_DIR = TESTS_DIR / "models"


def test_bom_counts_leaf_pieces_without_catalog() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    rows = model.bill_of_materials()

    assert rows == [
        BomRow(
            part="3001",
            description=None,
            colour_code=14,
            colour_name=None,
            quantity=1,
        ),
        BomRow(
            part="3005",
            description=None,
            colour_code=0,
            colour_name=None,
            quantity=1,
        ),
        BomRow(
            part="3005",
            description=None,
            colour_code=4,
            colour_name=None,
            quantity=1,
        ),
    ]


def test_bom_resolves_main_colour_to_placed_colour() -> None:
    root = Model(name="main.ldr")
    arm = Model(name="arm.ldr", objects=[Piece.place("3001", colour=16)])
    root.add_submodel(arm, colour=4)

    rows = root.bill_of_materials()

    assert [(row.part, row.colour_code, row.quantity) for row in rows] == [
        ("3001", 4, 1),
    ]


def test_bom_resolves_main_colour_through_nested_submodels() -> None:
    inner = Model(name="inner.ldr", objects=[Piece.place("3005", colour=16)])
    outer = Model(name="outer.ldr")
    outer.add_submodel(inner, colour=16)
    root = Model(name="main.ldr")
    root.add_submodel(outer, colour=1)

    rows = root.bill_of_materials()

    assert [(row.part, row.colour_code, row.quantity) for row in rows] == [
        ("3005", 1, 1),
    ]


def test_bom_placed_colours_split_rows() -> None:
    root = Model(name="main.ldr")
    arm = Model(name="arm.ldr", objects=[Piece.place("3001", colour=16)])
    root.add_submodel(arm, colour=4)
    root.add_submodel(arm, colour=1)

    rows = root.bill_of_materials()

    assert [(row.part, row.colour_code, row.quantity) for row in rows] == [
        ("3001", 1, 1),
        ("3001", 4, 1),
    ]


def test_bom_root_level_main_colour_stays_16() -> None:
    model = Model(objects=[Piece.place("3001", colour=16)])

    rows = model.bill_of_materials()

    assert [(row.part, row.colour_code, row.quantity) for row in rows] == [
        ("3001", 16, 1),
    ]


def test_bom_counts_repeated_submodel_references_twice() -> None:
    root = Model(name="main.ldr")
    wheels = Model(
        name="wheels.ldr",
        objects=[Piece.place("3005", colour=0)],
    )
    root.add_submodel(wheels)
    root.add(Piece.place("wheels", suffix=".LDR"))

    rows = root.bill_of_materials()

    assert rows == [
        BomRow(
            part="3005",
            description=None,
            colour_code=0,
            colour_name=None,
            quantity=2,
        ),
    ]


def test_bom_resolves_description_and_colour_name_from_catalog() -> None:
    parts = Parts.get(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")
    model = Model(objects=[Piece.place("3001", colour=189)])

    rows = bill_of_materials(model, parts=parts)

    assert rows == [
        BomRow(
            part="3001",
            description="Brick  2 x  4",
            colour_code=189,
            colour_name="Reddish_Gold",
            quantity=1,
        ),
    ]


def test_bom_counts_codes_case_insensitively(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "123abc.dat").write_text("0 Test Part\n")
    (ldraw_dir / "parts.lst").write_text("123abc.dat  Test Part\n")
    parts = Parts(ldraw_dir / "parts.lst")
    # Mixed-case references to the same part count as one row, shown with
    # the code as first written; the description lookup is case-tolerant.
    model = Model(objects=[Piece.place("123ABC"), Piece.place("123abc")])

    rows = bill_of_materials(model, parts=parts)

    assert len(rows) == 1
    assert rows[0].part == "123ABC"
    assert rows[0].quantity == 2
    assert rows[0].description == "Test Part"


def test_bom_unknown_part_and_colour_stay_unresolved() -> None:
    parts = Parts.get(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")
    model = Model(objects=[Piece.place("9999", colour=99)])

    rows = bill_of_materials(model, parts=parts)

    assert rows == [
        BomRow(
            part="9999",
            description=None,
            colour_code=99,
            colour_name=None,
            quantity=1,
        ),
    ]


def test_bom_keeps_colour_name_carried_by_the_piece() -> None:
    red = Colour(4, "Red", "#C91A09", 255)
    model = Model(objects=[Piece.place("3001", colour=red)])

    rows = bill_of_materials(model)

    assert rows[0].colour_name == "Red"


def test_bom_direct_colour_uses_rgb_as_name() -> None:
    model = Model(
        objects=[Piece.place("3001", colour=Colour(rgb="#FF0000", alpha=255))],
    )

    rows = bill_of_materials(model)

    assert rows == [
        BomRow(
            part="3001",
            description=None,
            colour_code=None,
            colour_name="#FF0000",
            quantity=1,
        ),
    ]


def test_bom_of_empty_model_is_empty() -> None:
    assert bill_of_materials(Model()) == []


def test_bom_sorts_coded_before_direct_colours() -> None:
    model = Model(
        objects=[
            Piece.place("3001", colour=Colour(rgb="#FF0000", alpha=255)),
            Piece.place("3001", colour=4),
        ],
    )

    rows = bill_of_materials(model)

    assert [row.colour_code for row in rows] == [4, None]


def test_rows_to_csv_exact_text() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    csv_text = rows_to_csv(model.bill_of_materials())

    assert csv_text == (
        "part,description,colour_code,colour_name,quantity\n"
        "3001,,14,,1\n"
        "3005,,0,,1\n"
        "3005,,4,,1\n"
    )


def test_rows_to_json_round_trips() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    parsed = json.loads(rows_to_json(model.bill_of_materials()))

    assert len(parsed) == 3
    assert all(tuple(entry) == BOM_FIELDS for entry in parsed)
    assert parsed[0] == {
        "part": "3001",
        "description": None,
        "colour_code": 14,
        "colour_name": None,
        "quantity": 1,
    }


def test_model_method_matches_module_function() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    assert model.bill_of_materials() == bill_of_materials(model)
