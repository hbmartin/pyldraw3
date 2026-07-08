"""Tests for library generation functionality."""

import logging
import os
import tempfile
from datetime import UTC, datetime
from os.path import join
from pathlib import Path

import pytest

from ldraw import LibraryImporter, generate
from ldraw.colour import Colour
from ldraw.config import Config

logger = logging.getLogger(__name__)


@pytest.fixture
def test_ldraw_library():
    generated_path = tempfile.mkdtemp(prefix=datetime.now(UTC).isoformat())
    logger.debug(f"generated_path={generated_path}")
    config = Config(
        ldraw_library_path=os.path.join("tests", "test_ldraw"),
        generated_path=generated_path,
    )
    generate(config)
    LibraryImporter.set_config(config)
    return config.generated_path


def test_library_gen_files(test_ldraw_library) -> None:
    """Generated library contains the right files."""
    content = {
        os.path.relpath(os.path.join(dp, f), test_ldraw_library)
        for dp, dn, fn in os.walk(test_ldraw_library)
        for f in fn
    }

    library = {
        "__init__.py",
        "py.typed",
        "colours.py",
        "license.txt",
        "__hash__",
        join("parts", "__init__.py"),
        join("parts", "bricks.py"),
    }

    expected = {join("library", el) for el in library} | {"catalog.sqlite"}
    assert content == expected


def test_library_gen_import(test_ldraw_library) -> None:
    """Generated library is importable."""
    from ldraw import library

    assert set(library.__all__) == {"parts", "colours"}

    # Import parts module explicitly (can't access as attribute with dynamic imports)
    from ldraw.library import parts

    assert parts.__all__ == ["bricks"]
    assert {t for t in dir(parts) if not t.startswith("__")} == {
        "bricks",
        "Brick2X4",
    }

    from ldraw.library.parts import Brick2X4

    assert Brick2X4 == "3001"

    from ldraw.library.parts.bricks import Brick2X4

    assert Brick2X4 == "3001"

    from ldraw.library.colours import ColoursByCode, ColoursByName, Reddish_Gold

    expected_color = Colour(189, "Reddish_Gold", "#AC8247", 255, ["PEARLESCENT"])

    assert ColoursByCode[expected_color.code] == expected_color
    assert ColoursByName[expected_color.name] == expected_color
    assert set(ColoursByCode) == {0, 1, 4, 14, 15, 16, 24, 189}

    assert Reddish_Gold == expected_color


def test_stale_generation_self_heals(test_ldraw_library, caplog) -> None:
    """A __hash__ from an older pyldraw (bare parts.lst md5) regenerates."""
    from ldraw.generation import GENERATION_SCHEMA_VERSION

    config = Config(
        ldraw_library_path=os.path.join("tests", "test_ldraw"),
        generated_path=test_ldraw_library,
    )
    hash_path = Path(test_ldraw_library) / "library" / "__hash__"
    fingerprint = hash_path.read_text()
    assert fingerprint.startswith(f"{GENERATION_SCHEMA_VERSION}\n")

    # Up-to-date generation is skipped.
    with caplog.at_level(logging.ERROR, logger="ldraw"):
        generate(config)
    assert "already generated" in caplog.text

    # The old format stored only the parts.lst md5; it must read as stale.
    caplog.clear()
    hash_path.write_text(fingerprint.splitlines()[1])
    with caplog.at_level(logging.ERROR, logger="ldraw"):
        generate(config)
    assert "already generated" not in caplog.text
    assert hash_path.read_text() == fingerprint


def test_colliding_symbols_are_deduped_with_part_codes(caplog) -> None:
    from ldraw.generation.parts import section_content

    section = {
        'Tile 1 x 1 with Silver "." Pattern': "3070bpuf",
        'Tile 1 x 1 with Silver "-" Pattern': "3070bpuh",
        "Brick 2 x 4": "3001",
    }
    with caplog.at_level(logging.WARNING, logger="ldraw"):
        content = section_content(section, "tiles")

    assert "sanitize to the same symbol" in caplog.text
    assert 'Tile1X1WithSilver_Pattern_3070bpuf = "3070bpuf"' in content
    assert 'Tile1X1WithSilver_Pattern_3070bpuh = "3070bpuh"' in content
    assert 'Brick2X4 = "3001"' in content
    assert 'Tile1X1WithSilver_Pattern = "' not in content


def test_unresolvable_symbol_collision_raises() -> None:
    from ldraw.generation.exceptions import DuplicateSymbolError
    from ldraw.generation.parts import section_content

    # The same code listed under two descriptions that sanitize identically
    # cannot be deduplicated by suffixing.
    section = {'Plate 1 x 1 "."': "3024", 'Plate 1 x 1 "-"': "3024"}
    with pytest.raises(DuplicateSymbolError, match="plates"):
        section_content(section, "plates")


def test_duplicate_descriptions_are_reported_once(tmp_path, caplog) -> None:
    from ldraw.parts import Parts

    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    for code in ("18860", "30068"):
        (parts_dir / f"{code}.dat").write_text("0 =Brick  1 x  1 Round\n")
    (ldraw_dir / "parts.lst").write_text(
        "18860.dat  =Brick  1 x  1 Round\n30068.dat  =Brick  1 x  1 Round\n",
    )

    with caplog.at_level(logging.INFO, logger="ldraw"):
        parts = Parts(ldraw_dir / "parts.lst")

    assert "1 parts" in caplog.text
    assert "share a description" in caplog.text
    # Last listed code wins.
    assert parts.by_name["=Brick  1 x  1 Round"] == "30068"
