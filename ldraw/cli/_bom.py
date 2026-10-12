"""Runtime services for the bom commands."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, TypedDict, cast

from ldraw.bom import (
    BomRow,
    _compare_inventory_occurrences,
    _inventory_reference_requires_catalog,
    comparison_to_csv,
    read_inventory,
    rows_to_csv,
    rows_to_json,
)
from ldraw.cli._common import _parts_lst_path, _print_diagnostics, _try_load_parts
from ldraw.errors import ConfigLoadError, PartError
from ldraw.model import load_model, read_model
from ldraw.parts import Parts
from ldraw.validation import Severity

if TYPE_CHECKING:
    from pathlib import Path

    from ldraw.model import ModelOccurrence


def _format_bom_table(rows: list[BomRow]) -> str:
    """Format BOM rows as an aligned text table."""
    if not rows:
        return "no pieces"
    lines = [f"{'qty':>5}  {'part':<12} {'colour':<20} description"]
    for row in rows:
        colour = row.colour_name or (
            str(row.colour_code) if row.colour_code is not None else ""
        )
        line = f"{row.quantity:>5}  {row.part:<12} {colour:<20} {row.description or ''}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def _format_bom(rows: list[BomRow], *, output_format: str) -> str:
    """Format BOM rows in the requested output format."""
    match output_format:
        case "csv":
            return rows_to_csv(rows)
        case "json":
            return rows_to_json(rows)
        case _:
            return _format_bom_table(rows)


def bom_command(
    *,
    file: Path,
    output_format: str,
    out: Path | None,
    compare: Path | None = None,
    inventory_mapping: Path | None = None,
) -> int:
    """Print or write a bill of materials for an LDraw model file."""
    if compare is not None or inventory_mapping is not None:
        return _compare_inventory_command(
            file=file,
            inventory=compare,
            mapping=inventory_mapping,
            output_format=output_format,
            out=out,
        )
    if not file.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    parts = _try_load_parts()
    if parts is None:
        print(
            "note: no parts library found; descriptions and colour names omitted",
            file=sys.stderr,
        )
    try:
        model = read_model(file)
        rows = model.bill_of_materials(parts=parts)
    except (PartError, UnicodeDecodeError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1
    text = _format_bom(rows, output_format=output_format)
    if not text.endswith("\n"):
        text = f"{text}\n"
    if out is not None:
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"Could not write {out}: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {len(rows)} rows to {out}")
    else:
        print(text, end="")
    return 0


class _InventoryMapping(TypedDict, total=False):
    columns: dict[str, str]
    part_aliases: dict[str, str]
    colour_map: dict[str, str | int]


def _read_inventory_mapping(path: Path | None) -> _InventoryMapping:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {
        "columns",
        "part_aliases",
        "colour_map",
    }:
        message = (
            "mapping must contain only columns, part_aliases, and colour_map objects"
        )
        raise ValueError(message)
    for name, values in data.items():
        if not isinstance(values, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, (str, int))
            or isinstance(value, bool)
            or (name != "colour_map" and not isinstance(value, str))
            for key, value in values.items()
        ):
            msg = f"invalid {name} mapping"
            raise ValueError(msg)
    return cast("_InventoryMapping", data)


def _inventory_parts(occurrences: tuple[ModelOccurrence, ...]) -> Parts | None:
    """Load only the listing, and only when a leaf needs classification."""
    if not any(
        _inventory_reference_requires_catalog(item.reference) for item in occurrences
    ):
        return None
    parts_lst = _parts_lst_path()
    return Parts(parts_lst) if parts_lst.is_file() else None


def _compare_inventory_command(
    *,
    file: Path,
    inventory: Path | None,
    mapping: Path | None,
    output_format: str,
    out: Path | None,
) -> int:
    try:
        if inventory is None:
            message = "--inventory-mapping requires --compare"
            raise ValueError(message)  # noqa: TRY301 - input failures share exit status 2
        options = _read_inventory_mapping(mapping)
        loaded = load_model(file)
        if loaded.model is None:
            _print_diagnostics(loaded.diagnostics, fallback_path=file)
            return 2
        if not loaded.complete or any(
            item.severity is Severity.ERROR for item in loaded.diagnostics
        ):
            _print_diagnostics(loaded.diagnostics, fallback_path=file)
            message = "model counts are incomplete; fix model errors before comparing"
            raise ValueError(message)  # noqa: TRY301 - input failures share exit status 2
        expected = read_inventory(
            inventory,
            columns=options.get("columns"),
            colour_map=options.get("colour_map"),
        )
        occurrences = tuple(loaded.model.iter_occurrences(include_steps=False))
        comparison = _compare_inventory_occurrences(
            occurrences=occurrences,
            expected=expected,
            part_aliases=options.get("part_aliases"),
            parts=_inventory_parts(occurrences),
        )
        match output_format:
            case "json":
                text = json.dumps(comparison.to_dict(), indent=2)
            case "csv":
                text = comparison_to_csv(comparison)
            case _:
                text = (
                    "Inventory matches."
                    if comparison.matched
                    else "\n".join(
                        [
                            "Part Colour Expected Actual Missing Extra",
                            *(
                                f"{row.part} {row.colour} {row.expected} {row.actual} "
                                f"{row.missing} {row.extra}"
                                for row in comparison.differences
                            ),
                        ]
                    )
                )
        if out is None:
            print(text.rstrip("\n"))
        else:
            out.write_text(f"{text.rstrip(chr(10))}\n", encoding="utf-8")
    except (OSError, ValueError, PartError, TypeError, ConfigLoadError) as exc:
        print(f"inventory comparison failed: {exc}", file=sys.stderr)
        return 2
    return int(not comparison.matched)
