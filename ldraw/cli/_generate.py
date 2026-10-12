"""Runtime services for the generate commands."""

from __future__ import annotations

import sys

from ldraw import generate as do_generate
from ldraw.cli._common import _confirm
from ldraw.config import Config
from ldraw.generation.exceptions import UnwritableOutputError


def generate_command(*, yes: bool, force: bool) -> int:
    """Generate the ldraw.library modules after confirmation."""
    config = Config.load()
    prompt = f"This will delete and regenerate {config.generated_path}. Continue?"
    if not _confirm(prompt, yes=yes):
        print("Aborted.")
        return 1

    try:
        do_generate(config=config, force=force)
    except UnwritableOutputError:
        print(
            f"{config.generated_path} is unwritable, select another out directory",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError:
        print(
            f"LDraw library not found under {config.ldraw_library_path}; "
            "run `ldraw download` first.",
            file=sys.stderr,
        )
        return 1
    print(
        "Run 'ldraw stubs' from your project root to refresh the ldraw-stubs "
        "package for IDE autocomplete and type checking.",
    )
    return 0
