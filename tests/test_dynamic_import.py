"""Tests for dynamic import functionality."""

import importlib
from pathlib import Path

import pytest

from ldraw import LibraryImporter
from ldraw.config import Config


@pytest.fixture
def generated_library(tmp_path: Path):
    generated_path = tmp_path / "generated"
    library_path = generated_path / "library"
    library_path.mkdir(parents=True)
    (library_path / "__init__.py").write_text("__all__ = ['single', 'package']")

    config = Config(
        ldraw_library_path=str(tmp_path / "ldraw"),
        generated_path=str(generated_path),
    )
    LibraryImporter.set_config(config)
    yield library_path
    LibraryImporter.clean()


def test_dynamic_import_single_py_module(generated_library: Path) -> None:
    (generated_library / "single.py").write_text("VALUE = 42")

    module = importlib.import_module("ldraw.library.single")

    assert module.VALUE == 42


def test_dynamic_import_package_init_module(generated_library: Path) -> None:
    package = generated_library / "package"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 'package'")

    module = importlib.import_module("ldraw.library.package")

    assert module.VALUE == "package"
