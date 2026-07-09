"""Public session and setup helpers for configured LDraw data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import BadZipFile

import requests

from ldraw.catalog import (
    CATALOG_SCHEMA_VERSION,
    catalog_db_path,
    load_parts,
    parts_lst_md5,
    save_catalog,
)
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as download_library
from ldraw.generation import generate as generate_library
from ldraw.generation import (
    generated_library_path,
    generation_hash_path,
    library_fingerprint,
)
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.imports import LibraryImporter
from ldraw.model import read_model
from ldraw.parts import Parts
from ldraw.progress import ProgressCallback, ProgressEvent, ProgressStage, emit_progress

if TYPE_CHECKING:
    from ldraw.model import Model


class LDrawStateReason(StrEnum):
    """Reasons the configured LDraw data is not fully ready."""

    LIBRARY_MISSING = "library-missing"
    INDEX_MISSING = "index-missing"
    INDEX_STALE = "index-stale"
    INDEX_UNREADABLE = "index-unreadable"
    GENERATED_LIBRARY_MISSING = "generated-library-missing"
    GENERATED_LIBRARY_STALE = "generated-library-stale"
    GENERATED_LIBRARY_UNREADABLE = "generated-library-unreadable"


@dataclass(frozen=True, slots=True)
class LDrawPaths:
    """Resolved filesystem paths for one pyldraw configuration."""

    library_path: Path
    ldraw_path: Path
    parts_lst: Path
    generated_path: Path
    generated_library: Path
    generation_hash: Path
    catalog_db: Path

    @classmethod
    def from_config(cls, config: Config) -> LDrawPaths:
        """Resolve paths from ``config``."""
        library_path = Path(config.ldraw_library_path)
        generated_path = Path(config.generated_path)
        return cls(
            library_path=library_path,
            ldraw_path=library_path / "ldraw",
            parts_lst=library_path / "ldraw" / "parts.lst",
            generated_path=generated_path,
            generated_library=generated_library_path(generated_path),
            generation_hash=generation_hash_path(generated_path),
            catalog_db=catalog_db_path(generated_path),
        )


@dataclass(frozen=True, slots=True)
class LDrawState:
    """Freshness state for a configured LDraw library and generated data."""

    paths: LDrawPaths
    reasons: tuple[LDrawStateReason, ...]

    @property
    def ready(self) -> bool:
        """Whether the catalog index and generated library are fresh."""
        return not self.reasons

    @property
    def library_available(self) -> bool:
        """Whether ``parts.lst`` exists and catalog loading can start."""
        return LDrawStateReason.LIBRARY_MISSING not in self.reasons

    @property
    def needs_index_rebuild(self) -> bool:
        """Whether loading will need the slow catalog categorization pass."""
        return any(
            reason
            in {
                LDrawStateReason.INDEX_MISSING,
                LDrawStateReason.INDEX_STALE,
                LDrawStateReason.INDEX_UNREADABLE,
            }
            for reason in self.reasons
        )

    @property
    def needs_generation(self) -> bool:
        """Whether ``ldraw.library`` should be generated or refreshed."""
        return any(
            reason
            in {
                LDrawStateReason.GENERATED_LIBRARY_MISSING,
                LDrawStateReason.GENERATED_LIBRARY_STALE,
                LDrawStateReason.GENERATED_LIBRARY_UNREADABLE,
            }
            for reason in self.reasons
        )


@dataclass(slots=True)
class LDrawSession:
    """Manage one configured LDraw catalog and generated library."""

    config: Config

    def __init__(self, config: Config | None = None) -> None:
        self.config = config if config is not None else Config.load()

    @property
    def paths(self) -> LDrawPaths:
        """Resolved paths for this session."""
        return LDrawPaths.from_config(self.config)

    def state(self) -> LDrawState:
        """Classify the configured library, catalog index, and generated package."""
        paths = self.paths
        if not paths.parts_lst.is_file():
            return LDrawState(
                paths=paths,
                reasons=(LDrawStateReason.LIBRARY_MISSING,),
            )

        reasons: list[LDrawStateReason] = []
        if (index_reason := _catalog_index_reason(paths)) is not None:
            reasons.append(index_reason)
        if (generation_reason := _generation_reason(paths)) is not None:
            reasons.append(generation_reason)
        return LDrawState(paths=paths, reasons=tuple(reasons))

    def load(self) -> Parts:
        """Load parts, building and persisting the catalog index when needed."""
        self.paths.generated_path.mkdir(parents=True, exist_ok=True)
        return load_parts(
            self.paths.parts_lst,
            self.paths.generated_path,
            build_index=True,
        )

    def rebuild_index(
        self,
        *,
        force: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> Parts:
        """Rebuild the persistent catalog index and return the loaded parts."""
        paths = self.paths
        paths.generated_path.mkdir(parents=True, exist_ok=True)
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.INDEX_REBUILD,
                message="Building parts catalog index",
                path=paths.catalog_db,
            ),
        )
        index_reason = _catalog_index_reason(paths)
        if not force and index_reason is None:
            return load_parts(paths.parts_lst, paths.generated_path)
        if paths.catalog_db.exists() and (
            force or index_reason is LDrawStateReason.INDEX_UNREADABLE
        ):
            paths.catalog_db.unlink()
        parts = Parts.get(paths.parts_lst)
        save_catalog(
            paths.catalog_db,
            md5=parts_lst_md5(paths.parts_lst),
            catalog=parts.catalog,
            library_root=paths.parts_lst.parent,
        )
        return parts

    def open_model(self, path: Path | str) -> Model:
        """Read a ``.ldr`` or ``.mpd`` model file."""
        return read_model(path)


def _catalog_index_reason(paths: LDrawPaths) -> LDrawStateReason | None:
    if not paths.catalog_db.is_file():
        return LDrawStateReason.INDEX_MISSING
    try:
        connection = sqlite3.connect(f"file:{paths.catalog_db}?mode=ro", uri=True)
    except sqlite3.Error:
        return LDrawStateReason.INDEX_UNREADABLE
    try:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if version != CATALOG_SCHEMA_VERSION:
            return LDrawStateReason.INDEX_STALE
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'parts_lst_md5'",
        ).fetchone()
        if row is None or row[0] != parts_lst_md5(paths.parts_lst):
            return LDrawStateReason.INDEX_STALE
    except (OSError, sqlite3.Error):
        return LDrawStateReason.INDEX_UNREADABLE
    finally:
        connection.close()
    return None


def _generation_reason(paths: LDrawPaths) -> LDrawStateReason | None:
    if not paths.generated_library.is_dir() or not paths.generation_hash.is_file():
        return LDrawStateReason.GENERATED_LIBRARY_MISSING
    try:
        if paths.generation_hash.read_text() != library_fingerprint(paths.parts_lst):
            return LDrawStateReason.GENERATED_LIBRARY_STALE
    except OSError:
        return LDrawStateReason.GENERATED_LIBRARY_UNREADABLE
    return None


def ensure_library(  # noqa: PLR0913 - public setup helper mirrors setup choices
    config: Config | None = None,
    *,
    version: str = COMPLETE_VERSION,
    write_config: bool = False,
    config_file: str | Path | None = None,
    force_generate: bool = False,
    on_progress: ProgressCallback | None = None,
) -> LDrawSession:
    """Ensure a configured library, generated package, and catalog index exist."""
    cfg = Config.load(config_file) if config is None else config
    session = LDrawSession(cfg)
    state = session.state()

    if LDrawStateReason.LIBRARY_MISSING in state.reasons:
        try:
            download_library(
                version=version,
                show_progress=False,
                on_progress=on_progress,
            )
        except (requests.RequestException, ValueError, BadZipFile) as exc:
            message = f"Could not download LDraw library: {exc}"
            raise RuntimeError(message) from exc
        cfg.ldraw_library_path = str(cache_ldraw / version)
        session = LDrawSession(cfg)
        state = session.state()

    if force_generate or state.needs_generation:
        try:
            generate_library(
                config=cfg,
                force=force_generate,
                on_progress=on_progress,
            )
        except UnwritableOutputError as exc:
            message = f"Generated library path is unwritable: {cfg.generated_path}"
            raise RuntimeError(message) from exc
        session = LDrawSession(cfg)
        state = session.state()

    if state.needs_index_rebuild:
        session.rebuild_index(force=False, on_progress=on_progress)

    LibraryImporter.set_config(cfg)
    if write_config:
        cfg.write(config_file=config_file)
    emit_progress(
        on_progress,
        ProgressEvent(stage=ProgressStage.DONE, message="LDraw library is ready"),
    )
    return session
