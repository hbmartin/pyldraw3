"""Some utils functions."""

import os
import re


def clean(input_string: str) -> str:
    """Clean a description string.

    :param input_string:
    :return:
    """
    return re.sub(r"\W+", "_", input_string).replace("_x_", "x")


def camel(input_string: str) -> str:
    """Return a CamelCase string."""
    return "".join(x for x in input_string.title() if not x.isspace())


def ensure_exists(path: str) -> str:
    """Make the directory if it does not exist."""
    os.makedirs(path, exist_ok=True)  # noqa: PTH103
    return path


# https://stackoverflow.com/a/6027615
def flatten(input_dict: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten a dictionary."""
    items = []
    for key, value in input_dict.items():
        new_key = parent_key + sep + key if parent_key else key
        if isinstance(value, dict):
            items.extend(flatten(value, new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)
