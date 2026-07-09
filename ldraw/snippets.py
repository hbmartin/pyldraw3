"""Small source-code snippets derived from catalog entries."""

from __future__ import annotations

from ldraw.parts import CatalogEntry
from ldraw.parts import symbol_name_for_description as _symbol_name_for_description


def symbol_name_for_description(description: str) -> str:
    """Return the generated Python symbol for an LDraw description."""
    return _symbol_name_for_description(description)


def symbol_name(entry: CatalogEntry) -> str:
    """Return the generated Python symbol name for a catalog entry."""
    return entry.symbol_name


def module_path(entry: CatalogEntry) -> str | None:
    """Return the generated module path containing ``entry``, if any."""
    return entry.module_path


def suggested_import(entry: CatalogEntry) -> str | None:
    """Return an import statement for ``entry`` in the generated library."""
    return entry.import_statement()
