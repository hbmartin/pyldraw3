"""Portable library selection and cache-only indexing of installations."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TYPE_CHECKING

from ldraw.config import Config, get_config
from ldraw.diagnostics import Diagnostic, Severity
from ldraw.dirs import get_cache_dir
from ldraw.library_setup import discover_libraries, inspect_library

if TYPE_CHECKING:
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class LibrarySelection:
    """Selected data directory and the evidence that selected it."""

    directory: Path
    source: str


def data_directory(path: str | Path) -> Path:
    """Accept an installation root or its data directory."""
    return inspect_library(path).ldraw_path


def usable_directory(path: str | Path) -> bool:
    """Geometry trees are required; a missing parts list can be synthesized."""
    directory = data_directory(path)
    return (directory / "parts").is_dir() and (directory / "p").is_dir()


def select_library(
    config: Config | None = None, *, library: str | Path | None = None
) -> LibrarySelection:
    """Select explicitly, then environment, saved config, cache, and discovery."""
    explicit = (
        (library, "argument")
        if library is not None
        else (config.ldraw_library_path, "configuration")
        if config is not None
        else None
    )
    if explicit is not None:
        path, source = explicit
        if not usable_directory(path):
            message = (
                f"Invalid explicit LDraw {source}: {path}; "
                "select a directory containing parts/ and p/ with --library"
            )
            raise FileNotFoundError(message)
        return LibrarySelection(directory=data_directory(path), source=source)
    if environment := _environment_selection():
        return environment
    cfg = Config.load()
    if get_config().is_file() and usable_directory(cfg.ldraw_library_path):
        return LibrarySelection(
            directory=data_directory(cfg.ldraw_library_path),
            source="saved-configuration",
        )
    if usable_directory(Config().ldraw_library_path):
        return LibrarySelection(
            directory=data_directory(Config().ldraw_library_path),
            source="default-cache",
        )
    return _discovered_selection()


def _environment_selection() -> LibrarySelection | None:
    for key in ("LDRAW_DIR", "LDRAWDIR"):
        if value := os.environ.get(key):
            if not usable_directory(value):
                message = (
                    f"Invalid {key}={value!r}; select a valid library or unset {key}"
                )
                raise FileNotFoundError(message)
            return LibrarySelection(directory=data_directory(value), source=key)
    return None


def _discovered_selection() -> LibrarySelection:
    candidates = {
        item.ldraw_path.resolve()
        for item in discover_libraries()
        if usable_directory(item.ldraw_path)
    }
    if len(candidates) > 1:
        paths = ", ".join(str(path) for path in sorted(candidates))
        message = f"Multiple LDraw libraries found: {paths}; select --library"
        raise ValueError(message)
    if candidates:
        return LibrarySelection(directory=candidates.pop(), source="discovery")
    message = (
        "No LDraw library found; use --library PATH or explicitly run ldraw download"
    )
    raise FileNotFoundError(message)


def index_directory(directory: Path, cache: str | Path | None = None) -> Path:
    """Return a source-specific cache path without creating it."""
    identity = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:24]
    base = Path(cache) if cache is not None else Path(get_cache_dir()) / "indexes"
    return base / identity


def _index_text(directory: Path) -> str:
    lines: list[str] = []
    for path in sorted((directory / "parts").glob("*.dat")):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            description = stream.readline().strip().removeprefix("0").strip()
        lines.append(f"{path.name} {description}\n")
    return "".join(lines)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def directory_parts(directory: str | Path, *, cache: str | Path | None = None) -> Parts:
    """Prepare indexes locally; read geometry from the untouched source."""
    from ldraw.catalog import (  # noqa: PLC0415
        load_catalog,
        parts_lst_md5,
        parts_tree_fingerprint,
    )
    from ldraw.parts import Parts  # noqa: PLC0415

    source = select_library(library=directory).directory
    cache_dir = index_directory(source, cache=cache)
    parts_list = source / "parts.lst"
    diagnostics: list[Diagnostic] = []
    temporary: TemporaryDirectory[str] | None = None
    if not parts_list.is_file():
        text = _index_text(source)
        parts_list = cache_dir / "parts.lst"
        try:
            if (
                not parts_list.is_file()
                or parts_list.read_text(encoding="utf-8") != text
            ):
                _atomic_text(parts_list, text)
        except OSError as error:
            temporary = TemporaryDirectory(prefix="pyldraw-index-")
            parts_list = Path(temporary.name) / "parts.lst"
            parts_list.write_text(text, encoding="utf-8")
            diagnostics.append(
                Diagnostic(
                    code="catalog.persist_failed",
                    severity=Severity.WARNING,
                    message=f"Using temporary part index: {error}",
                )
            )
    parts = Parts(parts_list, library_root=source)
    parts._temporary_index = temporary  # noqa: SLF001 - owns temporary lifetime
    db = cache_dir / "catalog.sqlite"
    tree = parts_tree_fingerprint(source)
    md5 = parts_lst_md5(parts_list)
    catalog = load_catalog(db, md5=md5, library_root=source, tree_fingerprint=tree)
    if catalog is not None:
        parts.adopt_catalog(catalog)
        parts.search_index = db
    else:
        _persist_directory_catalog(
            parts, db=db, md5=md5, tree=tree, diagnostics=diagnostics
        )
    parts.diagnostics = tuple(diagnostics)
    return parts


def _persist_directory_catalog(
    parts: Parts, *, db: Path, md5: str, tree: str, diagnostics: list[Diagnostic]
) -> None:
    from ldraw.catalog import save_catalog  # noqa: PLC0415

    catalog = parts.catalog
    temporary: Path | None = None
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=db.parent, delete=False) as stream:
            temporary = Path(stream.name)
        save_catalog(
            temporary,
            md5=md5,
            catalog=catalog,
            library_root=parts.library_root,
            tree_fingerprint=tree,
        )
        temporary.replace(db)
        parts.search_index = db
    except (OSError, sqlite3.Error) as error:
        diagnostics.append(
            Diagnostic(
                code="catalog.persist_failed",
                severity=Severity.WARNING,
                message=f"Catalog cache unavailable: {error}",
            )
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
