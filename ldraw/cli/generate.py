"""Argument registration and dispatch for generate."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate the ldraw.library modules from the downloaded library.",
    )
    generate_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Do not ask for confirmation.",
    )
    generate_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Regenerate even if the generated library is already up to date.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._generate import (  # noqa: PLC0415 - deferred command/parser services
        generate_command,
    )

    return generate_command(yes=args.yes, force=args.force)
