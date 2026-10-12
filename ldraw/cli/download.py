"""Argument registration and dispatch for download."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction
from ldraw.cli._defaults import COMPLETE_VERSION


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    download_parser = subparsers.add_parser(
        "download",
        help="Download and unpack an LDraw parts library release.",
    )
    download_parser.add_argument(
        "--version",
        default=COMPLETE_VERSION,
        help=f"LDraw library release, e.g. 2018-02 (default: {COMPLETE_VERSION}).",
    )
    download_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Do not ask for confirmation.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._download import (  # noqa: PLC0415 - deferred command/parser services
        download_command,
    )

    return download_command(version=args.version, yes=args.yes)
