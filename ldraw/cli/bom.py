"""Argument registration and dispatch for bom."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    bom_parser = subparsers.add_parser(
        "bom",
        help="Print a bill of materials for an LDraw model file.",
    )
    bom_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    bom_parser.add_argument(
        "--compare", type=Path, help="Compare counts against inventory CSV."
    )
    bom_parser.add_argument(
        "--inventory-mapping",
        type=Path,
        help="JSON column, alias, and colour mappings.",
    )
    bom_parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format (default: table).",
    )
    bom_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write output to a file instead of stdout.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._bom import (  # noqa: PLC0415 - deferred command/parser services
        bom_command,
    )

    return bom_command(
        file=args.file,
        output_format=args.format,
        out=args.output,
        compare=args.compare,
        inventory_mapping=args.inventory_mapping,
    )
