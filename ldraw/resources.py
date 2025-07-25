"""Resource file access utilities."""

import codecs
from importlib import resources


def get_resource(filename):
    return str(resources.files("ldraw") / filename)


def get_resource_content(filename):
    return codecs.open(get_resource(filename), "r", encoding="utf-8").read()
