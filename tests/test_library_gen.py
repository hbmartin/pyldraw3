"""Tests for library generation functionality."""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Never

import pytest

from ldraw import LibraryImporter, generate
from ldraw.colour import Colour
from ldraw.config import Config
from ldraw.generation.exceptions import DuplicateSymbolError

logger = logging.getLogger(__name__)


TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture
def test_ldraw_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[str, None, None]:
    config = Config(
        ldraw_library_path=str(TESTS_DIR / "test_ldraw"),
        generated_path=str(tmp_path),
    )
    generate(config)
    # Equivalent to LibraryImporter.set_config(config), but monkeypatch
    # restores the previous default config on teardown.
    monkeypatch.setattr(LibraryImporter, "_default_config", config)
    LibraryImporter.clean()
    yield str(tmp_path)
    LibraryImporter.clean()


def test_library_gen_files(test_ldraw_library: str) -> None:
    """Generated library contains the right files."""
    generated_root = Path(test_ldraw_library)
    content = {
        path.relative_to(generated_root)
        for path in generated_root.rglob("*")
        if path.is_file()
    }

    library = {
        Path("__init__.py"),
        Path("py.typed"),
        Path("colours.py"),
        Path("license.txt"),
        Path("__hash__"),
        Path("parts") / "__init__.py",
        Path("parts") / "bricks.py",
    }

    expected = {Path("library") / item for item in library} | {Path("catalog.sqlite")}
    assert content == expected


def test_library_gen_import(test_ldraw_library: str) -> None:
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


def test_stale_generation_self_heals(
    test_ldraw_library: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A __hash__ from an older pyldraw (bare parts.lst md5) regenerates."""
    from ldraw.generation import GENERATION_SCHEMA_VERSION

    config = Config(
        ldraw_library_path=str(TESTS_DIR / "test_ldraw"),
        generated_path=test_ldraw_library,
    )
    hash_path = Path(test_ldraw_library) / "library" / "__hash__"
    fingerprint = hash_path.read_text()
    assert fingerprint.startswith(f"{GENERATION_SCHEMA_VERSION}\n")

    # Up-to-date generation is skipped.
    with caplog.at_level(logging.INFO, logger="ldraw"):
        generate(config)
    assert "already generated" in caplog.text

    # The old format stored only the parts.lst md5; it must read as stale.
    caplog.clear()
    hash_path.write_text(fingerprint.splitlines()[1])
    with caplog.at_level(logging.INFO, logger="ldraw"):
        generate(config)
    assert "already generated" not in caplog.text
    assert hash_path.read_text() == fingerprint


def test_colliding_symbols_are_deduped_with_part_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ldraw.generation.parts import section_content

    section = {
        'Tile 1 x 1 with Silver "." Pattern': "3070bpuf",
        'Tile 1 x 1 with Silver "-" Pattern': "3070bpuh",
        "Brick 2 x 4": "3001",
    }
    with caplog.at_level(logging.WARNING, logger="ldraw"):
        content = section_content(section, "tiles")

    assert "sanitize to the same symbol" in caplog.text
    assert "Tile1X1WithSilver_Pattern_3070bpuf = '3070bpuf'" in content
    assert "Tile1X1WithSilver_Pattern_3070bpuh = '3070bpuh'" in content
    assert "Brick2X4 = '3001'" in content
    assert "Tile1X1WithSilver_Pattern = " not in content


def test_unresolvable_symbol_collision_raises() -> None:
    from ldraw.generation.parts import section_content

    # The same code listed under two descriptions that sanitize identically
    # cannot be deduplicated by suffixing.
    section = {'Plate 1 x 1 "."': "3024", 'Plate 1 x 1 "-"': "3024"}
    with pytest.raises(DuplicateSymbolError, match="plates"):
        section_content(section, "plates")


def test_duplicate_descriptions_are_reported_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
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


def test_generate_wraps_unwritable_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ldraw.generation import generate as do_generate
    from ldraw.generation.exceptions import UnwritableOutputError

    def denied(_path: str | Path) -> Never:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("ldraw.generation.ensure_exists", denied)
    config = Config(
        ldraw_library_path=str(TESTS_DIR / "test_ldraw"),
        generated_path=str(tmp_path),
    )

    with pytest.raises(UnwritableOutputError, match="Cannot write"):
        do_generate(config)


def test_verify_generated_modules_raises_on_syntax_error(tmp_path: Path) -> None:
    from ldraw.generation import _verify_generated_modules
    from ldraw.generation.exceptions import GeneratedModuleSyntaxError

    (tmp_path / "broken.py").write_text("x = (\n")

    with pytest.raises(GeneratedModuleSyntaxError, match=r"broken\.py"):
        _verify_generated_modules(tmp_path)

    (tmp_path / "broken.py").write_text("x = 1\n")
    _verify_generated_modules(tmp_path)


def test_dat_header_edit_marks_generation_stale(tmp_path: Path) -> None:
    import shutil

    from ldraw.generation import library_fingerprint

    library = tmp_path / "ldraw"
    shutil.copytree(TESTS_DIR / "test_ldraw" / "ldraw", library)
    parts_lst = library / "parts.lst"
    before = library_fingerprint(parts_lst)

    target = library / "parts" / "3001.dat"
    target.write_text(target.read_text() + "0 !KEYWORDS edited\n")

    assert library_fingerprint(parts_lst) != before


def test_digit_leading_description_is_prefixed() -> None:
    from ldraw.generation.parts import section_content

    content = section_content({"2 x 2 Brick": "9999"}, "bricks")

    assert "P2X2Brick = '9999'" in content
    compile(content, "<generated>", "exec")


def test_empty_description_is_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ldraw.generation.parts import section_content

    with caplog.at_level(logging.WARNING, logger="ldraw"):
        content = section_content({"": "123", "Brick 2 x 4": "3001"}, "bricks")

    assert "empty description" in caplog.text
    assert "'123'" not in content
    assert "Brick2X4 = '3001'" in content
    compile(content, "<generated>", "exec")


def test_backslash_code_renders_verbatim() -> None:
    from ldraw.generation.parts import section_content

    content = section_content({"Sub Part": "s\\3001s01"}, "bricks")

    namespace: dict[str, object] = {}
    exec(compile(content, "<generated>", "exec"), namespace)
    assert namespace["SubPart"] == "s\\3001s01"


def test_colour_name_argument_is_full_name(tmp_path: Path) -> None:
    from ldraw.generation.colours import colours_module_content
    from ldraw.parts import Parts

    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Two-tone CODE 5 VALUE #AABBCC EDGE #000000\n",
    )

    content = colours_module_content(Parts(ldraw_dir / "parts.lst"))

    assert "Two_Tone = Colour(5, 'Two-tone', '#AABBCC'" in content
    assert "'Two-tone': Two_Tone" in content
    namespace: dict[str, object] = {}
    exec(compile(content, "<generated>", "exec"), namespace)
    assert namespace["ColoursByName"]["Two-tone"].name == "Two-tone"


def test_colliding_colour_symbols_are_suffixed_with_codes(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ldraw.generation.colours import colours_module_content
    from ldraw.parts import Parts

    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Two-tone CODE 5 VALUE #AABBCC EDGE #000000\n"
        "0 !COLOUR Two@tone CODE 6 VALUE #CCDDEE EDGE #000000\n",
    )

    with caplog.at_level(logging.WARNING, logger="ldraw"):
        content = colours_module_content(Parts(ldraw_dir / "parts.lst"))

    assert "Two_Tone_5 = Colour(5, 'Two-tone'" in content
    assert "Two_Tone_6 = Colour(6, 'Two@tone'" in content
    assert "sanitize to the same symbol" in caplog.text
    namespace: dict[str, object] = {}
    exec(compile(content, "<generated>", "exec"), namespace)
    colours_by_code = namespace["ColoursByCode"]
    colours_by_name = namespace["ColoursByName"]
    assert isinstance(colours_by_code, dict)
    assert isinstance(colours_by_name, dict)
    assert colours_by_code[5].name == "Two-tone"
    assert colours_by_code[6].name == "Two@tone"
    assert colours_by_name["Two-tone"].code == 5
    assert colours_by_name["Two@tone"].code == 6


def test_unresolvable_colour_symbol_collision_raises(tmp_path: Path) -> None:
    from ldraw.generation.colours import colours_module_content
    from ldraw.parts import Parts

    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Two-tone CODE 5 VALUE #AABBCC EDGE #000000\n"
        "0 !COLOUR Two@tone CODE 6 VALUE #CCDDEE EDGE #000000\n"
        "0 !COLOUR Two_Tone_5 CODE 7 VALUE #EEFFAA EDGE #000000\n",
    )

    with pytest.raises(DuplicateSymbolError, match="Two_Tone_5"):
        colours_module_content(Parts(ldraw_dir / "parts.lst"))


def test_colour_with_no_valid_symbol_is_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from ldraw.generation.colours import colours_module_content
    from ldraw.parts import Parts

    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    parts = Parts(ldraw_dir / "parts.lst")
    parts.colours_by_name = {
        "": Colour(code=5, name="", rgb="#AABBCC"),
    }

    with caplog.at_level(logging.WARNING, logger="ldraw"):
        content = colours_module_content(parts)

    assert "= Colour(5" not in content
    assert "name yields no valid identifier" in caplog.text
