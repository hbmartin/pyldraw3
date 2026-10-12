"""Runtime services for the parts commands."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from zipfile import BadZipFile

from ldraw.cli._common import (
    _invalid_connection_source,
    _load_parts,
    _load_parts_with_connection_sources,
    _print_report_diagnostics,
    _report_connection_source_error,
    _write_report,
)
from ldraw.cli._inspect import (
    _box_data,
    _connection_data,
    _connection_metadata_data,
    _format_vector,
    _vector_data,
)
from ldraw.errors import PartError
from ldraw.snippets import suggested_import

if TYPE_CHECKING:
    from argparse import Namespace
    from pathlib import Path

    from ldraw.part_geometry_types import PartGeometry
    from ldraw.parts import CatalogEntry


def _suggested_import(entry: CatalogEntry) -> str | None:
    """Return the generated-library import statement for a catalog entry."""
    return suggested_import(entry)


def parts_search_command(  # noqa: PLR0913 - explicit search and presentation options
    *,
    term: str,
    limit: int,
    offset: int = 0,
    output_format: str = "table",
    output: Path | None = None,
    category: str | None = None,
    physical_only: bool = False,
) -> int:
    """Search with pagination, full totals, filters, and fallback diagnostics."""
    if (parts := _load_parts()) is None:
        return 1
    result = parts.search(
        term, category=category, physical_only=physical_only, limit=limit, offset=offset
    )
    if output_format == "json":
        text = json.dumps(
            {
                "items": [
                    {
                        "code": entry.code,
                        "category": entry.category.value,
                        "description": entry.description,
                    }
                    for entry in result.items
                ],
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
                "diagnostics": [item.to_dict() for item in result.diagnostics],
            },
            indent=2,
        )
    else:
        text = "\n".join(
            f"{entry.code:<12} {entry.category.value:<20} {entry.description}"
            for entry in result.items
        )
        remaining = max(result.total - offset - len(result.items), 0)
        if remaining:
            text = f"{text}\n... and {remaining} more (use --limit)."
        text = f"{text}\nTotal matches: {result.total}"
        if not result.total:
            print(f"No parts found matching {term!r}.", file=sys.stderr)
        for diagnostic in result.diagnostics:
            print(diagnostic.message, file=sys.stderr)
    written = _write_report(text, out=output, description="catalog search")
    return 0 if written and result.total else 1


def parts_info_command(*, code: str) -> int:
    """Show catalog details for one part code."""
    if (parts := _load_parts()) is None:
        return 1
    entry = parts.get_entry_by_code(code)
    if entry is None:
        print(f"No part with code {code!r}.", file=sys.stderr)
        return 1
    print(f"code: {entry.code}")
    print(f"description: {entry.description}")
    print(f"category: {entry.category.value}")
    if entry.minifig_section is not None:
        print(f"minifig section: {entry.minifig_section.value}")
    if entry.part is not None:
        print(f"file: {entry.part.path}")
    if (import_line := _suggested_import(entry)) is not None:
        print(f"import: {import_line}")
    return 0


def parts_geometry_command(
    *,
    code: str,
    output_format: str,
    connection_shadows: tuple[Path, ...] = (),
    studio_metadata: tuple[Path, ...] = (),
) -> int:
    """Show expanded geometry and completeness diagnostics for one part."""
    if (
        error := _invalid_connection_source(
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    ) is not None:
        print(error, file=sys.stderr)
        return 1
    if (
        parts := _load_parts_with_connection_sources(
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    ) is None:
        return 1
    try:
        geometry = parts.geometry(code)
    except (BadZipFile, OSError) as error:
        _report_connection_source_error(error)
        return 1
    except PartError as exc:
        print(exc, file=sys.stderr)
        return 1

    payload = _part_geometry_data(geometry)
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"code: {geometry.code}")
    print(f"description: {geometry.description}")
    print(f"complete: {'yes' if geometry.legacy_complete else 'no'}")
    print(f"expanded points: {len(geometry.points)}")
    print(f"connections: {len(geometry.connections)}")
    print(
        f"studs: {len(geometry.studs)} "
        f"({len(geometry.top_studs)} top, "
        f"{len(geometry.receptacles)} receptacles)"
    )
    if geometry.bounds is None:
        print("bounds: none")
    else:
        print(f"bounds min: {_format_vector(geometry.bounds.min)}")
        print(f"bounds max: {_format_vector(geometry.bounds.max)}")
        print(f"size: {_format_vector(geometry.bounds.size)}")
    _print_report_diagnostics(geometry.diagnostics)
    return 0


def _dispatch_parts(args: Namespace) -> int:
    """Dispatch one nested parts subcommand."""
    match args.parts_command:
        case "search":
            return parts_search_command(
                term=args.term,
                limit=args.limit,
                offset=args.offset,
                output_format=args.format,
                output=args.output,
                category=args.category,
                physical_only=args.physical_only,
            )
        case "geometry":
            return parts_geometry_command(
                code=args.code,
                output_format=args.format,
                connection_shadows=tuple(args.ldcad_shadow),
                studio_metadata=tuple(args.studio_metadata),
            )
        case "measurements":
            return parts_measurements_command(
                code=args.code, output_format=args.format, output=args.output
            )
        case "info":
            return parts_info_command(code=args.code)
        case _:
            msg = f"Unhandled parts subcommand: {args.parts_command!r}"
            raise AssertionError(msg)


def _part_geometry_data(geometry: PartGeometry) -> dict[str, object]:
    """Serialize geometry with compatibility and explicit coverage fields."""
    return {
        "bounds": _box_data(geometry.bounds),
        "code": geometry.code,
        "complete": geometry.legacy_complete,
        "geometry_coverage": geometry.geometry_coverage.value,
        "connection_coverage": geometry.connection_coverage.value,
        "connection_count": len(geometry.connections),
        "connections": [
            _connection_data(connection) for connection in geometry.connections
        ],
        "connection_metadata": _connection_metadata_data(
            geometry.connection_metadata,
        ),
        "description": geometry.description,
        "diagnostics": [item.to_dict() for item in geometry.diagnostics],
        "point_count": len(geometry.points),
        "receptacle_count": len(geometry.receptacles),
        "stud_count": len(geometry.studs),
        "studs": [
            {
                "description": stud.description,
                "is_placeholder": stud.is_placeholder,
                "is_receptacle": stud.is_receptacle,
                "is_top_stud": stud.is_top_stud,
                "name": stud.name,
                "position": _vector_data(stud.position),
                "up": _vector_data(stud.up),
            }
            for stud in geometry.studs
        ],
        "top_stud_count": len(geometry.top_studs),
    }


def parts_measurements_command(
    *, code: str, output_format: str, output: Path | None
) -> int:
    """Report supported measurements and absent values with diagnostics."""
    if (parts := _load_parts()) is None:
        return 1
    try:
        result = parts.measurements(code)
    except PartError as error:
        print(error, file=sys.stderr)
        return 1
    data = result.to_dict()
    text = (
        json.dumps(data, indent=2)
        if output_format == "json"
        else "\n".join(f"{key}: {value}" for key, value in data.items())
    )
    return 0 if _write_report(text, out=output, description="measurements") else 1
