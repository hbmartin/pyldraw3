"""Some utils functions."""

import collections
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def strtobool(val):
    """Convert a string representation of truth to True or False."""
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    if val in ("n", "no", "f", "false", "off", "0"):
        return False
    raise ValueError(f"invalid truth value {val!r}")


def clean(input_string):
    """Clean a description string.

    :param input_string:
    :return:
    """
    input_string = re.sub(r"\W+", "_", input_string)
    input_string = re.sub(r"_x_", "x", input_string)
    return input_string


def camel(input_string):
    """Return a CamelCase string."""
    return "".join(x for x in input_string.title() if not x.isspace())


def prompt(query):
    print("%s [y/n]: " % query)
    while True:
        val = input()
        try:
            return strtobool(val)
        except ValueError:
            print("Please answer with y/n")


def ensure_exists(path):
    """Make the directory if it does not exist."""
    os.makedirs(path, exist_ok=True)
    return path


# https://stackoverflow.com/a/6027615
def flatten(input_dict, parent_key="", sep="."):
    """Flatten a dictionary."""
    items = []
    for key, value in input_dict.items():
        new_key = parent_key + sep + key if parent_key else key
        if isinstance(value, collections.MutableMapping):
            items.extend(flatten(value, new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)


# https://stackoverflow.com/a/6027615
def flatten2(input_dict, parent_key=None):
    """Flatten a dictionary."""
    items = []
    for key, value in input_dict.items():
        new_key = parent_key + (key,) if parent_key is not None else (key,)
        if isinstance(value, collections.MutableMapping):
            items.extend(flatten2(value, new_key).items())
        else:
            items.append((new_key, value))
    return dict(items)


def file_exists(location):
    request = Request(location)
    request.get_method = lambda: "HEAD"
    try:
        response = urlopen(request)
        return True
    except HTTPError:
        return False
