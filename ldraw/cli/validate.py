"""Argument registration and dispatch for validate."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an LDraw file (.ldr, .mpd, or .dat).",
    )
    validate_parser.add_argument(
        "file",
        type=Path,
        help="Path to the file to validate.",
    )
    validate_parser.add_argument(
        "--profile", choices=("format", "assembly"), default="format"
    )
    validate_parser.add_argument("--matrix-tolerance", type=float, default=1e-6)
    validate_parser.add_argument("--connectivity", action="store_true")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._validate import (  # noqa: PLC0415 - deferred command/parser services
        validate_command,
    )

    return validate_command(
        file=args.file,
        strict=args.strict,
        profile=args.profile,
        matrix_tolerance=args.matrix_tolerance,
        connectivity=args.connectivity,
    )
