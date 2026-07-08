"""LDraw library file download and extraction functionality."""

import logging
import re
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import requests
from progress.bar import Bar

from ldraw.dirs import get_cache_dir
from ldraw.download_updates import get_latest_release_id
from ldraw.generate import generate_parts_lst

logger = logging.getLogger(__name__)

COMPLETE_VERSION = "complete"
LDRAW_URL = "https://library.ldraw.org/library/updates"
ARCHIVE_URL = "https://github.com/rienafairefr/ldraw-parts/archive/refs/tags"
VERSION_RE = re.compile(r"^\d{4}-\d{2}$")
cache_ldraw = Path(get_cache_dir())


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
    return temp_path.rename(destination)


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
    children = list(destination.iterdir())
    if (
        len(children) == 1
        and children[0].is_dir()
        and children[0].name.lower().startswith("ldraw-parts-")
    ):
        wrapper = children[0]
        for entry in wrapper.iterdir():
            entry.rename(destination / entry.name)
        wrapper.rmdir()

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
    for dirpath, dirnames, filenames in ldraw_dir.walk(top_down=False):
        for name in filenames + dirnames:
            lower_name = name.lower()
            if name != lower_name:
                _case_safe_rename(dirpath / name, dirpath / lower_name)


def unpack_version(version_zip: Path, version: str) -> Path:
    """Unpack a downloaded LDraw library ZIP file to the cache directory."""
    _validate_version(version)
    print(f"Unzipping {version_zip}...")
    destination = cache_ldraw / version
    with zipfile.ZipFile(version_zip, "r") as zip_ref:
        destination.mkdir(parents=True, exist_ok=True)
        _validate_zip_members(zip_ref, destination)
        zip_ref.extractall(destination)
    version_zip.unlink()
    _normalize_tree(destination)

    return destination


def _stream_download(
    url: str,
    retrieved: Path,
    chunk_size: int,
    *,
    show_progress: bool,
) -> Path:
    """Stream ``url`` to ``retrieved`` through a ``.part`` file.

    The body is written to a sibling ``.part`` file and renamed into place only
    once it is fully received, so an interrupted download is never cached as a
    complete file.
    """
    partial = retrieved.with_name(f"{retrieved.name}.part")
    with requests.get(url, stream=True) as response:  # noqa: S113
        response.raise_for_status()
        with partial.open("wb") as file:
            if not show_progress:
                file.writelines(response.iter_content(chunk_size=chunk_size))
            else:
                total = int(response.headers.get("content-length", 0))
                bar = Bar(f"Downloading {url} ...", max=total)
                for data in response.iter_content(chunk_size=chunk_size):
                    bar.next(file.write(data))
                bar.finish()
    partial.replace(retrieved)
    return retrieved


def _download(url: str, filename: str, chunk_size: int = 1_024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        return retrieved
    return _stream_download(url, retrieved, chunk_size, show_progress=False)


def _download_progress(url: str, filename: str, chunk_size: int = 1_024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        print(f"File {retrieved} already exists")
        return retrieved
    return _stream_download(url, retrieved, chunk_size, show_progress=True)


def download(*, show_progress: bool = True, version: str = COMPLETE_VERSION) -> str:
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
    retrieved = (
        _download_progress(url, filename) if show_progress else _download(url, filename)
    )

    version_dir = unpack_version(retrieved, version)

    print("Running mklist to generate parts.lst ...")
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
