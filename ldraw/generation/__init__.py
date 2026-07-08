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


def _library_fingerprint(parts_lst: Path) -> str:
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


def generate(config: Config, *, force: bool = False) -> None:
    """Generate the library from configuration."""
    generated_library_path = Path(config.generated_path) / "library"
    ensure_exists(generated_library_path)

    hash_path = generated_library_path / "__hash__"
    library_path = Path(config.ldraw_library_path)
    parts_lst = library_path / "ldraw" / "parts.lst"
    fingerprint = _library_fingerprint(parts_lst)

    if hash_path.exists() and hash_path.read_text() == fingerprint and not force:
        logger.error(
            "Path %s already generated (checksums match)",
            generated_library_path,
        )
        return

    shutil.rmtree(generated_library_path)
    ensure_exists(generated_library_path)

    parts = load_parts(parts_lst, config.generated_path, build_index=True)

    library__init__ = generated_library_path / "__init__.py"
    library__init__.write_text(LIBRARY_INIT)
    (generated_library_path / "py.typed").write_text("")

    shutil.copy(
        _get_resource("ldraw-license.txt"),
        generated_library_path / "license.txt",
    )

    gen_colours(parts, generated_library_path)
    gen_parts(parts, generated_library_path)

    hash_path.write_text(fingerprint)


LIBRARY_INIT = _get_resource_content("templates/ldraw__init__")
