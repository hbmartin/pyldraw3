"""LDraw library file download and extraction functionality."""

import logging
import zipfile
from pathlib import Path

import requests
from progress.bar import Bar

from ldraw.dirs import get_cache_dir
from ldraw.download_updates import get_latest_release_id
from ldraw.generate import generate_parts_lst

logger = logging.getLogger(__name__)

COMPLETE_VERSION = "complete"
LDRAW_URL = "https://library.ldraw.org/library/updates"
ARCHIVE_URL = "https://github.com/rienafairefr/ldraw-parts/archive/refs/tags"
cache_ldraw = Path(get_cache_dir())


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
        ldraw_dir = ldraw_dir.rename(destination / "ldraw")
    for dirpath, dirnames, filenames in ldraw_dir.walk(top_down=False):
        for name in filenames + dirnames:
            lower_name = name.lower()
            if name != lower_name:
                (dirpath / name).rename(dirpath / lower_name)


def unpack_version(version_zip: Path, version: str) -> Path:
    """Unpack a downloaded LDraw library ZIP file to the cache directory."""
    print(f"Unzipping {version_zip}...")
    destination = cache_ldraw / version
    with zipfile.ZipFile(version_zip, "r") as zip_ref:
        zip_ref.extractall(destination)
    version_zip.unlink()
    _normalize_tree(destination)

    return destination


def _download(url: str, filename: str, chunk_size=1024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        return retrieved

    response = requests.get(url, stream=True)  # noqa: S113
    response.raise_for_status()

    with open(retrieved, "wb") as file:
        file.writelines(response.iter_content(chunk_size=chunk_size))

    return retrieved


def _download_progress(url: str, filename: str, chunk_size=1024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        print(f"File {retrieved} already exists")
        return retrieved

    response = requests.get(url, stream=True)  # noqa: S113
    response.raise_for_status()
    total = int(response.headers.get("content-length", 0))
    bar = Bar(f"Downloading {url} ...", max=total)

    with open(retrieved, "wb") as file:
        for data in response.iter_content(chunk_size=chunk_size):
            size = file.write(data)
            bar.next(size)

    bar.finish()
    return retrieved


def download(*, show_progress: bool = True, version: str = COMPLETE_VERSION) -> str:
    """Download and unpack an LDraw library version, generating parts.lst file.

    The complete library comes from ldraw.org; versioned releases come from
    snapshot tags of the rienafairefr/ldraw-parts GitHub repository.
    """
    filename = f"{version}.zip"
    url = (
        f"{LDRAW_URL}/{filename}"
        if version == COMPLETE_VERSION
        else f"{ARCHIVE_URL}/{filename}"
    )
    retrieved = (
        _download_progress(url, filename)
        if show_progress
        else _download(url, filename)
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
