"""Argument registration and dispatch for inspect."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction
from ldraw.cli._defaults import DEFAULT_PAGE_MARKER_PREFIX


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    model_inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect exact world bounds, provenance, contacts, and gaps.",
    )
    model_inspect_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    model_inspect_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    model_inspect_parser.add_argument(
        "--gap-threshold",
        type=float,
        default=5.0,
        help="Report nearest AABB gaps larger than this many LDU (default: 5).",
    )
    model_inspect_parser.add_argument(
        "--chronological",
        action="store_true",
        help="Exclude neighbours installed on a later attributed page.",
    )
    model_inspect_parser.add_argument(
        "--page-marker-prefix",
        default=DEFAULT_PAGE_MARKER_PREFIX,
        help=(
            "Comment prefix used to attribute pages "
            f"(default: {DEFAULT_PAGE_MARKER_PREFIX!r})."
        ),
    )
    model_inspect_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write output to a file instead of stdout.",
    )
    model_inspect_parser.add_argument(
        "--ldcad-shadow",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Add an LDCad shadow directory, ZIP, or CSL; repeat as needed.",
    )
    model_inspect_parser.add_argument(
        "--studio-metadata",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Add a Studio connectivity JSON source; repeat as needed.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._inspect import (  # noqa: PLC0415 - deferred command/parser services
        inspect_command,
    )

    return inspect_command(
        file=args.file,
        output_format=args.format,
        gap_threshold=args.gap_threshold,
        chronological=args.chronological,
        page_marker_prefix=args.page_marker_prefix,
        out=args.output,
        connection_shadows=tuple(args.ldcad_shadow),
        studio_metadata=tuple(args.studio_metadata),
    )
