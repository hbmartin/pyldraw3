"""Options and service for library-independent API discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register public inventory presentation options."""
    parser = subparsers.add_parser(
        "api", help="Discover Python APIs without a parts library."
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path)


def run(args: Namespace) -> int:
    """Print a page and full matching total."""
    from ldraw.api import api_inventory  # noqa: PLC0415 - deferred services
    from ldraw.cli._common import _write_report  # noqa: PLC0415 - deferred services

    result = api_inventory(args.query, limit=args.limit, offset=args.offset)
    if args.format == "json":
        text = json.dumps(
            {
                "items": [entry.to_dict() for entry in result.items],
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
            },
            indent=2,
        )
    else:
        text = "\n".join(
            f"{entry.qualified_name}{entry.signature or ''}\n  "
            f"{entry.docstring.splitlines()[0] if entry.docstring else ''}"
            for entry in result.items
        )
        text = f"{text}\nTotal matches: {result.total}"
    return 0 if _write_report(text, out=args.output, description="API inventory") else 1
