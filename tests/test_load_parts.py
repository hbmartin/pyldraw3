"""Tests for parts loading functionality."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.errors import PartNotFoundError
from ldraw.parts import (
    CatalogEntry,
    MinifigSection,
    PartCategory,
    Parts,
    PartsCatalog,
    symbol_description,
)
from ldraw.snippets import module_path, suggested_import, symbol_name


def test_load_parts() -> None:
    p = Parts("tests/test_ldraw/ldraw/parts.lst")
    assert len(p.by_name) == 1
    assert len(p.by_code) == 1
    assert next(iter(p.by_name.values())) == "3001"
    assert next(iter(p.by_name.keys())) == "Brick  2 x  4"
    assert next(iter(p.by_code.keys())) == "3001"
    assert next(iter(p.by_code.values())) == "Brick  2 x  4"

    part = p.part(code="3001")

    assert str(part.path) == "tests/test_ldraw/ldraw/parts/3001.dat"


def test_typed_catalog_entries() -> None:
    p = Parts("tests/test_ldraw/ldraw/parts.lst")

    entry = p.get_entry_by_code("3001")
    assert entry is not None
    assert entry.description == "Brick  2 x  4"
    assert entry.category == PartCategory.BRICK
    assert p.get_entry_by_description("Brick  2 x  4") == entry
    assert p.entries_by_category(PartCategory.BRICK) == (entry,)
    assert not hasattr(p, "parts")


def test_part_category_module_names() -> None:
    assert PartCategory.BRICK.module_name == "bricks"
    assert PartCategory.TECHNIC.module_name == "technic"
    assert PartCategory.MINIFIG_ACCESSORY.module_name == "minifig_accessory"
    assert PartCategory.SHEET_PLASTIC.module_name == "sheet_plastic"


# Generated module names are a frozen public contract: any change here breaks
# existing `ldraw.library.parts.*` imports. Values match the historical output
# of the inflect-based pluralizer this mapping replaced; categories added
# since (the official-list sync) extend the contract but never rename.
EXPECTED_MODULE_NAMES = {
    PartCategory.ANIMAL: "animals",
    PartCategory.ANTENNA: "antennas",
    PartCategory.ARCH: "arches",
    PartCategory.ARM: "arms",
    PartCategory.BAR: "bars",
    PartCategory.BASEPLATE: "baseplates",
    PartCategory.BELVILLE: "belvilles",
    PartCategory.BOAT: "boats",
    PartCategory.BRACKET: "brackets",
    PartCategory.BRICK: "bricks",
    PartCategory.CANVAS: "canvases",
    PartCategory.CAR: "car",
    PartCategory.CLIKITS: "clikits",
    PartCategory.COCKPIT: "cockpits",
    PartCategory.CONE: "cones",
    PartCategory.CONSTRACTION: "constractions",
    PartCategory.CONSTRACTION_ACCESSORY: "constraction_accessory",
    PartCategory.CONTAINER: "containers",
    PartCategory.CONVEYOR: "conveyors",
    PartCategory.CRANE: "cranes",
    PartCategory.CYLINDER: "cylinders",
    PartCategory.DISH: "dishes",
    PartCategory.DOOR: "doors",
    PartCategory.DUPLO: "duplo",
    PartCategory.ELECTRIC: "electrics",
    PartCategory.EXHAUST: "exhausts",
    PartCategory.FENCE: "fences",
    PartCategory.FIGURE: "figures",
    PartCategory.FIGURE_ACCESSORY: "figure_accessory",
    PartCategory.FLAG: "flags",
    PartCategory.FORKLIFT: "forklifts",
    PartCategory.FREESTYLE: "freestyles",
    PartCategory.GARAGE: "garages",
    PartCategory.GLASS: "glass",
    PartCategory.GRAB: "grabs",
    PartCategory.HINGE: "hinges",
    PartCategory.HOMEMAKER: "homemakers",
    PartCategory.HOSE: "hoses",
    PartCategory.LADDER: "ladders",
    PartCategory.LEVER: "levers",
    PartCategory.MAGNET: "magnets",
    PartCategory.MINIFIG: "minifigs",
    PartCategory.MINIFIG_ACCESSORY: "minifig_accessory",
    PartCategory.MINIFIG_FOOTWEAR: "minifig_footwear",
    PartCategory.MINIFIG_HEADWEAR: "minifig_headwear",
    PartCategory.MINIFIG_HIPWEAR: "minifig_hipwear",
    PartCategory.MINIFIG_NECKWEAR: "minifig_neckwear",
    PartCategory.MONORAIL: "monorail",
    PartCategory.PANEL: "panels",
    PartCategory.PLANE: "planes",
    PartCategory.PLANT: "plants",
    PartCategory.PLATE: "plates",
    PartCategory.PLATFORM: "platforms",
    PartCategory.PROPELLOR: "propellors",
    PartCategory.RACK: "racks",
    PartCategory.ROADSIGN: "roadsigns",
    PartCategory.ROCK: "rocks",
    PartCategory.SCALA: "scala",
    PartCategory.SCREW: "screws",
    PartCategory.SHEET_CARDBOARD: "sheet_cardboard",
    PartCategory.SHEET_FABRIC: "sheet_fabric",
    PartCategory.SHEET_PLASTIC: "sheet_plastic",
    PartCategory.SLOPE: "slopes",
    PartCategory.SPHERE: "spheres",
    PartCategory.STAIRCASE: "staircases",
    PartCategory.STICKER: "stickers",
    PartCategory.STRING: "string",
    PartCategory.SUPPORT: "supports",
    PartCategory.TAIL: "tails",
    PartCategory.TAP: "taps",
    PartCategory.TECHNIC: "technic",
    PartCategory.TILE: "tiles",
    PartCategory.TIPPER: "tippers",
    PartCategory.TRACTOR: "tractors",
    PartCategory.TRAILER: "trailers",
    PartCategory.TRAIN: "train",
    PartCategory.TURNTABLE: "turntables",
    PartCategory.TYRE: "tyres",
    PartCategory.VEHICLE: "vehicles",
    PartCategory.WEDGE: "wedges",
    PartCategory.WHEEL: "wheels",
    PartCategory.WINCH: "winches",
    PartCategory.WINDOW: "windows",
    PartCategory.WINDSCREEN: "windscreens",
    PartCategory.WING: "wings",
    PartCategory.ZNAP: "znap",
    PartCategory.OTHER: "others",
}


def test_module_names_are_frozen_for_every_category() -> None:
    assert {
        category: category.module_name for category in PartCategory
    } == EXPECTED_MODULE_NAMES


def test_module_sections_cover_categories_and_minifig_sections() -> None:
    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(
            code="3001",
            description="Brick  2 x  4",
            category=PartCategory.BRICK,
        ),
    )
    catalog.add(
        CatalogEntry(
            code="3846",
            description="Shield Triangular",
            category=PartCategory.MINIFIG_ACCESSORY,
        ),
    )
    catalog.add(
        CatalogEntry(
            code="3901",
            description="Minifig Hair Male",
            category=PartCategory.OTHER,
            minifig_section=MinifigSection.HATS,
        ),
    )
    catalog.add(
        CatalogEntry(
            code="973",
            description="Minifig Torso",
            category=PartCategory.MINIFIG,
            minifig_section=MinifigSection.TORSOS,
        ),
    )

    sections = catalog.module_sections()

    assert sections[("bricks",)] == {"Brick  2 x  4": "3001"}
    assert sections[("minifig_accessory",)] == {"Shield Triangular": "3846"}
    # Symbol names strip the Minifig prefix in every module they appear in.
    assert sections[("minifig", "hats")] == {"Hair Male": "3901"}
    assert sections[("minifig", "torsos")] == {"Torso": "973"}
    assert sections[("minifigs",)] == {"Torso": "973"}
    assert ("other",) not in sections


def test_catalog_entry_import_snippets() -> None:
    entry = CatalogEntry(
        code="3001",
        description="Brick  2 x  4",
        category=PartCategory.BRICK,
    )

    assert entry.symbol_name == "Brick2X4"
    assert entry.module_path == "ldraw.library.parts.bricks"
    assert entry.import_statement() == (
        "from ldraw.library.parts.bricks import Brick2X4"
    )
    assert symbol_name(entry) == entry.symbol_name
    assert module_path(entry) == entry.module_path
    assert suggested_import(entry) == entry.import_statement()


def test_catalog_entry_import_snippets_for_other_category() -> None:
    entry = CatalogEntry(
        code="9999",
        description="Weird Part",
        category=PartCategory.OTHER,
    )

    assert entry.module_path is None
    assert entry.import_statement() is None


def test_unknown_category_warns_and_falls_back_to_other(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "9999.dat").write_text("0 Weird Part\n0 !CATEGORY Playmobil\n")
    (ldraw_dir / "parts.lst").write_text("9999.dat  Weird Part\n")

    with caplog.at_level(logging.WARNING, logger="ldraw.parts"):
        parts = Parts(ldraw_dir / "parts.lst")

    entry = parts.get_entry_by_code("9999")
    assert entry is not None
    assert entry.category == PartCategory.OTHER
    assert "unknown LDraw category 'Playmobil'" in caplog.text


def test_official_category_labels_resolve() -> None:
    assert PartCategory.from_label("Panel") == PartCategory.PANEL
    assert PartCategory.from_label("Duplo") == PartCategory.DUPLO
    assert PartCategory.from_label("Constraction Accessory") == (
        PartCategory.CONSTRACTION_ACCESSORY
    )


def test_description_category_word_resolves_new_categories(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "2409.dat").write_text("0 Panel 10 x 10 x 12 Corner\n")
    (ldraw_dir / "parts.lst").write_text("2409.dat  Panel 10 x 10 x 12 Corner\n")

    parts = Parts(ldraw_dir / "parts.lst")

    entry = parts.get_entry_by_code("2409")
    assert entry is not None
    assert entry.category == PartCategory.PANEL
    assert ("panels",) in parts.catalog.module_sections()


def test_load_primitives() -> None:
    p = Parts("tests/test_ldraw/ldraw/parts.lst")
    assert len(p.primitives_by_name) == 4
    assert len(p.primitives_by_code) == 4
    assert p.primitives_by_name["Box with 5 Faces and All Edges"] == "box5"
    assert p.primitives_by_code["box5"] == "Box with 5 Faces and All Edges"

    part = p.part(code="box5")

    assert str(part.path) == "tests/test_ldraw/ldraw/p/box5.dat"


@patch.object(Path, "open", side_effect=OSError)
def test_cantreadpartslst(mocked) -> None:
    with pytest.raises(OSError):
        Parts("tests/test_ldraw/ldraw/parts.lst")


def test_parts_get_memoizes_by_stat(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    parts_lst = ldraw_dir / "parts.lst"
    parts_lst.write_text("3001.dat  Brick 2 x 4\n")
    Parts.clear_cache()

    first = Parts.get(parts_lst)
    assert Parts.get(parts_lst) is first

    # A content change (new mtime/size) must invalidate the cached instance.
    (parts_dir / "3002.dat").write_text("0 Brick 2 x 3\n")
    parts_lst.write_text("3001.dat  Brick 2 x 4\n3002.dat  Brick 2 x 3\n")
    assert Parts.get(parts_lst) is not first

    Parts.clear_cache()
    assert Parts.get(parts_lst) is not first


def test_parts_get_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        Parts.get("does/not/exist/parts.lst")


def test_symbol_description_strips_minifig_prefix() -> None:
    assert symbol_description("Minifig Torso") == "Torso"
    assert symbol_description("Minifig (Complete)") == "Complete"
    assert symbol_description("Brick  2 x  4") == "Brick  2 x  4"


def test_minifig_descriptions_are_kept_as_written(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "973.dat").write_text("0 Minifig Torso\n")
    (ldraw_dir / "parts.lst").write_text("973.dat  Minifig Torso\n")

    parts = Parts(ldraw_dir / "parts.lst")

    assert parts.by_code["973"] == "Minifig Torso"
    assert parts.by_name["Minifig Torso"] == "973"
    entry = parts.get_entry_by_code("973")
    assert entry is not None
    assert entry.description == "Minifig Torso"
    assert entry.minifig_section == MinifigSection.TORSOS
    # Generated symbols still strip the prefix.
    assert parts.catalog.module_sections()[("minifig", "torsos")] == {"Torso": "973"}


def test_description_for_tolerates_casing_differences(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "123abc.dat").write_text("0 Test Part\n")
    (ldraw_dir / "parts.lst").write_text("123abc.dat  Test Part\n")

    parts = Parts(ldraw_dir / "parts.lst")

    assert parts.description_for("123abc") == "Test Part"
    assert parts.description_for("123ABC") == "Test Part"  # Piece.part casing
    assert parts.description_for("unknown") is None


def test_part_raises_for_unknown_description_code_or_file() -> None:
    parts = Parts("tests/test_ldraw/ldraw/parts.lst")

    with pytest.raises(PartNotFoundError):
        parts.part(description="No Such Part")
    with pytest.raises(PartNotFoundError):
        parts.part(code="99999")
    with pytest.raises(PartNotFoundError):
        parts.part(code="nosuchdir/3001")
    with pytest.raises(ValueError, match="needs a description or a code"):
        parts.part()


def test_find_part_returns_none_instead_of_raising() -> None:
    parts = Parts("tests/test_ldraw/ldraw/parts.lst")

    assert parts.find_part(description="No Such Part") is None
    assert parts.find_part(code="99999") is None
    found = parts.find_part(code="3001")
    assert found is not None
    assert parts.find_part(description="Brick  2 x  4") is not None


def test_malformed_ldconfig_colour_is_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Bad_Colour   CODE 998   VALUE #NOTHEX\n"
        "0 !COLOUR Good_Colour   CODE 999   VALUE #05131d\n",
    )

    with caplog.at_level(logging.WARNING, logger="ldraw.parts"):
        parts = Parts(ldraw_dir / "parts.lst")

    assert 998 not in parts.colours_by_code
    assert "Bad_Colour" in caplog.text
    # Well-formed values are canonicalized to #RRGGBB uppercase.
    assert parts.colours_by_code[999].rgb == "#05131D"
    assert parts.colours[999] == "#05131D"


def test_glitter_speckle_and_glow_finishes_are_detected(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Glitter_Trans_Dark_Pink  CODE 114  VALUE #DF6695  EDGE #9A2A66"
        "  ALPHA 128  MATERIAL GLITTER VALUE #923978"
        " FRACTION 0.17 VFRACTION 0.2 SIZE 1\n"
        "0 !COLOUR Speckle_Black_Silver  CODE 132  VALUE #000000  EDGE #595959"
        "  MATERIAL SPECKLE VALUE #595959 FRACTION 0.4 MINSIZE 1 MAXSIZE 3\n"
        "0 !COLOUR Glow_In_Dark_Opaque  CODE 21  VALUE #E0FFB0  EDGE #A4C374"
        "  ALPHA 240  LUMINANCE 15\n"
        "0 !COLOUR Red  CODE 4  VALUE #C91A09  EDGE #333333\n",
    )

    parts = Parts(ldraw_dir / "parts.lst")

    glitter = parts.colours_by_code[114]
    assert glitter.colour_attributes == ["GLITTER"]
    # The MATERIAL's second VALUE token must not displace the main rgb.
    assert glitter.rgb == "#DF6695"
    assert not glitter.is_solid

    assert parts.colours_by_code[132].colour_attributes == ["SPECKLE"]
    assert parts.colours_by_code[21].colour_attributes == ["LUMINANCE"]
    assert not parts.colours_by_code[21].is_solid

    red = parts.colours_by_code[4]
    assert red.colour_attributes == []
    assert red.is_solid
