"""Library discovery, inspection, and non-mutating download planning."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ldraw.config import Config
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.dirs import get_cache_dir
from ldraw.download_updates import get_latest_release_id
from ldraw.downloads import ARCHIVE_URL, COMPLETE_VERSION, LDRAW_URL, VERSION_RE
from ldraw.errors import CouldNotDetermineLatestVersionError
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    ProgressUnit,
    emit_progress,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_REQUEST_TIMEOUT_SECONDS = 30
_REQUIRED_COMPONENTS = ("parts", "p", "parts.lst", "ldconfig.ldr")


@dataclass(frozen=True, slots=True)
class LibraryComponent:
    """Presence and basic readability of one expected library component."""

    name: str
    path: Path
    present: bool
    valid: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryInspection:
    """Non-mutating inspection of a possible LDraw installation."""

    path: Path
    ldraw_path: Path
    release: str | None
    components: tuple[LibraryComponent, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def valid(self) -> bool:
        """Return whether every required component is present and usable."""
        return all(component.valid for component in self.components)

    @property
    def missing_components(self) -> tuple[str, ...]:
        """Return names of components that were not found."""
        return tuple(
            component.name for component in self.components if not component.present
        )

    @property
    def corrupt_components(self) -> tuple[str, ...]:
        """Return names of present components that failed validation."""
        return tuple(
            component.name
            for component in self.components
            if component.present and not component.valid
        )


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """Network and local-cache facts for a prospective library download."""

    version: str
    release: str | None
    url: str
    archive_path: Path
    destination: Path
    download_size: int | None
    cached_bytes: int
    resumable: bool
    cached_archive_valid: bool | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def remaining_bytes(self) -> int | None:
        """Return the expected remaining transfer size when known."""
        if self.download_size is None:
            return None
        return max(self.download_size - self.cached_bytes, 0)


def _ldraw_path(path: Path) -> tuple[Path, Path]:
    """Return (installation root, ldraw data directory) for either form."""
    expanded = path.expanduser()
    if (expanded / "parts.lst").is_file() or expanded.name.casefold() == "ldraw":
        return expanded.parent, expanded
    return expanded, expanded / "ldraw"


def inspect_library(path: str | Path) -> LibraryInspection:
    """Inspect a candidate installation without building its catalog."""
    root, ldraw_path = _ldraw_path(Path(path))
    components: list[LibraryComponent] = []
    diagnostics: list[Diagnostic] = []
    for name in _REQUIRED_COMPONENTS:
        component_path = ldraw_path / name
        expects_directory = name in {"parts", "p"}
        present = component_path.exists()
        valid = (
            component_path.is_dir() if expects_directory else component_path.is_file()
        )
        detail = None
        if valid and not expects_directory:
            try:
                with component_path.open("rb") as handle:
                    handle.read(1)
            except OSError as exc:
                valid = False
                detail = str(exc)
        if not valid:
            state = "missing" if not present else "unusable"
            detail = detail or state
            diagnostics.append(
                Diagnostic(
                    line_number=None,
                    message=f"Library component {name} is {state}",
                    severity=Severity.ERROR,
                    code=DiagnosticCode.DISCOVERY_INVALID_LIBRARY,
                    path=component_path,
                    offending_value=name,
                ),
            )
        components.append(
            LibraryComponent(
                name=name,
                path=component_path,
                present=present,
                valid=valid,
                detail=detail,
            ),
        )
    release_path = ldraw_path / "_release.txt"
    try:
        release = release_path.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        release = None
    return LibraryInspection(
        path=root,
        ldraw_path=ldraw_path,
        release=release,
        components=tuple(components),
        diagnostics=tuple(diagnostics),
    )


def discover_libraries(
    paths: Iterable[str | Path] | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> tuple[LibraryInspection, ...]:
    """Discover valid and partial installations in configured/common locations."""
    candidates: list[Path] = []
    if paths is not None:
        candidates.extend(Path(path) for path in paths)
    else:
        candidates.append(Path(Config.load().ldraw_library_path))
        cache = Path(get_cache_dir())
        if cache.is_dir():
            candidates.extend(path for path in cache.iterdir() if path.is_dir())
        candidates.extend(
            (
                Path("/Applications/LDView.app/Contents/Resources/ldraw"),
                Path("/Applications/LeoCAD.app/Contents/Resources/ldraw"),
                Path("/usr/share/ldraw"),
                Path("/usr/local/share/ldraw"),
            ),
        )
    unique = tuple(dict.fromkeys(path.expanduser() for path in candidates))
    total = len(unique)
    emit_progress(
        on_progress,
        ProgressEvent(
            stage=ProgressStage.LIBRARY_DISCOVERY,
            message="Discovering LDraw libraries",
            current=0,
            total=total,
            unit=ProgressUnit.FILES,
        ),
    )
    inspections: list[LibraryInspection] = []
    for current, candidate in enumerate(unique, start=1):
        check_cancelled(cancellation)
        inspection = inspect_library(candidate)
        if inspection.ldraw_path.exists():
            inspections.append(inspection)
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.LIBRARY_DISCOVERY,
                message="Discovering LDraw libraries",
                current=current,
                total=total,
                path=candidate,
                unit=ProgressUnit.FILES,
            ),
        )
    return tuple(
        sorted(
            inspections,
            key=lambda inspection: (
                not inspection.valid,
                str(inspection.path).casefold(),
            ),
        ),
    )


def plan_download(
    version: str = COMPLETE_VERSION,
    *,
    cache_path: str | Path | None = None,
    cancellation: CancellationToken | None = None,
) -> DownloadPlan:
    """Inspect remote size/resume support and local archive integrity."""
    if version != COMPLETE_VERSION and not VERSION_RE.fullmatch(version):
        message = f"Unsupported LDraw library version: {version!r}"
        raise ValueError(message)
    check_cancelled(cancellation)
    filename = f"{version}.zip"
    url = (
        f"{LDRAW_URL}/{filename}"
        if version == COMPLETE_VERSION
        else f"{ARCHIVE_URL}/{filename}"
    )
    cache = Path(cache_path) if cache_path is not None else Path(get_cache_dir())
    archive_path = cache / filename
    partial_path = archive_path.with_name(f"{archive_path.name}.part")
    cached_bytes = partial_path.stat().st_size if partial_path.is_file() else 0
    archive_valid: bool | None = None
    diagnostics: list[Diagnostic] = []
    if archive_path.is_file():
        try:
            with zipfile.ZipFile(archive_path) as archive:
                bad_member = archive.testzip()
                archive_valid = bad_member is None
                if bad_member is not None:
                    diagnostics.append(
                        Diagnostic(
                            line_number=None,
                            message=f"Corrupt cached archive member: {bad_member}",
                            severity=Severity.ERROR,
                            code=DiagnosticCode.DOWNLOAD_INTEGRITY_FAILED,
                            path=archive_path,
                            offending_value=bad_member,
                        ),
                    )
        except (OSError, zipfile.BadZipFile) as exc:
            archive_valid = False
            diagnostics.append(
                Diagnostic(
                    line_number=None,
                    message=f"Cached archive is corrupt: {exc}",
                    severity=Severity.ERROR,
                    code=DiagnosticCode.DOWNLOAD_INTEGRITY_FAILED,
                    path=archive_path,
                    cause=exc,
                ),
            )
    size: int | None = None
    resumable = False
    release = version if version != COMPLETE_VERSION else None
    try:
        response = requests.head(
            url=url,
            allow_redirects=True,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if raw_size := response.headers.get("content-length"):
            size = int(raw_size)
        resumable = "bytes" in response.headers.get("accept-ranges", "").casefold()
    except (OSError, ValueError, requests.RequestException) as exc:
        diagnostics.append(
            Diagnostic(
                line_number=None,
                message=f"Could not inspect download: {exc}",
                severity=Severity.WARNING,
                code=DiagnosticCode.DOWNLOAD_PLAN_FAILED,
                path=archive_path,
                cause=exc,
            ),
        )
    if version == COMPLETE_VERSION:
        check_cancelled(cancellation)
        try:
            release = get_latest_release_id()
        except (
            CouldNotDetermineLatestVersionError,
            OSError,
            ValueError,
            requests.RequestException,
        ) as exc:
            diagnostics.append(
                Diagnostic(
                    line_number=None,
                    message=f"Could not determine current release: {exc}",
                    severity=Severity.WARNING,
                    code=DiagnosticCode.DOWNLOAD_PLAN_FAILED,
                    path=archive_path,
                    cause=exc,
                ),
            )
    check_cancelled(cancellation)
    return DownloadPlan(
        version=version,
        release=release,
        url=url,
        archive_path=archive_path,
        destination=cache / version,
        download_size=size,
        cached_bytes=cached_bytes,
        resumable=resumable,
        cached_archive_valid=archive_valid,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "DownloadPlan",
    "LibraryComponent",
    "LibraryInspection",
    "discover_libraries",
    "inspect_library",
    "plan_download",
]
