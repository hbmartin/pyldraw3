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

    from ldraw.parts import CatalogEntry


def _suggested_import(entry: CatalogEntry) -> str | None:
    """Return the generated-library import statement for a catalog entry."""
    return suggested_import(entry)


def parts_search_command(*, term: str, limit: int) -> int:
    """Search the parts catalog through the shared public search API."""
    if (parts := _load_parts()) is None:
        return 1
    matches = parts.catalog.search(term)
    if not matches:
        print(f"No parts found matching {term!r}.", file=sys.stderr)
        return 1
    for entry in matches[:limit]:
        print(f"{entry.code:<12} {entry.category.value:<20} {entry.description}")
    if len(matches) > limit:
        print(f"... and {len(matches) - limit} more (use --limit).")
    return 0


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

    payload = {
        "bounds": _box_data(geometry.bounds),
        "code": geometry.code,
        "complete": geometry.complete,
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
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"code: {geometry.code}")
    print(f"description: {geometry.description}")
    print(f"complete: {'yes' if geometry.complete else 'no'}")
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
            return parts_search_command(term=args.term, limit=args.limit)
        case "geometry":
            return parts_geometry_command(
                code=args.code,
                output_format=args.format,
                connection_shadows=tuple(args.ldcad_shadow),
                studio_metadata=tuple(args.studio_metadata),
            )
        case "info":
            return parts_info_command(code=args.code)
        case _:
            msg = f"Unhandled parts subcommand: {args.parts_command!r}"
            raise AssertionError(msg)
