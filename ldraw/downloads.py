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
LDRAW_URL = "https://library.ldraw.org/library/updates/"
cache_ldraw = Path(get_cache_dir())


def unpack_version(version_zip: Path, version: str) -> Path:
    """Unpack a downloaded LDraw library ZIP file to the cache directory."""
    print(f"Unzipping {version_zip}...")
    destination = cache_ldraw / version
    zip_ref = zipfile.ZipFile(version_zip, "r")
    zip_ref.extractall(destination)
    zip_ref.close()
    version_zip.unlink()

    return destination


def _download(url: str, filename: str, chunk_size=1024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        return retrieved

    response = requests.get(url, stream=True)  # noqa: S113

    with open(retrieved, "wb") as file:
        file.writelines(response.iter_content(chunk_size=chunk_size))

    return retrieved


def _download_progress(url: str, filename: str, chunk_size=1024) -> Path:
    retrieved = cache_ldraw / filename
    if retrieved.exists():
        print(f"File {retrieved} already exists")
        return retrieved

    response = requests.get(url, stream=True)  # noqa: S113
    total = int(response.headers.get("content-length", 0))
    bar = Bar(f"Downloading {url} ...", max=total)

    with open(retrieved, "wb") as file:
        for data in response.iter_content(chunk_size=chunk_size):
            size = file.write(data)
            bar.next(size)

    bar.finish()
    return retrieved


def download(*, show_progress: bool = True, version: str = COMPLETE_VERSION) -> str:
    """Download and unpack an LDraw library version, generating parts.lst file."""
    filename = f"{version}.zip"
    retrieved = (
        _download_progress(f"{LDRAW_URL}/{filename}", filename)
        if show_progress
        else _download(f"{LDRAW_URL}/{filename}", filename)
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
