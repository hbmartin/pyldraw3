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
