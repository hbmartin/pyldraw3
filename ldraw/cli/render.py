"""Argument registration and dispatch for render."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction
from ldraw.cli._defaults import DEFAULT_RENDER_SIZE
from ldraw.rendering import RenderBackend, RenderView


def register(subparsers: _SubParsersAction) -> None:
    """Register command options without loading command services."""
    render_parser = subparsers.add_parser(
        "render",
        help="Render a deterministic set of standard preview views.",
    )
    render_parser.add_argument("--section", help="Render a selected MPD section.")
    render_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    render_parser.add_argument(
        "--view",
        action="append",
        type=RenderView,
        choices=tuple(RenderView),
        default=None,
        help="Standard view to render; repeat for multiple views.",
    )
    render_parser.add_argument(
        "--size",
        default=f"{DEFAULT_RENDER_SIZE[0]}x{DEFAULT_RENDER_SIZE[1]}",
        metavar="WIDTHxHEIGHT",
        help=(
            f"Image size (default: {DEFAULT_RENDER_SIZE[0]}x{DEFAULT_RENDER_SIZE[1]})."
        ),
    )
    render_parser.add_argument(
        "--backend",
        choices=("auto", *(backend.value for backend in RenderBackend)),
        default="auto",
        help="Renderer backend (default: auto).",
    )
    render_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: beside the model).",
    )
    render_parser.add_argument(
        "--prefix",
        default=None,
        help="Output filename prefix (default: model stem).",
    )
    render_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass cached previews and render fresh images.",
    )
    render_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing requested images after every view succeeds.",
    )


def run(args: Namespace) -> int:
    """Invoke the command service."""
    from ldraw.cli._render import (  # noqa: PLC0415 - deferred command/parser services
        render_command,
    )

    return render_command(
        file=args.file,
        views=args.view,
        size=args.size,
        backend=args.backend,
        output_dir=args.output_dir,
        prefix=args.prefix,
        refresh=args.refresh,
        overwrite=args.overwrite,
        section=args.section,
    )
