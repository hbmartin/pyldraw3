"""General utility functions."""

from __future__ import annotations

import keyword
import re
from pathlib import Path


def clean(input_string: str) -> str:
    """Clean a description string."""
    return re.sub(r"\W+", "_", input_string).replace("_x_", "x")


def safe_identifier(candidate: str) -> str | None:
    """Return a valid, non-keyword Python identifier from candidate, or None."""
    name = candidate
    if name and name[0].isdigit():
        name = f"P{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name if name.isidentifier() else None


def camel(input_string: str) -> str:
    """Return a CamelCase string."""
    return "".join(x for x in input_string.title() if not x.isspace())


def normalize_ref(ref: str) -> str:
    """Normalize a submodel reference for case-insensitive lookup."""
    return " ".join(ref.split()).casefold().replace("\\", "/")


def split_reference(ref: str) -> tuple[str, str]:
    """Split a subfile reference into its stem and extension.

    Case is preserved so parsed files round-trip byte-identically;
    comparisons and lookups are case-insensitive instead.
    """
    stem, dot, ext = ref.rpartition(".")
    if not dot:
        return ref, ""
    return stem, f".{ext}"


def ldraw_file_name(line: str) -> str | None:
    """Return the section name if the line is a ``0 FILE <name>`` command."""
    match line.split(maxsplit=2):
        case ["0", keyword, rest] if keyword.upper() == "FILE":
            return rest.strip()
        case _:
            return None


def ensure_exists(path: str | Path) -> str:
    """Make the directory if it does not exist."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)
