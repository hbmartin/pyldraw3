"""Small source-code snippets derived from catalog entries."""

from __future__ import annotations

from ldraw.parts import CatalogEntry, PartCategory, symbol_description
from ldraw.utils import camel, clean


def symbol_name_for_description(description: str) -> str:
    """Return the generated Python symbol for an LDraw description."""
    return clean(camel(symbol_description(description)))


def symbol_name(entry: CatalogEntry) -> str:
    """Return the generated Python symbol name for a catalog entry."""
    return symbol_name_for_description(entry.description)


def module_path(entry: CatalogEntry) -> str | None:
    """Return the generated module path containing ``entry``, if any."""
    if entry.minifig_section is not None:
        return f"ldraw.library.parts.minifig.{entry.minifig_section.value}"
    if entry.category is PartCategory.OTHER:
        return None
    return f"ldraw.library.parts.{entry.category.module_name}"


def suggested_import(entry: CatalogEntry) -> str | None:
    """Return an import statement for ``entry`` in the generated library."""
    if (module := module_path(entry)) is None:
        return None
    return f"from {module} import {symbol_name(entry)}"
