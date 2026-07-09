"""Generate the ldraw.library namespace from configured LDraw data."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ldraw.catalog import load_parts
from ldraw.generation.colours import gen_colours
from ldraw.generation.parts import gen_parts
from ldraw.progress import ProgressCallback, ProgressEvent, ProgressStage, emit_progress
from ldraw.resources import _get_resource, _get_resource_content
from ldraw.utils import ensure_exists

if TYPE_CHECKING:
    from ldraw.config import Config

logger = logging.getLogger("ldraw")

# Bump whenever generator output changes (templates, symbol naming, colour
# attribute detection, …) so previously generated libraries regenerate
# instead of silently serving stale modules.
GENERATION_SCHEMA_VERSION = 2


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def generated_library_path(generated_path: str | Path) -> Path:
    """Return the generated ``ldraw.library`` package directory."""
    return Path(generated_path) / "library"


def generation_hash_path(generated_path: str | Path) -> Path:
    """Return the generated-library fingerprint file path."""
    return generated_library_path(generated_path) / "__hash__"


def library_fingerprint(parts_lst: Path) -> str:
    """Fingerprint everything the generated library is derived from.

    Covers the generator schema version, ``parts.lst``, and
    ``ldconfig.ldr`` — a change to any of them (including upgrading to a
    pyldraw version with a fixed parser) invalidates the generation.
    """
    ldconfig_md5 = ""
    for item in parts_lst.parent.iterdir():
        if item.name.lower() == "ldconfig.ldr":
            ldconfig_md5 = _file_md5(item)
            break
    return f"{GENERATION_SCHEMA_VERSION}\n{_file_md5(parts_lst)}\n{ldconfig_md5}\n"


def generate(
    config: Config,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Generate the library from configuration."""
    library_path_out = generated_library_path(config.generated_path)
    ensure_exists(library_path_out)

    hash_path = generation_hash_path(config.generated_path)
    library_path = Path(config.ldraw_library_path)
    parts_lst = library_path / "ldraw" / "parts.lst"
    fingerprint = library_fingerprint(parts_lst)

    if hash_path.exists() and hash_path.read_text() == fingerprint and not force:
        logger.error(
            "Path %s already generated (checksums match)",
            library_path_out,
        )
        return

    emit_progress(
        on_progress,
        ProgressEvent(
            stage=ProgressStage.LIBRARY_GENERATION,
            message="Generating ldraw.library",
            path=library_path_out,
        ),
    )
    shutil.rmtree(library_path_out)
    ensure_exists(library_path_out)

    parts = load_parts(parts_lst, config.generated_path, build_index=True)

    library__init__ = library_path_out / "__init__.py"
    library__init__.write_text(LIBRARY_INIT)
    (library_path_out / "py.typed").write_text("")

    shutil.copy(
        _get_resource("ldraw-license.txt"),
        library_path_out / "license.txt",
    )

    gen_colours(parts, library_path_out)
    gen_parts(parts, library_path_out)

    hash_path.write_text(fingerprint)


LIBRARY_INIT = _get_resource_content("templates/ldraw__init__")
