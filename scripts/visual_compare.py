#!/usr/bin/env python3
"""Run the optional pyldraw3 raster visual-comparison tool."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Load and run the optional tool with an actionable dependency error."""
    try:
        from ldraw.visual_compare import main as visual_compare_main  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        if exc.name != "PIL":
            raise
        print(
            "error: visual comparison requires Pillow; install "
            "pyldraw3[visual-compare] or run `uv sync --extra visual-compare`",
            file=sys.stderr,
        )
        return 1
    return visual_compare_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
