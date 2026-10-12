"""Argument registration and dispatch for parts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction
from ldraw.cli._defaults import DEFAULT_SEARCH_LIMIT


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    parts_parser = subparsers.add_parser("parts", help="Query the parts catalog.")
    parts_subparsers = parts_parser.add_subparsers(
        dest="parts_command",
        metavar="subcommand",
        required=True,
    )
    search_parser = parts_subparsers.add_parser(
        "search",
        help="Search parts by code, description, category, or keywords.",
    )
    search_parser.add_argument(
        "term",
        help=(
            "Case-insensitive search terms; every whitespace-separated token "
            "must match, and results are ranked by relevance."
        ),
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=f"Maximum matches to print (default: {DEFAULT_SEARCH_LIMIT}).",
    )
    info_parser = parts_subparsers.add_parser(
        "info",
        help="Show details for one part code.",
    )
    info_parser.add_argument("code", help="LDraw part code, e.g. 3001.")
    geometry_parser = parts_subparsers.add_parser(
        "geometry",
        help="Show recursively expanded geometry for one part code.",
    )
    geometry_parser.add_argument("code", help="LDraw part code, e.g. 3001.")
    geometry_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    geometry_parser.add_argument(
        "--ldcad-shadow",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Add an LDCad shadow directory, ZIP, or CSL; repeat as needed.",
    )
    geometry_parser.add_argument(
        "--studio-metadata",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Add a Studio connectivity JSON source; repeat as needed.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._parts import (  # noqa: PLC0415 - deferred command/parser services
        _dispatch_parts,
    )

    return _dispatch_parts(args)
