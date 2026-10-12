"""Read-only library diagnosis command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register diagnosis options."""
    parser = subparsers.add_parser(
        "doctor", help="Diagnose library, cache, and renderer availability."
    )
    parser.add_argument("--format", choices=("table", "json"), default="table")


def run(args: Namespace) -> int:
    """Report facts without repairing the installation."""
    from ldraw.diagnosis import doctor  # noqa: PLC0415 - deferred services

    report = doctor(library=args.library)
    data = report.to_dict()
    print(
        json.dumps(data, indent=2)
        if args.format == "json"
        else "\n".join(f"{key}: {value}" for key, value in data.items())
    )
    return 0
