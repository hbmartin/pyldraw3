"""Part identities remain consistent from parsing through exported counts."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw._parts_listing import PartsListing
from ldraw.analysis import analyze_model
from ldraw.bom import bill_of_materials, compare_inventory, rows_to_csv, rows_to_json
from ldraw.cli import main
from ldraw.geometry import Identity, Vector
from ldraw.model import Model, parse_model_result
from ldraw.parts import Parts
from ldraw.pieces import Piece
from ldraw.utils import split_ldraw_reference

IDENTITY = "1 0 0 0 1 0 0 0 1"


@pytest.mark.parametrize("code", ["custom.v1", "custom.dat.v1", "CUSTOM.DAT.V1"])
@pytest.mark.parametrize("suffix", ["", ".dat", ".DAT"])
def test_dotted_identity_agrees_across_all_consumers(
    tmp_path: Path, code: str, suffix: str
) -> None:
    root = tmp_path / "library"
    (root / "parts").mkdir(parents=True)
    (root / "parts" / f"{code.lower()}.dat").write_text("0 Brick Custom\n")
    listing = root / "parts.lst"
    listing.write_text(f"{code.lower()}.dat  Brick Custom\n")
    parts = Parts(parts_lst=listing)
    text = f"1 4 0 0 0 {IDENTITY} {code}{suffix}\n"
    loaded = parse_model_result(text, name="main.ldr", parts=parts)
    assert loaded.valid
    assert loaded.model is not None
    piece = loaded.model.pieces[0]
    assert piece.part == code
    assert piece.reference == f"{code}{suffix}"
    assert loaded.model.to_ldraw() == text.rstrip()
    assert Piece.place(f"{code}{suffix}").part == code
    occurrence = next(loaded.model.iter_occurrences())
    assert occurrence.part_code == code
    analysis = analyze_model(loaded.model)
    assert analysis.summary.part_counts == {code: 1}
    assert analysis.bom[0].part == code
    assert compare_inventory(loaded.model, analysis.bom, parts=parts).matched
    path = tmp_path / "model.ldr"
    path.write_text(text)
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(rows_to_csv(analysis.bom))
    with patch("ldraw.cli._bom._parts_lst_path", return_value=listing):
        assert main(["bom", str(path), "--compare", str(inventory)]) == 0


def test_custom_constructor_suffix_preserves_reference_and_identity() -> None:
    piece = Piece(
        colour=4,
        position=Vector(0, 0, 0),
        matrix=Identity(),
        part="custom",
        suffix=".v1",
    )
    assert piece.reference == "custom.v1"
    assert piece.part == "custom.v1"
    assert piece.suffix == ""
    assert split_ldraw_reference("custom.dat.v1") == ("custom.dat.v1", "")
    assert split_ldraw_reference("custom.v1.DAT") == ("custom.v1", ".DAT")
    assert split_ldraw_reference("body.v1.LDR") == ("body.v1", ".LDR")
    assert split_ldraw_reference("body.v1.MPD") == ("body.v1", ".MPD")


def test_caller_occurrence_identity_override_remains_authoritative() -> None:
    model = Model(objects=[Piece.place("3001", colour=4)])
    occurrence = next(model.iter_occurrences())
    relabeled = replace(occurrence, part_code="External.v2")
    rows = bill_of_materials(occurrences=[relabeled, relabeled])
    assert [(row.part, row.quantity) for row in rows] == [("External.v2", 2)]
    assert rows[0].part in rows_to_csv(rows)
    assert json.loads(rows_to_json(rows))[0]["part"] == "External.v2"


@pytest.mark.parametrize("first", ["s\\3001s01", "S/3001S01"])
def test_bom_preserves_first_spelling_and_reference_separators(first: str) -> None:
    model = parse_model_result(
        f"1 4 0 0 0 {IDENTITY} {first}.dat\n1 4 20 0 0 {IDENTITY} s/3001s01.dat\n"
    ).model
    assert model is not None
    rows = bill_of_materials(model)
    assert [(row.part, row.quantity) for row in rows] == [(first, 2)]
    assert json.loads(rows_to_json(rows))[0]["part"] == first
    assert first in rows_to_csv(rows)
    assert compare_inventory(model, rows).matched


def test_part_and_primitive_listings_share_dotted_filename_parsing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    listing = tmp_path / "parts.lst"
    listing.write_text(
        "custom.dat.v1.DAT  Description with .dat text\nempty.dat\nmalformed\n"
    )
    full = Parts(parts_lst=listing)
    lightweight = PartsListing.read(listing)
    full._load_primitives(listing)  # noqa: SLF001 - shared primitive listing contract
    expected = {"custom.dat.v1": "Description with .dat text", "empty": ""}
    assert full.by_code == lightweight.by_code == full.primitives_by_code == expected
    assert full.description_for("CUSTOM.DAT.V1") == lightweight.description_for(
        "CUSTOM.DAT.V1"
    )
    assert "skipping malformed line 3" in caplog.text


@pytest.mark.parametrize("missing_configuration", [False, True])
def test_unresolved_submodel_error_precedes_listing_or_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, missing_configuration: bool
) -> None:
    model = tmp_path / "mixed.ldr"
    model.write_text(
        f"1 4 0 0 0 {IDENTITY} missing.ldr\n1 4 20 0 0 {IDENTITY} custom.v1\n"
    )
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\ncustom.v1,4,1\n")
    with patch(
        "ldraw.cli._bom._parts_lst_path",
        return_value=tmp_path / "missing.lst",
        side_effect=AssertionError("configuration lookup")
        if missing_configuration
        else None,
    ) as path_lookup:
        assert main(["bom", str(model), "--compare", str(inventory)]) == 2
    path_lookup.assert_not_called()
    error = capsys.readouterr().err
    assert "unresolved submodel reference 'missing.ldr'" in error
    assert "ldraw download" not in error
