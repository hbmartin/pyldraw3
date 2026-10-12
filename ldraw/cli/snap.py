"""Bounded snap suggestions, with no model mutation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register qualified connection-search controls."""
    parser = subparsers.add_parser(
        "snap", help="Report candidate snap transforms and coverage."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--moving", type=int, required=True)
    parser.add_argument("--fixed", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--occurrence-budget", type=int)
    parser.add_argument("--feature-pair-budget", type=int)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--ldcad-shadow", action="append", type=Path, default=[])
    parser.add_argument("--studio-metadata", action="append", type=Path, default=[])


def run(args: Namespace) -> int:
    """Run the bounded search without applying its transforms."""
    from ldraw.cli._document_reports import snap_command  # noqa: PLC0415

    return snap_command(args)
