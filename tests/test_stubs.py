"""Tests for the ldraw-stubs package emission."""

from pathlib import Path

import pytest

from ldraw import generate
from ldraw.config import Config
from ldraw.errors import LibraryNotGeneratedError
from ldraw.stubs import write_stub_package


@pytest.fixture
def generated_library(tmp_path: Path) -> str:
    generated_path = tmp_path / "generated"
    generated_path.mkdir()
    config = Config(
        ldraw_library_path=str(Path(__file__).resolve().parent / "test_ldraw"),
        generated_path=str(generated_path),
    )
    generate(config)
    return str(generated_path)


def test_write_stub_package_mirrors_library(
    generated_library: str,
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "project"
    out_dir.mkdir()

    stubs_dir = write_stub_package(generated_library, out_dir)

    assert stubs_dir == out_dir / "ldraw-stubs"
    relative = {
        str(path.relative_to(stubs_dir))
        for path in stubs_dir.rglob("*")
        if path.is_file()
    }
    assert relative == {
        "py.typed",
        str(Path("library") / "__init__.pyi"),
        str(Path("library") / "colours.pyi"),
        str(Path("library") / "parts" / "__init__.pyi"),
        str(Path("library") / "parts" / "bricks.pyi"),
    }
    assert (stubs_dir / "py.typed").read_text() == "partial\n"

    bricks_pyi = stubs_dir / "library" / "parts" / "bricks.pyi"
    bricks_py = Path(generated_library) / "library" / "parts" / "bricks.py"
    assert bricks_pyi.read_text() == bricks_py.read_text()
    assert "Brick2X4 = '3001'" in bricks_pyi.read_text()


def test_write_stub_package_requires_generated_library(tmp_path: Path) -> None:
    with pytest.raises(LibraryNotGeneratedError, match="run `ldraw generate` first"):
        write_stub_package(tmp_path, tmp_path)


def test_write_stub_package_removes_stale_stubs(
    generated_library: str,
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "project"
    stale = out_dir / "ldraw-stubs" / "library" / "parts" / "stale.pyi"
    stale.parent.mkdir(parents=True)
    stale.write_text("Ghost = '0000'\n")

    stubs_dir = write_stub_package(generated_library, out_dir)

    assert not stale.exists()
    assert (stubs_dir / "library" / "parts" / "bricks.pyi").is_file()
