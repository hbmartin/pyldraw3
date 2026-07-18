"""Persistent on-disk index for the parts catalog.

Building a :class:`~ldraw.parts.PartsCatalog` requires opening every part
file in the library for its ``!CATEGORY`` header — tens of thousands of
file reads for a full LDraw release. This module caches the result in a
single SQLite file under the configured ``generated_path`` so later runs
skip that pass entirely. The index is keyed to the MD5 of ``parts.lst``
plus a per-file metadata fingerprint of the part trees (so in-place ``.dat``
header edits invalidate it) and is best-effort: any missing, stale,
corrupt, or version-mismatched index simply falls back to a full build.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

from ldraw.part import Part
from ldraw.parts import (
    CatalogEntry,
    MinifigSection,
    PartCategory,
    Parts,
    PartsCatalog,
)

logger = logging.getLogger(__name__)

# Version 4: freshness is additionally keyed to a per-file parts-tree
# metadata fingerprint (meta key `tree_fingerprint`), so path, size, or mtime
# changes that leave parts.lst byte-identical still invalidate the index.
# (Version 3: entry descriptions stored as written in parts.lst.)
CATALOG_SCHEMA_VERSION = 4

_CREATE_META = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
_CREATE_PARTS = """
CREATE TABLE parts (
    code            TEXT PRIMARY KEY,
    description     TEXT NOT NULL,
    category        TEXT NOT NULL,
    minifig_section TEXT,
    path            TEXT,
    keywords        TEXT NOT NULL DEFAULT ''
)
"""

_KEYWORDS_SEPARATOR = "\t"


def catalog_db_path(generated_path: str | Path) -> Path:
    """Return the index location for a configured ``generated_path``."""
    return Path(generated_path) / "catalog.sqlite"


def parts_lst_md5(parts_lst: Path) -> str:
    """Return the MD5 digest of a ``parts.lst`` file."""
    return hashlib.md5(parts_lst.read_bytes(), usedforsecurity=False).hexdigest()


def parts_tree_fingerprint(ldraw_dir: Path) -> str:
    """Hash each file's relative path, size, and mtime in the parts and p trees.

    Catches in-place ``.dat`` header edits (``!CATEGORY``/``!KEYWORDS``)
    that leave ``parts.lst`` byte-identical. A stat-only pass — no file
    contents are read.
    """
    digest = hashlib.sha256()
    for sub in ("parts", "p"):
        root = ldraw_dir / sub
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in root.walk():
            dirnames.sort()
            for filename in sorted(filenames):
                path = dirpath / filename
                stat_result = path.stat()
                relative_path = path.relative_to(ldraw_dir).as_posix()
                metadata = (
                    f"{relative_path}\0{stat_result.st_size}\0"
                    f"{stat_result.st_mtime_ns}\n"
                )
                digest.update(metadata.encode())
    return digest.hexdigest()


def _stored_path(part: Part | None, library_root: Path) -> str | None:
    if part is None:
        return None
    path = Path(part.path)
    if path.is_relative_to(library_root):
        return str(path.relative_to(library_root))
    return str(path)


def _loaded_part(stored: str | None, library_root: Path) -> Part | None:
    if stored is None:
        return None
    path = Path(stored)
    return Part(path if path.is_absolute() else library_root / path)


def _entry_from_row(
    row: tuple[str, str, str, str | None, str | None, str],
    library_root: Path,
) -> CatalogEntry:
    code, description, category, minifig_section, stored, keywords = row
    return CatalogEntry(
        code=code,
        description=description,
        category=PartCategory(category),
        part=_loaded_part(stored, library_root),
        minifig_section=(
            MinifigSection(minifig_section) if minifig_section is not None else None
        ),
        keywords=tuple(keywords.split(_KEYWORDS_SEPARATOR)) if keywords else (),
    )


def _read_index_rows(
    db_path: Path,
    md5: str,
    tree_fingerprint: str,
) -> list[tuple[str, str, str, str | None, str | None, str]] | None:
    """Read all part rows from a fresh index, or None when it is unusable."""
    try:
        connection = sqlite3.connect(db_path)
    except sqlite3.Error:
        return None
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != CATALOG_SCHEMA_VERSION:
            return None
        stored_md5 = connection.execute(
            "SELECT value FROM meta WHERE key = 'parts_lst_md5'",
        ).fetchone()
        if stored_md5 is None or stored_md5[0] != md5:
            return None
        stored_tree = connection.execute(
            "SELECT value FROM meta WHERE key = 'tree_fingerprint'",
        ).fetchone()
        if stored_tree is None or stored_tree[0] != tree_fingerprint:
            return None
        return connection.execute(
            "SELECT code, description, category, minifig_section, path, keywords"
            " FROM parts ORDER BY rowid",
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def load_catalog(
    db_path: Path,
    *,
    md5: str,
    library_root: Path,
    tree_fingerprint: str,
) -> PartsCatalog | None:
    """Load a catalog from the index, or None when it cannot be trusted.

    A missing file, schema-version mismatch, stale ``parts.lst`` digest or
    tree fingerprint, corrupt database, or unknown category/section value
    all return None rather than raising, so callers can always fall back
    to a full build.
    """
    if not db_path.is_file():
        return None
    rows = _read_index_rows(
        db_path=db_path,
        md5=md5,
        tree_fingerprint=tree_fingerprint,
    )
    if rows is None:
        return None
    catalog = PartsCatalog()
    try:
        for row in rows:
            catalog.add(_entry_from_row(row, library_root))
    except ValueError:
        return None
    return catalog


def save_catalog(
    db_path: Path,
    *,
    md5: str,
    catalog: PartsCatalog,
    library_root: Path,
    tree_fingerprint: str,
) -> None:
    """Write the catalog to the index in a single transaction.

    Raises OSError or sqlite3.Error on failure; persisting is best-effort,
    so callers are expected to swallow those.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION}")
            connection.execute("DROP TABLE IF EXISTS meta")
            connection.execute("DROP TABLE IF EXISTS parts")
            connection.execute(_CREATE_META)
            connection.execute(_CREATE_PARTS)
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('parts_lst_md5', ?)",
                (md5,),
            )
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('tree_fingerprint', ?)",
                (tree_fingerprint,),
            )
            connection.executemany(
                "INSERT INTO parts (code, description, category, minifig_section,"
                " path, keywords) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        entry.code,
                        entry.description,
                        entry.category.value,
                        (
                            entry.minifig_section.value
                            if entry.minifig_section is not None
                            else None
                        ),
                        _stored_path(entry.part, library_root),
                        _KEYWORDS_SEPARATOR.join(entry.keywords),
                    )
                    for entry in catalog.by_code.values()
                ),
            )
    finally:
        connection.close()


def load_parts(
    parts_lst: str | Path,
    generated_path: str | Path,
    *,
    build_index: bool = False,
) -> Parts:
    """Load a Parts catalog, using the persistent index when it is fresh.

    With a fresh index this never runs the expensive categorization pass.
    Otherwise it returns a lazily-categorized ``Parts``; when
    ``build_index`` is true the catalog is materialized immediately and
    persisted (best-effort) for future runs — pass it from callers that
    will use the catalog anyway.
    """
    parts_lst_path = Path(parts_lst)
    md5 = parts_lst_md5(parts_lst_path)
    db_path = catalog_db_path(generated_path)
    library_root = parts_lst_path.parent
    tree = parts_tree_fingerprint(library_root)
    catalog = load_catalog(
        db_path,
        md5=md5,
        library_root=library_root,
        tree_fingerprint=tree,
    )
    parts = Parts.get(parts_lst_path)
    if catalog is not None:
        parts.adopt_catalog(catalog)
        return parts
    if build_index:
        try:
            save_catalog(
                db_path,
                md5=md5,
                catalog=parts.catalog,
                library_root=library_root,
                tree_fingerprint=tree,
            )
        except (OSError, sqlite3.Error):
            logger.debug("could not persist parts index to %s", db_path)
    return parts
