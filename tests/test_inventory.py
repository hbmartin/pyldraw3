"""Inventory comparison contracts, including CLI failure boundaries."""

import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.bom import BomRow, compare_inventory, read_inventory, rows_to_csv
from ldraw.cli import main
from ldraw.colour import Colour
from ldraw.config import Config
from ldraw.geometry import Identity, Matrix, Radians, XAxis, YAxis, ZAxis
from ldraw.model import Model, parse_model_result, read_model
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.units import BRICK_HEIGHT, LDU_TO_MM, PLATE_HEIGHT, STUD_PITCH


@pytest.fixture
def parts() -> Parts:
    return Parts(Path(__file__).parent / "test_ldraw" / "ldraw" / "parts.lst")


def _comparison_files(
    tmp_path: Path, *, reference: str, inventory_code: str
) -> tuple[Path, Path]:
    model = tmp_path / "model.ldr"
    model.write_text(f"1 4 0 0 0 1 0 0 0 1 0 0 0 1 {reference}\n", encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        f"part,colour_code,quantity\n{inventory_code},4,1\n", encoding="utf-8"
    )
    return model, inventory


def test_inventory_bare_parts_require_catalog_evidence(parts: Parts) -> None:
    model = Model(objects=[Piece.place("3001", colour=4, suffix="")])
    expected = [BomRow("3001", None, 4, None, 1)]
    with pytest.raises(ValueError, match=r"3001.*supply a parts catalog"):
        compare_inventory(model, expected)
    assert compare_inventory(model, expected, parts=parts).matched


def test_inventory_alias_cannot_disguise_an_unknown_bare_reference(
    parts: Parts,
) -> None:
    model = Model(objects=[Piece.place("Missing Sub", colour=4, suffix="")])
    with pytest.raises(ValueError, match="Missing Sub"):
        compare_inventory(
            model,
            [BomRow("3001", None, 4, None, 1)],
            part_aliases={"Missing Sub": "3001"},
            parts=parts,
        )


@pytest.mark.parametrize("reference", ["Car v1.5", "body.1", "3001.", "3001.xyz"])
@pytest.mark.parametrize("with_alias", [False, True])
def test_inventory_rejects_unknown_dotted_references_before_aliases(
    tmp_path: Path,
    parts: Parts,
    reference: str,
    *,
    with_alias: bool,
) -> None:
    stem = reference.rsplit(".", maxsplit=1)[0]
    aliases = {reference: "3001", stem: "3001"} if with_alias else None
    expected_code = "3001" if with_alias else stem
    model = Model(objects=[Piece.place(reference, colour=4)])
    with pytest.raises(ValueError, match=r"without an explicit \.dat suffix") as raised:
        compare_inventory(
            model,
            [BomRow(expected_code, None, 4, None, 1)],
            parts=parts,
            part_aliases=aliases,
        )
    assert reference in str(raised.value)
    model_path, inventory = _comparison_files(
        tmp_path, reference=reference, inventory_code=expected_code
    )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"part_aliases": aliases or {}}), encoding="utf-8")
    with patch("ldraw.cli._bom._parts_lst_path", return_value=parts.path):
        assert (
            main(
                [
                    "bom",
                    str(model_path),
                    "--compare",
                    str(inventory),
                    "--inventory-mapping",
                    str(mapping),
                ]
            )
            == 2
        )


@pytest.mark.parametrize("reference", ["3001A", "mIxEd", "CUSTOM.V1"])
@pytest.mark.parametrize("geometry", [None, b"\xff"])
def test_inventory_accepts_listed_identifiers_without_parseable_geometry(
    tmp_path: Path, reference: str, geometry: bytes | None
) -> None:
    root = tmp_path / "library" / "ldraw"
    parts_dir = root / "parts"
    parts_dir.mkdir(parents=True)
    codes = ("3001a", "MiXeD", "custom.v1")
    listing = root / "parts.lst"
    listing.write_text(
        "".join(f"{code}.dat  Brick Listed\n" for code in codes), encoding="utf-8"
    )
    if geometry is not None:
        for code in codes:
            (parts_dir / f"{code}.dat").write_bytes(geometry)
    catalog = Parts(listing)
    model_path, inventory = _comparison_files(
        tmp_path, reference=reference, inventory_code=reference.lower()
    )
    model = parse_model_result(model_path.read_text()).model
    assert model is not None
    assert compare_inventory(model, read_inventory(inventory), parts=catalog).matched
    with patch("ldraw.cli._bom._parts_lst_path", return_value=listing):
        assert main(["bom", str(model_path), "--compare", str(inventory)]) == 0


def test_inventory_expands_extensionless_submodels_without_catalog() -> None:
    child = Model(name="body", objects=[Piece.place("3001", colour=16)])
    model = Model(name="main.ldr")
    model.add_submodel(child, colour=4)
    assert compare_inventory(model, [BomRow("3001", None, 4, None, 1)]).matched


@pytest.mark.parametrize("reference", ["missing.ldr", "Missing.MPD"])
def test_inventory_rejects_unresolved_submodels(reference: str, parts: Parts) -> None:
    with pytest.raises(ValueError, match="unresolved submodel") as raised:
        compare_inventory(Model(objects=[Piece.place(reference)]), [], parts=parts)
    assert reference in str(raised.value)


def test_native_colour_name_is_trimmed_before_mapping(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "part,colour_code,colour_name,quantity\n3001,, Red ,1\n", encoding="utf-8"
    )
    assert read_inventory(inventory, colour_map={"Red": 4}) == [
        BomRow("3001", None, 4, None, 1)
    ]


@pytest.mark.parametrize(
    "case",
    [
        ("3001", True, 0),
        ("3001", False, 2),
        ("Missing Sub", True, 2),
        ("Missing Sub", False, 2),
    ],
)
def test_comparison_cli_classifies_bare_references(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    parts: Parts,
    case: tuple[str, bool, int],
) -> None:
    reference, catalog_available, status = case
    model = tmp_path / "model.ldr"
    model.write_text(f"1 4 0 0 0 1 0 0 0 1 0 0 0 1 {reference}\n", encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n", encoding="utf-8")
    with patch(
        "ldraw.cli._bom._parts_lst_path",
        return_value=parts.path if catalog_available else tmp_path / "missing.lst",
    ) as listing_path:
        assert main(["bom", str(model), "--compare", str(inventory)]) == status
    listing_path.assert_called_once_with()
    output = capsys.readouterr()
    if status == 2:
        if catalog_available:
            assert reference in output.err
            assert "supply a parts catalog or use .dat" in output.err
        else:
            assert str(tmp_path / "missing.lst") in output.err
            assert "parts.lst not found" in output.err
            assert "ldraw download" in output.err
        assert not output.out
    else:
        assert "Inventory matches" in output.out


@pytest.mark.parametrize("suffix", [".dat", ".DAT"])
def test_comparison_cli_dat_references_do_not_load_config(
    tmp_path: Path, suffix: str
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(f"1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001{suffix}\n", encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n", encoding="utf-8")
    with patch.object(Config, "load", side_effect=AssertionError("unexpected config")):
        assert main(["bom", str(model), "--compare", str(inventory)]) == 0


def test_comparison_cli_config_errors_are_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model, inventory = _comparison_files(
        tmp_path, reference="3001", inventory_code="3001"
    )
    config_file = tmp_path / "broken.yml"
    config_file.write_text("[broken", encoding="utf-8")
    with patch("ldraw.config.CONFIG_FILE", config_file):
        assert main(["bom", str(model), "--compare", str(inventory)]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "inventory comparison failed" in output.err
    assert str(config_file) in output.err


def test_comparison_cli_traverses_once_without_catalog_work(
    tmp_path: Path, parts: Parts
) -> None:
    model, inventory = _comparison_files(
        tmp_path, reference="3001", inventory_code="3001"
    )
    with (
        patch("ldraw.cli._bom._parts_lst_path", return_value=parts.path),
        patch.object(
            Parts, "_scan_library_directories", side_effect=AssertionError("scan")
        ),
        patch("ldraw.part.parse_ldraw_line", side_effect=AssertionError("geometry")),
        patch.object(
            Model,
            "iter_occurrences",
            autospec=True,
            side_effect=Model.iter_occurrences,
        ) as traversal,
        patch.object(
            Parts, "_categorize_parts", side_effect=AssertionError("categorization")
        ),
        patch(
            "ldraw.catalog.catalog_fingerprint",
            side_effect=AssertionError("fingerprint"),
        ),
        patch("sqlite3.connect", side_effect=AssertionError("SQLite")),
    ):
        assert main(["bom", str(model), "--compare", str(inventory)]) == 0
    assert traversal.call_count == 1
    assert traversal.call_args.kwargs == {"include_steps": False}


@pytest.mark.parametrize("suffix", ["", ".dat", ".DAT"])
def test_dotted_model_matches_its_own_exported_bom(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], suffix: str
) -> None:
    listing = tmp_path / "parts.lst"
    listing.write_text("custom.v1.dat  Version One\ncustom.v2.dat  Version Two\n")
    parts = Parts(parts_lst=listing)
    model_path = tmp_path / "model.mpd"
    identity = "1 0 0 0 1 0 0 0 1"
    model_path.write_text(
        f"0 FILE main.ldr\n1 4 0 0 0 {identity} body.ldr\n"
        f"0 FILE body.ldr\n1 16 0 0 0 {identity} custom.v1{suffix}\n"
        f"1 16 20 0 0 {identity} CUSTOM.V1{suffix}\n"
        f"1 16 40 0 0 {identity} custom.v2{suffix}\n"
    )
    model = read_model(model_path)
    rows = model.bill_of_materials(parts=parts)
    assert [(row.part, row.quantity, row.description) for row in rows] == [
        ("custom.v1", 2, "Version One"),
        ("custom.v2", 1, "Version Two"),
    ]
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(rows_to_csv(rows))
    assert compare_inventory(
        model=model, expected=read_inventory(inventory), parts=parts
    ).matched
    with patch("ldraw.cli._bom._parts_lst_path", return_value=listing):
        assert main(["bom", str(model_path), "--compare", str(inventory)]) == 0
        capsys.readouterr()
        exported = tmp_path / "exported.csv"
        with patch("ldraw.cli._bom._try_load_parts", return_value=parts):
            assert (
                main(["bom", str(model_path), "--format", "csv", "-o", str(exported)])
                == 0
            )
        assert main(["bom", str(model_path), "--compare", str(exported)]) == 0
    assert "Inventory matches" in capsys.readouterr().out
    aliases = {"custom.v1": "external-1", "custom.v2": "external-2"}
    assert compare_inventory(
        model=model, expected=rows, parts=parts, part_aliases=aliases
    ).matched


@pytest.mark.parametrize("failure", ["missing", "unreadable", "undecodable"])
def test_comparison_cli_preserves_model_read_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    model = tmp_path / "model.ldr"
    if failure == "undecodable":
        model.write_bytes(b"\xff")
    reader = (
        patch(
            "ldraw.model.Path.read_bytes",
            side_effect=PermissionError("permission denied"),
        )
        if failure == "unreadable"
        else nullcontext()
    )
    with reader:
        assert (
            main(["bom", str(model), "--compare", str(tmp_path / "inventory.csv")]) == 2
        )
    error = capsys.readouterr().err
    assert str(model) in error
    expected_code = "io.decode_failed" if failure == "undecodable" else "io.read_failed"
    assert expected_code in error
    assert "incomplete" not in error


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
