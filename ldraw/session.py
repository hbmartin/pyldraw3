"""Public session and setup helpers for configured LDraw data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING
from zipfile import BadZipFile

import requests

from ldraw.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogFingerprint,
    catalog_db_path,
    catalog_fingerprint,
    load_parts,
    save_catalog,
)
from ldraw.config import Config
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as download_library
from ldraw.errors import CouldNotDetermineLatestVersionError
from ldraw.generation import generate as generate_library
from ldraw.generation import (
    generated_library_path,
    generation_hash_path,
    library_fingerprint,
)
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.imports import LibraryImporter
from ldraw.model import ModelLoadResult, load_model, read_model
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.parts import Parts, PartsCatalog
from ldraw.progress import ProgressCallback, ProgressEvent, ProgressStage, emit_progress

if TYPE_CHECKING:
    from collections.abc import Iterable

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


class LDrawCapability(StrEnum):
    """Configured data capabilities a caller may require."""

    CATALOG = "catalog"
    GENERATED_MODULES = "generated-modules"


class CatalogBuildOutcome(StrEnum):
    """How a catalog preparation obtained its in-memory catalog."""

    UNAVAILABLE = "unavailable"
    LOADED = "loaded"
    REBUILT = "rebuilt"
    REBUILT_NOT_PERSISTED = "rebuilt-not-persisted"


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
    capabilities: frozenset[LDrawCapability] = frozenset(
        {LDrawCapability.CATALOG, LDrawCapability.GENERATED_MODULES}
    )

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


@dataclass(frozen=True, slots=True)
class CatalogBuildReport:
    """Index work and persistence performed by ``prepare_catalog``."""

    library_root: Path
    index_path: Path
    fingerprint: CatalogFingerprint | None
    entry_count: int
    outcome: CatalogBuildOutcome
    persisted: bool


@dataclass(frozen=True, slots=True)
class CatalogPreparationResult:
    """Parts plus before/after state and diagnostics from one preparation."""

    parts: Parts | None
    initial_state: LDrawState
    final_state: LDrawState
    report: CatalogBuildReport
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether usable parts were produced without an error diagnostic."""
        return self.parts is not None and not any(
            diagnostic.severity is Severity.ERROR for diagnostic in self.diagnostics
        )


class LDrawSession:
    """Manage one configured LDraw catalog and generated library."""

    __slots__ = ("config",)

    config: Config

    def __init__(self, config: Config | None = None) -> None:
        self.config = config if config is not None else Config.load()

    @property
    def paths(self) -> LDrawPaths:
        """Resolved paths for this session."""
        return LDrawPaths.from_config(self.config)

    def state(
        self,
        *,
        capabilities: Iterable[LDrawCapability] | None = None,
        fingerprint: CatalogFingerprint | None = None,
    ) -> LDrawState:
        """Classify only the configured capabilities requested by the caller."""
        required = frozenset(capabilities or tuple(LDrawCapability))
        paths = self.paths
        if not paths.parts_lst.is_file():
            return LDrawState(
                paths=paths,
                reasons=(LDrawStateReason.LIBRARY_MISSING,),
                capabilities=required,
            )

        snapshot = fingerprint or _session_fingerprint(
            paths,
            include_catalog=LDrawCapability.CATALOG in required,
            include_generation=LDrawCapability.GENERATED_MODULES in required,
        )

        reasons: list[LDrawStateReason] = []
        if (
            LDrawCapability.CATALOG in required
            and (index_reason := _catalog_index_reason(paths, snapshot)) is not None
        ):
            reasons.append(index_reason)
        if (
            LDrawCapability.GENERATED_MODULES in required
            and (
                generation_reason := _generation_reason(
                    paths,
                    expected_fingerprint=snapshot.generation_fingerprint,
                )
            )
            is not None
        ):
            reasons.append(generation_reason)
        return LDrawState(
            paths=paths,
            reasons=tuple(reasons),
            capabilities=required,
        )

    def load(self) -> Parts:
        """Load parts, building and persisting the catalog index when needed."""
        result = self.prepare_catalog()
        if result.parts is None:
            raise FileNotFoundError(self.paths.parts_lst)
        return result.parts

    def prepare_catalog(
        self,
        *,
        capabilities: Iterable[LDrawCapability] = (LDrawCapability.CATALOG,),
        force: bool = False,
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> CatalogPreparationResult:
        """Load or rebuild requested data using one filesystem fingerprint."""
        required = frozenset(capabilities)
        if not required:
            message = "at least one LDraw capability is required"
            raise ValueError(message)
        paths = self.paths
        if not paths.parts_lst.is_file():
            state = LDrawState(
                paths=paths,
                reasons=(LDrawStateReason.LIBRARY_MISSING,),
                capabilities=required,
            )
            diagnostic = Diagnostic(
                message=f"LDraw parts list not found: {paths.parts_lst}",
                code=DiagnosticCode.CATALOG_LIBRARY_MISSING,
                path=paths.parts_lst,
            )
            return CatalogPreparationResult(
                parts=None,
                initial_state=state,
                final_state=state,
                report=CatalogBuildReport(
                    library_root=paths.ldraw_path,
                    index_path=paths.catalog_db,
                    fingerprint=None,
                    entry_count=0,
                    outcome=CatalogBuildOutcome.UNAVAILABLE,
                    persisted=False,
                ),
                diagnostics=(diagnostic,),
            )

        check_cancelled(cancellation)
        snapshot = _session_fingerprint(
            paths,
            include_catalog=LDrawCapability.CATALOG in required,
            include_generation=LDrawCapability.GENERATED_MODULES in required,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        initial = self.state(capabilities=required, fingerprint=snapshot)
        diagnostics: list[Diagnostic] = []

        if LDrawCapability.GENERATED_MODULES in required and (
            force or initial.needs_generation
        ):
            try:
                generate_library(
                    config=self.config,
                    force=force,
                    on_progress=on_progress,
                    fingerprint=snapshot.generation_fingerprint,
                    cancellation=cancellation,
                )
            except (OSError, UnwritableOutputError) as error:
                diagnostics.append(
                    Diagnostic(
                        message=f"Could not generate ldraw.library: {error}",
                        code=DiagnosticCode.GENERATION_FAILED,
                        path=paths.generated_library,
                        cause=error,
                    ),
                )

        parts: Parts | None = None
        outcome = CatalogBuildOutcome.UNAVAILABLE
        persisted = False
        if LDrawCapability.CATALOG in required:
            paths.generated_path.mkdir(parents=True, exist_ok=True)
            needs_rebuild = force or initial.needs_index_rebuild
            if not needs_rebuild:
                parts = load_parts(
                    paths.parts_lst,
                    paths.generated_path,
                    fingerprint=snapshot,
                    on_progress=on_progress,
                    cancellation=cancellation,
                )
                outcome = CatalogBuildOutcome.LOADED
                persisted = True
            else:
                parts = Parts.get(paths.parts_lst)
                catalog = parts.build_catalog(
                    on_progress=on_progress,
                    cancellation=cancellation,
                )
                try:
                    _persist_catalog_atomically(
                        paths=paths,
                        parts=parts,
                        catalog=catalog,
                        fingerprint=snapshot,
                        on_progress=on_progress,
                        cancellation=cancellation,
                    )
                    outcome = CatalogBuildOutcome.REBUILT
                    persisted = True
                except (OSError, sqlite3.Error) as error:
                    outcome = CatalogBuildOutcome.REBUILT_NOT_PERSISTED
                    diagnostics.append(
                        Diagnostic(
                            message=f"Could not persist catalog index: {error}",
                            severity=Severity.WARNING,
                            code=DiagnosticCode.CATALOG_PERSIST_FAILED,
                            path=paths.catalog_db,
                            cause=error,
                        ),
                    )
        else:
            parts = Parts.get(paths.parts_lst)
            outcome = CatalogBuildOutcome.LOADED

        final = self.state(capabilities=required, fingerprint=snapshot)
        report = CatalogBuildReport(
            library_root=paths.ldraw_path,
            index_path=paths.catalog_db,
            fingerprint=snapshot,
            entry_count=(
                len(parts.catalog.by_code)
                if parts is not None and LDrawCapability.CATALOG in required
                else len(parts.by_code)
                if parts is not None
                else 0
            ),
            outcome=outcome,
            persisted=persisted,
        )
        emit_progress(
            on_progress,
            ProgressEvent(stage=ProgressStage.DONE, message="LDraw data is ready"),
        )
        return CatalogPreparationResult(
            parts=parts,
            initial_state=initial,
            final_state=final,
            report=report,
            diagnostics=tuple(diagnostics),
        )

    def rebuild_index(
        self,
        *,
        force: bool = True,
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
        fingerprint: CatalogFingerprint | None = None,
    ) -> Parts:
        """Rebuild the persistent catalog index and return the loaded parts."""
        paths = self.paths
        paths.generated_path.mkdir(parents=True, exist_ok=True)
        snapshot = fingerprint or _session_fingerprint(
            paths,
            include_catalog=True,
            include_generation=False,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        index_reason = _catalog_index_reason(paths, snapshot)
        if not force and index_reason is None:
            return load_parts(
                paths.parts_lst,
                paths.generated_path,
                fingerprint=snapshot,
                on_progress=on_progress,
                cancellation=cancellation,
            )
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.INDEX_REBUILD,
                message="Building parts catalog index",
                path=paths.catalog_db,
            ),
        )
        parts = Parts.get(paths.parts_lst)
        catalog = parts.build_catalog(
            on_progress=on_progress,
            cancellation=cancellation,
        )
        _persist_catalog_atomically(
            paths=paths,
            parts=parts,
            catalog=catalog,
            fingerprint=snapshot,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        return parts

    def open_model(self, path: Path | str) -> Model:
        """Read a ``.ldr`` or ``.mpd`` model file."""
        return read_model(path)

    def load_model(
        self,
        path: Path | str,
        parts: Parts | None = None,
        *,
        tolerant: bool = True,
    ) -> ModelLoadResult:
        """Read and validate a model into a structured load result."""
        return load_model(path, parts=parts, tolerant=tolerant)


def _session_fingerprint(
    paths: LDrawPaths,
    *,
    include_catalog: bool,
    include_generation: bool,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> CatalogFingerprint:
    if include_catalog:
        snapshot = catalog_fingerprint(
            paths.parts_lst,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        generation_fingerprint = (
            library_fingerprint(
                paths.parts_lst,
                parts_lst_digest=snapshot.parts_lst_md5,
                tree_fingerprint=snapshot.tree_fingerprint,
            )
            if include_generation
            else None
        )
    elif include_generation:
        generation_fingerprint = library_fingerprint(
            paths.parts_lst,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        lines = generation_fingerprint.splitlines()
        snapshot = CatalogFingerprint(
            parts_lst_md5=lines[1],
            tree_fingerprint=lines[3],
        )
    else:
        message = "at least one fingerprint capability is required"
        raise ValueError(message)
    return CatalogFingerprint(
        parts_lst_md5=snapshot.parts_lst_md5,
        tree_fingerprint=snapshot.tree_fingerprint,
        generation_fingerprint=generation_fingerprint,
    )


def _persist_catalog_atomically(  # noqa: PLR0913 - operation state is explicit
    *,
    paths: LDrawPaths,
    parts: Parts,
    catalog: PartsCatalog,
    fingerprint: CatalogFingerprint,
    on_progress: ProgressCallback | None,
    cancellation: CancellationToken | None,
) -> None:
    with NamedTemporaryFile(
        dir=paths.catalog_db.parent,
        prefix=f".{paths.catalog_db.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_db = Path(temp_file.name)
    try:
        save_catalog(
            temp_db,
            md5=fingerprint.parts_lst_md5,
            catalog=catalog,
            library_root=parts.library_root,
            tree_fingerprint=fingerprint.tree_fingerprint,
            on_progress=on_progress,
            cancellation=cancellation,
        )
        check_cancelled(cancellation)
        temp_db.replace(paths.catalog_db)
    finally:
        temp_db.unlink(missing_ok=True)


def _catalog_index_reason(
    paths: LDrawPaths,
    fingerprint: CatalogFingerprint | None = None,
) -> LDrawStateReason | None:
    if not paths.catalog_db.is_file():
        return LDrawStateReason.INDEX_MISSING
    snapshot = fingerprint or _session_fingerprint(
        paths,
        include_catalog=True,
        include_generation=False,
    )
    try:
        connection = sqlite3.connect(
            f"{paths.catalog_db.resolve().as_uri()}?mode=ro",
            uri=True,
        )
    except sqlite3.Error:
        return LDrawStateReason.INDEX_UNREADABLE
    meta_checks = (
        (
            "SELECT value FROM meta WHERE key = 'parts_lst_md5'",
            snapshot.parts_lst_md5,
        ),
        (
            "SELECT value FROM meta WHERE key = 'tree_fingerprint'",
            snapshot.tree_fingerprint,
        ),
    )
    try:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if version != CATALOG_SCHEMA_VERSION:
            return LDrawStateReason.INDEX_STALE
        for statement, expected_value in meta_checks:
            row = connection.execute(statement).fetchone()
            if row is None or row[0] != expected_value:
                return LDrawStateReason.INDEX_STALE
    except (OSError, sqlite3.Error):
        return LDrawStateReason.INDEX_UNREADABLE
    finally:
        connection.close()
    return None


def _generation_reason(
    paths: LDrawPaths,
    *,
    expected_fingerprint: str | None = None,
) -> LDrawStateReason | None:
    if not paths.generated_library.is_dir() or not paths.generation_hash.is_file():
        return LDrawStateReason.GENERATED_LIBRARY_MISSING
    try:
        expected = expected_fingerprint or library_fingerprint(paths.parts_lst)
        if paths.generation_hash.read_text() != expected:
            return LDrawStateReason.GENERATED_LIBRARY_STALE
    except OSError:
        return LDrawStateReason.GENERATED_LIBRARY_UNREADABLE
    return None


def prepare_catalog(
    config: Config | None = None,
    *,
    capabilities: Iterable[LDrawCapability] = (LDrawCapability.CATALOG,),
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> CatalogPreparationResult:
    """Prepare requested configured data and return a structured report."""
    return LDrawSession(config).prepare_catalog(
        capabilities=capabilities,
        force=force,
        on_progress=on_progress,
        cancellation=cancellation,
    )


def ensure_library(  # noqa: PLR0913 - public setup helper mirrors setup choices
    config: Config | None = None,
    *,
    version: str = COMPLETE_VERSION,
    write_config: bool = False,
    config_file: str | Path | None = None,
    force_generate: bool = False,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> LDrawSession:
    """Ensure a configured library, generated package, and catalog index exist.

    When the library is downloaded, ``config.ldraw_library_path`` is
    updated in place on the caller's Config (persisted only when
    ``write_config`` is true), and the process-global default import
    configuration is replaced via ``LibraryImporter.set_config``.
    """
    cfg = Config.load(config_file) if config is None else config
    session = LDrawSession(cfg)
    state = session.state(capabilities=(LDrawCapability.CATALOG,))

    if LDrawStateReason.LIBRARY_MISSING in state.reasons:
        try:
            download_library(
                version=version,
                show_progress=False,
                on_progress=on_progress,
                resume=True,
                cancellation=cancellation,
            )
        except (
            requests.RequestException,
            ValueError,
            BadZipFile,
            CouldNotDetermineLatestVersionError,
            OSError,
        ) as exc:
            message = f"Could not download LDraw library: {exc}"
            raise RuntimeError(message) from exc
        cfg.ldraw_library_path = str(cache_ldraw / version)
        session = LDrawSession(cfg)

    if force_generate:
        try:
            generate_library(
                config=cfg,
                force=True,
                on_progress=on_progress,
                cancellation=cancellation,
            )
        except UnwritableOutputError as exc:
            message = f"Generated library path is unwritable: {cfg.generated_path}"
            raise RuntimeError(message) from exc

    result = session.prepare_catalog(
        capabilities=(
            LDrawCapability.CATALOG,
            LDrawCapability.GENERATED_MODULES,
        ),
        on_progress=on_progress,
        cancellation=cancellation,
    )
    if result.parts is None:
        message = (
            result.diagnostics[0].message if result.diagnostics else "unknown error"
        )
        raise RuntimeError(message)
    if (
        failure := next(
            (
                diagnostic
                for diagnostic in result.diagnostics
                if diagnostic.severity is Severity.ERROR
            ),
            None,
        )
    ) is not None:
        raise RuntimeError(failure.message) from failure.cause

    LibraryImporter.set_config(cfg)
    if write_config:
        cfg.write(config_file=config_file)
    return session
