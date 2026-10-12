"""Runtime services for the version commands."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

from ldraw.cli._defaults import PACKAGE_NAME


def version_command() -> int:
    """Print the installed pyldraw3 package version."""
    try:
        print(package_version(PACKAGE_NAME))
    except PackageNotFoundError:
        print("unknown (not installed)")
    return 0
