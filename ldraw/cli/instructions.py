"""Argument registration and dispatch for instructions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    instructions_parser = subparsers.add_parser(
        "instructions",
        help="Inspect, validate, and export renderer-neutral instructions.",
    )
    instruction_subparsers = instructions_parser.add_subparsers(
        dest="instructions_command",
        metavar="subcommand",
        required=True,
    )
    inspect_parser = instruction_subparsers.add_parser(
        "inspect",
        help="Print section-local instruction step summaries.",
    )
    inspect_parser.add_argument("file", type=Path, help="LDraw model file.")
    inspect_parser.add_argument("--section", help="Inspect one reachable section.")
    inspect_parser.add_argument(
        "--parts",
        action="store_true",
        help="Show each step's added parts tray.",
    )
    instruction_validate_parser = instruction_subparsers.add_parser(
        "validate",
        help="Run LDraw and instruction-structure validation.",
    )
    instruction_validate_parser.add_argument(
        "file",
        type=Path,
        help="LDraw model file.",
    )
    instruction_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    instruction_validate_parser.add_argument(
        "--max-parts",
        type=int,
        default=None,
        help="Warn when a step adds more than this many expanded parts.",
    )
    export_parser = instruction_subparsers.add_parser(
        "export",
        help="Write a schema-versioned JSON instruction manifest.",
    )
    export_parser.add_argument("file", type=Path, help="LDraw model file.")
    export_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write to a file instead of stdout.",
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing manifest file.",
    )
    snapshots_parser = instruction_subparsers.add_parser(
        "snapshots",
        help="Write cumulative MPD/LDR snapshots and their manifest.",
    )
    snapshots_parser.add_argument("file", type=Path, help="LDraw model file.")
    snapshots_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for the snapshot bundle.",
    )
    snapshots_parser.add_argument(
        "--section",
        help="Generate snapshots for one reachable section.",
    )
    snapshots_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate files owned by an existing pyldraw3 manifest.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._instructions import (  # noqa: PLC0415 - deferred command/parser services
        _dispatch_instructions,
    )

    return _dispatch_instructions(args)
