"""Argument registration and dispatch for stubs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    stubs_parser = subparsers.add_parser(
        "stubs",
        help="Write a type-stub package for ldraw.library into your project.",
    )
    stubs_parser.add_argument(
        "--out",
        type=Path,
        default=Path(),
        help="Directory to write ldraw-stubs into (default: current directory).",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._stubs import (  # noqa: PLC0415 - deferred command/parser services
        stubs_command,
    )

    return stubs_command(out=args.out)
