"""Runtime services for the stubs commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ldraw.config import Config
from ldraw.errors import LibraryNotGeneratedError
from ldraw.stubs import write_stub_package

if TYPE_CHECKING:
    from pathlib import Path


def stubs_command(*, out: Path) -> int:
    """Write the ldraw-stubs package for IDE autocomplete and type checking."""
    try:
        stubs_dir = write_stub_package(
            generated_path=Config.load().generated_path,
            out_dir=out,
        )
    except LibraryNotGeneratedError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Could not write stubs to {out}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote stub package to {stubs_dir}")
    return 0
