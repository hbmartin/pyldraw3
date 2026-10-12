"""Argument registration and dispatch for config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    subparsers.add_parser("config", help="Print the current configuration.")


def run(_args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._config import (  # noqa: PLC0415 - deferred command/parser services
        config_command,
    )

    return config_command()
