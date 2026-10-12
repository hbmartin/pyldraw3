"""Discover public APIs without a downloaded or generated library."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any

UNIT_DOCS = {
    "STUD_PITCH": "Distance between adjacent stud centres: 20 LDraw units (LDU).",
    "PLATE_HEIGHT": "Standard plate body height: 8 LDraw units (LDU).",
    "BRICK_HEIGHT": "Standard brick body height: 24 LDraw units (LDU).",
    "LDU_TO_MM": "Millimetres per LDraw unit: 0.4 mm/LDU.",
}

SUPPLEMENTAL_API: tuple[tuple[str, str], ...] = (
    ("ldraw.bom", "comparison_to_csv"),
    ("ldraw.units", "STUD_PITCH"),
    ("ldraw.units", "PLATE_HEIGHT"),
    ("ldraw.units", "BRICK_HEIGHT"),
    ("ldraw.units", "LDU_TO_MM"),
    ("ldraw.bom", "rows_to_csv"),
    ("ldraw.bom", "rows_to_json"),
    ("ldraw.config", "Config"),
    ("ldraw.errors", "NoGeometryError"),
    ("ldraw.errors", "PartNotFoundError"),
    ("ldraw.errors", "UnknownSubmodelError"),
    ("ldraw.part_geometry", "part_bounding_box"),
    ("ldraw.part_geometry", "part_studs"),
    ("ldraw.parts", "symbol_description"),
    ("ldraw.snippets", "module_path"),
    ("ldraw.snippets", "suggested_import"),
    ("ldraw.snippets", "symbol_name"),
    ("ldraw.snippets", "symbol_name_for_description"),
)


@dataclass(frozen=True, slots=True)
class ApiEntry:
    """One discoverable public symbol, method, property, or constant."""

    qualified_name: str
    signature: str | None
    docstring: str
    kind: str
    value: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Return JSON-ready fields."""
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ApiInventory:
    """A presentation page and the number of all matching symbols."""

    items: tuple[ApiEntry, ...]
    total: int
    limit: int | None
    offset: int


def public_symbols() -> tuple[tuple[str, str], ...]:
    """Return the shared runtime, reference, and cheat-sheet registry."""
    package = importlib.import_module("ldraw")
    return (*(("ldraw", name) for name in package.__all__), *SUPPLEMENTAL_API)


def _api_entry(name: str, value: Any, kind: str) -> ApiEntry:  # noqa: ANN401
    try:
        signature = str(inspect.signature(value)) if callable(value) else None
    except (ValueError, TypeError):
        signature = None
    return ApiEntry(
        qualified_name=name,
        signature=signature,
        docstring=UNIT_DOCS.get(
            name.removeprefix("ldraw.units."), inspect.getdoc(value) or ""
        ),
        kind=kind,
        value=repr(value) if kind == "constant" else None,
    )


def _inventory_entries() -> dict[str, ApiEntry]:
    """Enumerate shared symbols and their public callable or property members."""
    entries: dict[str, ApiEntry] = {}
    for module_name, name in public_symbols():
        value = getattr(importlib.import_module(module_name), name)
        qualified = f"{module_name}.{name}"
        kind = (
            "class"
            if inspect.isclass(value)
            else "function"
            if callable(value)
            else "constant"
        )
        entries[qualified] = _api_entry(qualified, value, kind)
        if inspect.isclass(value):
            for member_name, member in inspect.getmembers(value):
                if not member_name.startswith("_") and (
                    callable(member) or isinstance(member, property)
                ):
                    member_qualified = f"{qualified}.{member_name}"
                    entries[member_qualified] = _api_entry(
                        member_qualified,
                        member,
                        "method" if callable(member) else "property",
                    )
    return entries


def api_inventory(
    query: str = "", *, limit: int | None = None, offset: int = 0
) -> ApiInventory:
    """Search public names and documentation; pagination never changes totals."""
    if offset < 0 or (limit is not None and limit < 0):
        message = "limit and offset must be non-negative"
        raise ValueError(message)
    tokens = query.casefold().split()
    matches = tuple(
        entry
        for _, entry in sorted(_inventory_entries().items())
        if all(
            token in f"{entry.qualified_name} {entry.docstring}".casefold()
            for token in tokens
        )
    )
    text = query.casefold().strip()
    matches = tuple(
        sorted(
            matches,
            key=lambda entry: (
                not entry.qualified_name.casefold().endswith(f".{text}"),
                text not in entry.qualified_name.casefold(),
                entry.qualified_name,
            ),
        )
    )
    end = None if limit is None else offset + limit
    return ApiInventory(
        items=matches[offset:end], total=len(matches), limit=limit, offset=offset
    )
