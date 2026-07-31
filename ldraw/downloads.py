"""LDraw library file download and extraction functionality."""

import logging
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import requests
from progress.bar import Bar

from ldraw.dirs import get_cache_dir
from ldraw.download_updates import get_latest_release_id
from ldraw.generate import generate_parts_lst
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    ProgressUnit,
    emit_progress,
)

logger = logging.getLogger(__name__)

COMPLETE_VERSION = "complete"
LDRAW_URL = "https://library.ldraw.org/library/updates"
ARCHIVE_URL = "https://github.com/rienafairefr/ldraw-parts/archive/refs/tags"
VERSION_RE = re.compile(r"^\d{4}-\d{2}$")
cache_ldraw = Path(get_cache_dir())

# Minimum byte delta between throttled download progress events.
_PROGRESS_BYTE_STEP = 1_048_576

_REQUEST_TIMEOUT_SECONDS = 30


def _validate_version(version: str) -> None:
    if version != COMPLETE_VERSION and not VERSION_RE.fullmatch(version):
        message = f"Unsupported LDraw library version: {version!r}"
        raise ValueError(message)


def _temporary_rename_path(path: Path) -> Path:
    for index in range(10_000):
        suffix = "__pyldraw_tmp__" if index == 0 else f"__pyldraw_tmp_{index}__"
        candidate = path.with_name(f"{path.name}{suffix}")
        if not candidate.exists():
            return candidate
    message = f"No temporary rename path available for {path}"
    raise FileExistsError(message)


def _case_safe_rename(path: Path, destination: Path) -> Path:
    temp_path = _temporary_rename_path(path)
    path.rename(temp_path)
    try:
        return temp_path.rename(destination)
    except OSError:
        temp_path.rename(path)
        raise


def _is_unsafe_zip_member(filename: str) -> bool:
    posix_path = PurePosixPath(filename)
    windows_path = PureWindowsPath(filename)
    return (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    )


def _validate_zip_members(zip_ref: zipfile.ZipFile, destination: Path) -> None:
    destination_root = destination.resolve()
    for member in zip_ref.infolist():
        message = f"Unsafe ZIP member path: {member.filename!r}"
        if _is_unsafe_zip_member(member.filename):
            raise ValueError(message)
        target = (destination / member.filename).resolve()
        try:
            target.relative_to(destination_root)
        except ValueError as exc:
            raise ValueError(message) from exc


def _normalize_tree(destination: Path) -> None:
    """Normalize an unpacked library to the lowercase `ldraw/parts` layout.

    GitHub tag archives wrap everything in a `ldraw-parts-<tag>` directory and
    use uppercase entry names (`LDRAW/PARTS`), while the rest of the code
    expects the lowercase `ldraw/parts` layout that complete.zip uses.
    """
    if not destination.is_dir():
        return
    _unwrap_archive_wrapper(destination)

    ldraw_dir = next(
        (
            child
            for child in destination.iterdir()
            if child.name.lower() == "ldraw" and child.is_dir()
        ),
        None,
    )
    if ldraw_dir is None:
        return
    if ldraw_dir.name != "ldraw":
        ldraw_dir = _case_safe_rename(ldraw_dir, destination / "ldraw")
    _lowercase_tree(ldraw_dir)


def _unwrap_archive_wrapper(destination: Path) -> None:
    """Hoist a ``ldraw-parts-<tag>`` wrapper's content into ``destination``.

    A wrapper can coexist with a stale, previously normalized tree after a
    failed run; the fresh archive content replaces stale siblings.
    """
    wrapper = next(
        (
            child
            for child in destination.iterdir()
            if child.is_dir() and child.name.lower().startswith("ldraw-parts-")
        ),
        None,
    )
    if wrapper is None:
        return
    entries = list(wrapper.iterdir())
    by_lower: dict[str, str] = {}
    for entry in entries:
        lower_name = entry.name.lower()
        if (clashing := by_lower.get(lower_name)) is not None:
            message = (
                f"Case-colliding wrapper entries {clashing!r} and {entry.name!r}"
                f" in {wrapper}; cannot unwrap the LDraw archive"
            )
            raise ValueError(message)
        by_lower[lower_name] = entry.name

    for entry in entries:
        for existing in destination.iterdir():
            if existing != wrapper and existing.name.lower() == entry.name.lower():
                if existing.is_dir():
                    shutil.rmtree(existing)
                else:
                    existing.unlink()
        entry.rename(destination / entry.name)
    wrapper.rmdir()


def _lowercase_tree(ldraw_dir: Path) -> None:
    """Lowercase every entry under ``ldraw_dir``, refusing case collisions."""
    for dirpath, dirnames, filenames in ldraw_dir.walk(top_down=False):
        names = filenames + dirnames
        by_lower: dict[str, str] = {}
        for name in names:
            lower_name = name.lower()
            if (clashing := by_lower.get(lower_name)) is not None:
                message = (
                    f"Case-colliding entries {clashing!r} and {name!r} in {dirpath};"
                    " cannot normalize the LDraw tree"
                )
                raise ValueError(message)
            by_lower[lower_name] = name
        for name in names:
            lower_name = name.lower()
            if name != lower_name:
                _case_safe_rename(dirpath / name, dirpath / lower_name)


def unpack_version(
    version_zip: Path,
    version: str,
    *,
    show_progress: bool = True,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Unpack a downloaded LDraw library ZIP file to the cache directory."""
    _validate_version(version)
    if show_progress:
        print(f"Unzipping {version_zip}...")
    destination = cache_ldraw / version
    emit_progress(
        on_progress,
        ProgressEvent(
            stage=ProgressStage.UNPACK,
            message=f"Unpacking {version_zip.name}",
            path=destination,
        ),
    )
    with zipfile.ZipFile(version_zip, "r") as zip_ref:
        destination.mkdir(parents=True, exist_ok=True)
        _validate_zip_members(zip_ref, destination)
        members = zip_ref.infolist()
        total = len(members)
        for current, member in enumerate(members, start=1):
            check_cancelled(cancellation)
            zip_ref.extract(member, destination)
            emit_progress(
                on_progress,
                ProgressEvent(
                    stage=ProgressStage.UNPACK,
                    message=f"Unpacking {version_zip.name}",
                    current=current,
                    total=total,
                    path=destination,
                    unit=ProgressUnit.FILES,
                ),
            )
    version_zip.unlink()
    _normalize_tree(destination)

    return destination


def _download(  # noqa: PLR0913 - streaming state and controls are explicit
    url: str,
    filename: str,
    chunk_size: int = 1_024,
    *,
    show_progress: bool = False,
    on_progress: ProgressCallback | None = None,
    resume: bool = False,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Download ``url`` to ``filename`` in the cache, streaming via a ``.part`` file.

    The body is written to a sibling ``.part`` file and renamed into place only
    once it is fully received, so an interrupted download is never cached as a
    complete file.
    """
    cache_ldraw.mkdir(parents=True, exist_ok=True)
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        if show_progress:
            print(f"File {retrieved} already exists")
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.DOWNLOAD,
                message=f"Using cached {filename}",
                path=retrieved,
            ),
        )
        return retrieved

    partial = retrieved.with_name(f"{retrieved.name}.part")
    offset = partial.stat().st_size if resume and partial.is_file() else 0
    request_headers = {"Range": f"bytes={offset}-"} if offset else None
    with requests.get(
        url=url,
        stream=True,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        headers=request_headers,
    ) as response:
        response.raise_for_status()
        accepted_resume = offset > 0 and response.status_code == 206
        if offset and not accepted_resume:
            offset = 0
        remaining = int(response.headers.get("content-length", 0))
        total = remaining + offset if accepted_resume else remaining
        _stream_download(
            response=response,
            partial=partial,
            retrieved=retrieved,
            url=url,
            filename=filename,
            chunk_size=chunk_size,
            show_progress=show_progress,
            on_progress=on_progress,
            resume=resume,
            accepted_resume=accepted_resume,
            offset=offset,
            total=total,
            cancellation=cancellation,
        )
    partial.replace(retrieved)
    return retrieved


def _stream_download(  # noqa: PLR0913 - transfer state is explicit
    *,
    response: requests.Response,
    partial: Path,
    retrieved: Path,
    url: str,
    filename: str,
    chunk_size: int,
    show_progress: bool,
    on_progress: ProgressCallback | None,
    resume: bool,
    accepted_resume: bool,
    offset: int,
    total: int,
    cancellation: CancellationToken | None,
) -> None:
    message = f"Downloading {filename}"

    # Only build events when a callback is registered, and throttle so a
    # multi-megabyte stream does not flood the consumer with one event per
    # 1 KiB chunk. The start and final byte counts are always emitted.
    last_emitted = -1

    def emit_download(current: int, *, force: bool = False) -> None:
        nonlocal last_emitted
        if on_progress is None:
            return
        if not force and current - last_emitted < _PROGRESS_BYTE_STEP:
            return
        last_emitted = current
        on_progress(
            ProgressEvent(
                stage=ProgressStage.DOWNLOAD,
                message=message,
                current=current,
                total=total or None,
                path=retrieved,
                unit=ProgressUnit.BYTES,
            ),
        )

    emit_download(offset, force=True)
    try:
        with partial.open("ab" if accepted_resume else "wb") as file:
            bar = Bar(f"Downloading {url} ...", max=total) if show_progress else None
            current = offset
            for data in response.iter_content(chunk_size=chunk_size):
                check_cancelled(cancellation)
                written = file.write(data)
                current += written
                if bar is not None:
                    bar.next(written)
                emit_download(current)
            if bar is not None:
                bar.finish()
            emit_download(current, force=True)
    except BaseException:
        if not resume:
            partial.unlink(missing_ok=True)
        raise


def download(
    *,
    show_progress: bool = True,
    version: str = COMPLETE_VERSION,
    on_progress: ProgressCallback | None = None,
    resume: bool = False,
    cancellation: CancellationToken | None = None,
) -> str:
    """Download and unpack an LDraw library version, generating parts.lst file.

    The complete library comes from ldraw.org; versioned releases come from
    snapshot tags of the rienafairefr/ldraw-parts GitHub repository.
    """
    _validate_version(version)
    filename = f"{version}.zip"
    url = (
        f"{LDRAW_URL}/{filename}"
        if version == COMPLETE_VERSION
        else f"{ARCHIVE_URL}/{filename}"
    )
    cache_ldraw.mkdir(parents=True, exist_ok=True)
    cached = cache_ldraw / filename
    if version == COMPLETE_VERSION and cached.exists():
        # A leftover complete.zip only exists after a failed unpack, and the
        # complete release is a moving target — never reuse it. Versioned
        # archives come from immutable tags and stay cached.
        logger.info(
            "Discarding cached %s: the complete release is a moving target",
            cached,
        )
        cached.unlink()
    retrieved = _download(
        url=url,
        filename=filename,
        show_progress=show_progress,
        on_progress=on_progress,
        resume=resume,
        cancellation=cancellation,
    )

    version_dir = unpack_version(
        version_zip=retrieved,
        version=version,
        show_progress=show_progress,
        on_progress=on_progress,
        cancellation=cancellation,
    )

    if show_progress:
        print("Running mklist to generate parts.lst ...")
    emit_progress(
        on_progress,
        ProgressEvent(
            stage=ProgressStage.PARTS_LIST,
            message="Generating parts.lst",
            path=version_dir / "ldraw" / "parts.lst",
        ),
    )
    generate_parts_lst(
        mode="description",
        version_dir=version_dir,
    )
    if version == COMPLETE_VERSION:
        version = get_latest_release_id()
        release_file = Path(version_dir) / "ldraw" / "_release.txt"
        release_file.parent.mkdir(parents=True, exist_ok=True)
        release_file.write_text(version)

    return version
