"""Runtime services for the download commands."""

from __future__ import annotations

import sys
from zipfile import BadZipFile

import requests

from ldraw.cli._common import _confirm
from ldraw.cli._defaults import COMPLETE_VERSION
from ldraw.config import Config
from ldraw.downloads import cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.errors import CouldNotDetermineLatestVersionError


def download_command(*, version: str, yes: bool) -> int:
    """Download an LDraw library release and point the config at it."""
    prompt = (
        f"This will download the {version!r} LDraw library release "
        f"(~80 MB for {COMPLETE_VERSION!r}). Continue?"
    )
    if not _confirm(prompt, yes=yes):
        print("Aborted.")
        return 1

    try:
        release_id = do_download(version=version, show_progress=sys.stderr.isatty())
    except (
        requests.RequestException,
        ValueError,
        BadZipFile,
        CouldNotDetermineLatestVersionError,
        OSError,
    ) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    config = Config.load()
    config.ldraw_library_path = str(cache_ldraw / version)
    try:
        config.write()
    except OSError as exc:
        print(f"Could not update configuration: {exc}", file=sys.stderr)
        return 1

    print(f"Downloaded LDraw library release {release_id}.", file=sys.stderr)
    print(
        f"Configured ldraw_library_path: {config.ldraw_library_path}",
        file=sys.stderr,
    )
    return 0
