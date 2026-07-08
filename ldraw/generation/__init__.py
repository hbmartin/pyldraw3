"""Generate the ldraw.library namespace from configured LDraw data."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ldraw.generation.colours import gen_colours
from ldraw.generation.parts import gen_parts
from ldraw.parts import Parts
from ldraw.resources import _get_resource, _get_resource_content
from ldraw.utils import ensure_exists

if TYPE_CHECKING:
    from ldraw.config import Config

logger = logging.getLogger("ldraw")


def generate(config: Config, *, force: bool = False) -> None:
    """Generate the library from configuration."""
    generated_library_path = Path(config.generated_path) / "library"
    ensure_exists(generated_library_path)

    hash_path = generated_library_path / "__hash__"
    library_path = Path(config.ldraw_library_path)
    parts_lst = library_path / "ldraw" / "parts.lst"
    md5_parts_lst = hashlib.md5(
        parts_lst.read_bytes(),
        usedforsecurity=False,
    ).hexdigest()

    if hash_path.exists():
        md5 = hash_path.read_text()
        if md5 == md5_parts_lst and not force:
            logger.error(
                "Path %s already generated (checksums match)",
                generated_library_path,
            )
            return

    shutil.rmtree(generated_library_path)
    ensure_exists(generated_library_path)

    parts = Parts(parts_lst)

    library__init__ = generated_library_path / "__init__.py"
    library__init__.write_text(LIBRARY_INIT)
    (generated_library_path / "py.typed").write_text("")

    shutil.copy(
        _get_resource("ldraw-license.txt"),
        generated_library_path / "license.txt",
    )

    gen_colours(parts, generated_library_path)
    gen_parts(parts, generated_library_path)

    hash_path.write_text(md5_parts_lst)


LIBRARY_INIT = _get_resource_content("templates/ldraw__init__")
