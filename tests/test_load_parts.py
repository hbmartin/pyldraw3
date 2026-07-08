"""Tests for parts loading functionality."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.parts import (
    CatalogEntry,
    MinifigSection,
    PartCategory,
    Parts,
    PartsCatalog,
)


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
# of the inflect-based pluralizer this mapping replaced.
EXPECTED_MODULE_NAMES = {
    PartCategory.ANIMAL: "animals",
    PartCategory.ANTENNA: "antennas",
    PartCategory.ARCH: "arches",
    PartCategory.ARM: "arms",
    PartCategory.BAR: "bars",
    PartCategory.BASEPLATE: "baseplates",
    PartCategory.BELVILLE: "belvilles",
    PartCategory.BOAT: "boats",
    PartCategory.BRICK: "bricks",
    PartCategory.CANVAS: "canvases",
    PartCategory.CAR: "car",
    PartCategory.CONE: "cones",
    PartCategory.CONSTRACTION: "constractions",
    PartCategory.CONTAINER: "containers",
    PartCategory.CRANE: "cranes",
    PartCategory.CYLINDER: "cylinders",
    PartCategory.DISH: "dishes",
    PartCategory.DOOR: "doors",
    PartCategory.ELECTRIC: "electrics",
    PartCategory.FENCE: "fences",
    PartCategory.FIGURE: "figures",
    PartCategory.FIGURE_ACCESSORY: "figure_accessory",
    PartCategory.FREESTYLE: "freestyles",
    PartCategory.HINGE: "hinges",
    PartCategory.HOMEMAKER: "homemakers",
    PartCategory.HOSE: "hoses",
    PartCategory.MAGNET: "magnets",
    PartCategory.MINIFIG: "minifigs",
    PartCategory.MINIFIG_ACCESSORY: "minifig_accessory",
    PartCategory.MINIFIG_FOOTWEAR: "minifig_footwear",
    PartCategory.MINIFIG_HEADWEAR: "minifig_headwear",
    PartCategory.MINIFIG_HIPWEAR: "minifig_hipwear",
    PartCategory.MINIFIG_NECKWEAR: "minifig_neckwear",
    PartCategory.PLANE: "planes",
    PartCategory.PLANT: "plants",
    PartCategory.PLATE: "plates",
    PartCategory.PROPELLOR: "propellors",
    PartCategory.ROADSIGN: "roadsigns",
    PartCategory.SCREW: "screws",
    PartCategory.SHEET_CARDBOARD: "sheet_cardboard",
    PartCategory.SHEET_FABRIC: "sheet_fabric",
    PartCategory.SHEET_PLASTIC: "sheet_plastic",
    PartCategory.SLOPE: "slopes",
    PartCategory.SPHERE: "spheres",
    PartCategory.STAIRCASE: "staircases",
    PartCategory.STICKER: "stickers",
    PartCategory.SUPPORT: "supports",
    PartCategory.TAP: "taps",
    PartCategory.TECHNIC: "technic",
    PartCategory.TILE: "tiles",
    PartCategory.TRAIN: "train",
    PartCategory.TURNTABLE: "turntables",
    PartCategory.TYRE: "tyres",
    PartCategory.VEHICLE: "vehicles",
    PartCategory.WHEEL: "wheels",
    PartCategory.WINCH: "winches",
    PartCategory.WINDOW: "windows",
    PartCategory.WINDSCREEN: "windscreens",
    PartCategory.WING: "wings",
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
            description="Hair Male",
            category=PartCategory.OTHER,
            minifig_section=MinifigSection.HATS,
        ),
    )

    sections = catalog.module_sections()

    assert sections[("bricks",)] == {"Brick  2 x  4": "3001"}
    assert sections[("minifig_accessory",)] == {"Shield Triangular": "3846"}
    assert sections[("minifig", "hats")] == {"Hair Male": "3901"}
    assert ("other",) not in sections


def test_unknown_category_warns_and_falls_back_to_other(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "9999.dat").write_text("0 Weird Part\n0 !CATEGORY Duplo\n")
    (ldraw_dir / "parts.lst").write_text("9999.dat  Weird Part\n")

    with caplog.at_level(logging.WARNING, logger="ldraw.parts"):
        parts = Parts(ldraw_dir / "parts.lst")

    entry = parts.get_entry_by_code("9999")
    assert entry is not None
    assert entry.category == PartCategory.OTHER
    assert "unknown LDraw category 'Duplo'" in caplog.text


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
