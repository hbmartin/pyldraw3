"""Read-only diagnosis of selection, capabilities, caches, and renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ldraw.catalog import catalog_db_path
from ldraw.catalog_search import fts5_available
from ldraw.diagnostics import Diagnostic, Severity
from ldraw.library_access import index_directory, select_library
from ldraw.library_setup import inspect_library
from ldraw.rendering import render_capabilities

if TYPE_CHECKING:
    from pathlib import Path

    from ldraw.config import Config
    from ldraw.library_access import LibrarySelection


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Facts gathered without downloads, cache creation, or repairs."""

    selection: LibrarySelection | None
    capabilities: dict[str, bool]
    cache: dict[str, str | bool]
    fts5: bool
    renderers: dict[str, str | None]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready diagnostic report."""
        return {
            "selection": {
                "directory": str(self.selection.directory),
                "source": self.selection.source,
            }
            if self.selection
            else None,
            "capabilities": self.capabilities,
            "cache": self.cache,
            "fts5": self.fts5,
            "renderers": self.renderers,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def doctor(
    config: Config | None = None, *, library: str | Path | None = None
) -> DoctorReport:
    """Inspect library and tool availability without repairing anything."""
    diagnostics: list[Diagnostic] = []
    selection = None
    capabilities: dict[str, bool] = {}
    cache: dict[str, str | bool] = {}
    try:
        selection = select_library(config, library=library)
    except (OSError, ValueError) as error:
        diagnostics.append(
            Diagnostic(
                code="discovery.selection_failed",
                severity=Severity.WARNING,
                message=str(error),
            )
        )
    if selection is not None:
        inspection = inspect_library(selection.directory)
        capabilities = {
            component.name: component.valid for component in inspection.components
        }
        capabilities["geometry"] = capabilities.get(
            "parts", False
        ) and capabilities.get("p", False)
        db = (
            catalog_db_path(config.generated_path)
            if config is not None and capabilities.get("parts.lst")
            else index_directory(selection.directory) / "catalog.sqlite"
        )
        cache = {"path": str(db), "present": db.is_file()}
        cache["state"] = _cache_state(db=db, directory=selection.directory)
    renderers = {
        item.backend.value: str(item.executable) if item.executable else None
        for item in render_capabilities()
    }
    return DoctorReport(
        selection=selection,
        capabilities=capabilities,
        cache=cache,
        fts5=fts5_available(),
        renderers=renderers,
        diagnostics=tuple(diagnostics),
    )


def _cache_state(*, db: Path, directory: Path) -> str:
    from ldraw.catalog import (  # noqa: PLC0415
        load_catalog,
        parts_lst_md5,
        parts_tree_fingerprint,
    )

    parts_list = directory / "parts.lst"
    if not parts_list.is_file():
        parts_list = db.parent / "parts.lst"
    if not db.is_file() or not parts_list.is_file():
        return "unprepared"
    try:
        cached = load_catalog(
            db,
            md5=parts_lst_md5(parts_list),
            library_root=directory,
            tree_fingerprint=parts_tree_fingerprint(directory),
        )
    except OSError:
        return "unreadable"
    return "ready" if cached is not None else "stale-or-unreadable"
