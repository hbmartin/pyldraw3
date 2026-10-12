"""Inventory comparison contracts, including CLI failure boundaries."""

import json
from pathlib import Path

import pytest

from ldraw.bom import BomRow, compare_inventory, read_inventory, rows_to_csv
from ldraw.cli import main
from ldraw.colour import Colour
from ldraw.geometry import Identity, Matrix, Radians, XAxis, YAxis, ZAxis
from ldraw.model import Model, parse_model_result
from ldraw.pieces import Piece
from ldraw.units import BRICK_HEIGHT, LDU_TO_MM, PLATE_HEIGHT, STUD_PITCH


def test_rotation_factory() -> None:
    assert Matrix.rotation() == Identity()
    for name, axis in (("x", XAxis), ("y", YAxis), ("z", ZAxis)):
        assert Matrix.rotation(**{name: 90}).flatten() == pytest.approx(
            Identity().rotate(90, axis).flatten()
        )
    assert Matrix.rotation(x=20, y=30, z=40).flatten() == pytest.approx(
        Identity().rotate(20, XAxis).rotate(30, YAxis).rotate(40, ZAxis).flatten()
    )
    assert Matrix.rotation(
        x=3.141592653589793 / 2, units=Radians
    ).flatten() == pytest.approx(Matrix.rotation(x=90).flatten())
    first = Matrix.rotation()
    first.rows = [[2, 0, 0], [0, 2, 0], [0, 0, 2]]
    assert Matrix.rotation() == Identity()
    assert (STUD_PITCH, PLATE_HEIGHT, BRICK_HEIGHT, LDU_TO_MM) == (20, 8, 24, 0.4)


def test_inventory_nested_aliases_and_repeated_rows(tmp_path: Path) -> None:
    inner = Model(name="inner.ldr", objects=[Piece.place("OLD", colour=16)])
    outer = Model(name="outer.ldr")
    outer.add_submodel(inner)
    root = Model(name="root.ldr")
    root.add_submodel(outer, colour=4)
    root.add_submodel(outer, colour=4)
    csv = tmp_path / "inventory.csv"
    csv.write_text("ID,Color,Count\nNEW,red,1\nold.dat,red,1\n", encoding="utf-8")
    rows = read_inventory(
        csv,
        columns={"part": "ID", "colour": "Color", "quantity": "Count"},
        colour_map={"red": 4},
    )
    assert compare_inventory(root, rows, part_aliases={"OLD.DAT": "new"}).matched
    result = compare_inventory(root, rows)
    assert [
        (d.part, d.expected, d.actual, d.missing, d.extra) for d in result.differences
    ] == [("new", 1, 0, 1, 0), ("old", 1, 2, 0, 1)]
    assert result.to_dict()["matched"] is False


def test_native_rgb_inventory(tmp_path: Path) -> None:
    root = Model(objects=[Piece.place("3001", colour=Colour(rgb="#ABCDEF"))])
    csv = tmp_path / "native.csv"
    csv.write_text(rows_to_csv(root.bill_of_materials()), encoding="utf-8")
    assert compare_inventory(root, read_inventory(csv)).matched


@pytest.mark.parametrize(
    "text",
    [
        "part,quantity\n3001,1\n",
        "part,colour_code,quantity\n,4,1\n",
        "part,colour_code,quantity\n3001,4,-1\n",
        "part,colour_code,quantity\n3001,4,1.5\n",
        "part,colour_code,quantity\n3001,red,1\n",
        "part,colour_code,quantity\n3001,4,1,extra\n",
        "part,part,quantity\n3001,4,1\n",
    ],
)
def test_invalid_inventory(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        read_inventory(path)


def test_mapping_errors(tmp_path: Path) -> None:
    csv = tmp_path / "native.csv"
    csv.write_text("part,colour_code,quantity\n3001,4,1\n", encoding="utf-8")
    for kwargs in (
        {"columns": {"bad": "name"}},
        {"columns": {"part": ""}},
        {"colour_map": {}},
    ):
        with pytest.raises(ValueError):
            read_inventory(csv, **kwargs)
    with pytest.raises(ValueError, match="cyclic"):
        compare_inventory(Model(), [], part_aliases={"a": "b", "b": "a"})
    with pytest.raises(ValueError, match="quantities"):
        compare_inventory(Model(), [BomRow("3001", None, 4, None, -1)])
    with pytest.raises(ValueError, match="unresolved"):
        compare_inventory(Model(objects=[Piece.place("missing.ldr")]), [])


@pytest.mark.parametrize("output_format", ["table", "csv", "json"])
def test_comparison_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], output_format: str
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n", encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n", encoding="utf-8")
    args = ["bom", str(model), "--compare", str(inventory), "--format", output_format]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert text
    if output_format == "json":
        assert json.loads(text) == {"matched": True, "differences": []}
    inventory.write_text("part,colour_code,quantity\n3001,4,3\n", encoding="utf-8")
    out = tmp_path / "comparison.txt"
    assert main([*args, "--output", str(out)]) == 1
    assert out.read_text()
    model.write_text("1 malformed\n", encoding="utf-8")
    assert main(args) == 2
    assert "incomplete" in capsys.readouterr().err


def test_comparison_mapping_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n", encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("id,color,count\nbrick,red,1\n", encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "columns": {"part": "id", "colour": "color", "quantity": "count"},
                "part_aliases": {"brick": "3001"},
                "colour_map": {"red": 4},
            }
        ),
        encoding="utf-8",
    )
    args = [
        "bom",
        str(model),
        "--compare",
        str(inventory),
        "--inventory-mapping",
        str(mapping),
    ]
    assert main(args) == 0
    for bad in (
        [],
        {"unknown": {}},
        {"columns": []},
        {"part_aliases": {"a": 2}},
        {"colour_map": {"red": True}},
    ):
        mapping.write_text(json.dumps(bad), encoding="utf-8")
        assert main(args) == 2
    assert main(["bom", str(model), "--inventory-mapping", str(mapping)]) == 2
    assert "requires --compare" in capsys.readouterr().err


def test_duplicate_placements_are_section_local() -> None:
    line = "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat"
    text = "\n".join(
        (
            "0 FILE main.ldr",
            line,
            "0 STEP",
            line.upper(),
            line.replace("1 4 ", "1 1 "),
            line.replace("0 0 0 1 3001", "0 0 0 -1 3001"),
            "0 FILE child.ldr",
            line,
        )
    )
    report = parse_model_result(text)
    duplicates = [
        d for d in report.diagnostics if d.code.value == "model.duplicate_placement"
    ]
    assert len(duplicates) == 1
    assert duplicates[0].line_number == 4
    assert "line 2" in duplicates[0].message
    assert duplicates[0].section == "main.ldr"


def test_duplicates_strict_cli(tmp_path: Path) -> None:
    path = tmp_path / "model.ldr"
    line = "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
    path.write_text(line * 2, encoding="utf-8")
    assert main(["validate", str(path)]) == 0
    assert main(["validate", str(path), "--strict"]) == 1
