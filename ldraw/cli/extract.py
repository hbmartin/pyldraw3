"""Dependency-closed extraction without importing runtime services for help."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def register(subparsers: _SubParsersAction) -> None:
    """Register the document reuse workflow."""
    parser = subparsers.add_parser(
        "extract", help="Extract a section and its dependencies."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("section")
    parser.add_argument("--namespace", default="")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)


def run(args: Namespace) -> int:
    """Save the extracted document and optional attribution manifest."""
    from ldraw.cli._document_reports import extract_command  # noqa: PLC0415

    return extract_command(
        file=args.file,
        section=args.section,
        namespace=args.namespace,
        output=args.output,
        manifest=args.manifest,
    )
