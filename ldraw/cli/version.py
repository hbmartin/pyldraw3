"""Argument registration and dispatch for version."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    subparsers.add_parser("version", help="Print the installed pyldraw3 version.")


def run(_args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._version import (  # noqa: PLC0415 - deferred command/parser services
        version_command,
    )

    return version_command()
