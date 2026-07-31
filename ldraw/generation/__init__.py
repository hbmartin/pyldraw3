"""Generate the ldraw.library namespace from configured LDraw data."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ldraw.catalog import CatalogFingerprint, load_parts, parts_tree_fingerprint
from ldraw.generation.colours import gen_colours
from ldraw.generation.exceptions import (
    GeneratedModuleSyntaxError,
    UnwritableOutputError,
)
from ldraw.generation.parts import gen_parts
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.progress import ProgressCallback, ProgressEvent, ProgressStage, emit_progress
from ldraw.resources import _get_resource_content
from ldraw.utils import ensure_exists

if TYPE_CHECKING:
    from ldraw.config import Config

logger = logging.getLogger("ldraw")

# Bump whenever generator output changes (templates, symbol naming, colour
# attribute detection, …) so previously generated libraries regenerate
# instead of silently serving stale modules.
GENERATION_SCHEMA_VERSION = 3


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def generated_library_path(generated_path: str | Path) -> Path:
    """Return the generated ``ldraw.library`` package directory."""
    return Path(generated_path) / "library"


def generation_hash_path(generated_path: str | Path) -> Path:
    """Return the generated-library fingerprint file path."""
    return generated_library_path(generated_path) / "__hash__"


def library_fingerprint(
    parts_lst: Path,
    *,
    parts_lst_digest: str | None = None,
    tree_fingerprint: str | None = None,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> str:
    """Fingerprint everything the generated library is derived from.

    Covers the generator schema version, ``parts.lst``, ``ldconfig.ldr``,
    and a per-file stat fingerprint of the part trees — a change to any of
    them, including renames and in-place ``.dat`` header edits, invalidates
    the generation.
    """
    ldconfig_md5 = ""
    for item in parts_lst.parent.iterdir():
        if item.name.lower() == "ldconfig.ldr":
            ldconfig_md5 = _file_md5(item)
            break
    tree = tree_fingerprint or parts_tree_fingerprint(
        parts_lst.parent,
        on_progress=on_progress,
        cancellation=cancellation,
    )
    return (
        f"{GENERATION_SCHEMA_VERSION}\n"
        f"{parts_lst_digest or _file_md5(parts_lst)}\n{ldconfig_md5}\n{tree}\n"
    )


def generate(
    config: Config,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    fingerprint: str | None = None,
    cancellation: CancellationToken | None = None,
) -> None:
    """Generate the library from configuration."""
    library_path_out = generated_library_path(config.generated_path)
    try:
        ensure_exists(library_path_out)
    except OSError as exc:
        raise UnwritableOutputError(str(library_path_out)) from exc

    hash_path = generation_hash_path(config.generated_path)
    library_path = Path(config.ldraw_library_path)
    parts_lst = library_path / "ldraw" / "parts.lst"
    fingerprint = fingerprint or library_fingerprint(parts_lst)

    if hash_path.exists() and hash_path.read_text() == fingerprint and not force:
        logger.info(
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
    check_cancelled(cancellation)
    try:
        shutil.rmtree(library_path_out)
        ensure_exists(library_path_out)
    except OSError as exc:
        raise UnwritableOutputError(str(library_path_out)) from exc

    fingerprint_lines = fingerprint.splitlines()
    catalog_snapshot = CatalogFingerprint(
        parts_lst_md5=fingerprint_lines[1],
        tree_fingerprint=fingerprint_lines[3],
        generation_fingerprint=fingerprint,
    )
    parts = load_parts(
        parts_lst,
        config.generated_path,
        build_index=True,
        fingerprint=catalog_snapshot,
        on_progress=on_progress,
        cancellation=cancellation,
    )
    check_cancelled(cancellation)

    library__init__ = library_path_out / "__init__.py"
    library__init__.write_text(LIBRARY_INIT)
    (library_path_out / "py.typed").write_text("")

    (library_path_out / "license.txt").write_text(
        _get_resource_content("ldraw-license.txt"),
        encoding="utf-8",
    )

    gen_colours(parts, library_path_out, cancellation=cancellation)
    check_cancelled(cancellation)
    gen_parts(parts, library_path_out, cancellation=cancellation)
    check_cancelled(cancellation)

    _verify_generated_modules(library_path_out)
    check_cancelled(cancellation)
    hash_path.write_text(fingerprint)


def _verify_generated_modules(library_path_out: Path) -> None:
    """Compile every generated module so a broken generation never looks fresh."""
    for py_file in sorted(library_path_out.rglob("*.py")):
        try:
            compile(
                py_file.read_text(encoding="utf-8"),
                str(py_file),
                "exec",
            )
        except SyntaxError as exc:
            raise GeneratedModuleSyntaxError(str(py_file)) from exc


LIBRARY_INIT = _get_resource_content("templates/ldraw__init__")
