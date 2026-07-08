"""Resource file access utilities."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def _get_resource(filename: str) -> str:
    return str(resources.files("ldraw") / filename)


def _get_resource_content(filename: str) -> str:
    return Path(_get_resource(filename)).read_text(encoding="utf-8")
