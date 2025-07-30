"""Module tasked with generating python files for the ldraw.library namespace."""

import hashlib
import logging
import os
import shutil
from pathlib import Path

from ldraw.config import Config
from ldraw.generation.colours import gen_colours
from ldraw.generation.parts import gen_parts
from ldraw.parts import Parts
from ldraw.resources import _get_resource, _get_resource_content
from ldraw.utils import ensure_exists

logger = logging.getLogger("ldraw")


def generate(config: Config, *, force=False):
    """Generate the library from configuration."""
    generated_library_path = os.path.join(config.generated_path, "library")
    ensure_exists(generated_library_path)

    hash_path = Path(generated_library_path) / "__hash__"

    library_path = Path(config.ldraw_library_path)

    parts_lst = library_path / "ldraw" / "parts.lst"
    md5_parts_lst = hashlib.md5(parts_lst.read_bytes()).hexdigest()

    if hash_path.exists():
        md5 = hash_path.read_text()
        if md5 == md5_parts_lst and not force:
            logger.error(
                "Path %s already generated (checksums match)",
                generated_library_path,
            )
            return

    # pyrefly: ignore  # deprecated  # noqa: ERA001
    shutil.rmtree(generated_library_path)
    ensure_exists(generated_library_path)

    parts = Parts(parts_lst)

    library__init__ = os.path.join(generated_library_path, "__init__.py")

    with open(library__init__, "w") as library__init__:
        library__init__.write(LIBRARY_INIT)

    shutil.copy(
        _get_resource("ldraw-license.txt"),
        os.path.join(generated_library_path, "license.txt"),
    )

    gen_colours(parts, generated_library_path)
    gen_parts(parts, generated_library_path)

    hash_path.write_text(md5_parts_lst)


LIBRARY_INIT = _get_resource_content(os.path.join("templates", "ldraw__init__"))
