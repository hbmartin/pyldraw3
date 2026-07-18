"""Resource file access utilities."""

from __future__ import annotations

from importlib import resources


def _get_resource_content(filename: str) -> str:
    """Read a packaged resource as text; zip-import safe.

    ``filename`` is a forward-slash relative path like
    ``templates/parts.mustache``.
    """
    return (resources.files("ldraw") / filename).read_text(encoding="utf-8")
