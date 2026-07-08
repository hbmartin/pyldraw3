"""General utility functions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def clean(input_string: str) -> str:
    """Clean a description string."""
    return re.sub(r"\W+", "_", input_string).replace("_x_", "x")


def camel(input_string: str) -> str:
    """Return a CamelCase string."""
    return "".join(x for x in input_string.title() if not x.isspace())


def normalize_ref(ref: str) -> str:
    """Normalize a submodel reference for case-insensitive lookup."""
    return " ".join(ref.split()).casefold().replace("\\", "/")


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


def flatten(
    input_dict: dict[str, Any],
    parent_key: str = "",
    sep: str = ".",
) -> dict[str, Any]:
    """Flatten a dictionary."""
    items: list[tuple[str, Any]] = []
    for key, value in input_dict.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.extend(flatten(value, new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)
