#!/usr/bin/env python
"""Generates the ldraw.library.parts namespace."""
import os
from pathlib import Path

import pystache
from attridict import AttriDict
from progress.bar import Bar

from ldraw.parts import PartError, Parts
from ldraw.resources import _get_resource_content
from ldraw.utils import camel, clean

SECTION_SEP = "#|#"


def gen_parts(parts: Parts, library_path: str) -> None:
    """Generate the ldraw.library.parts namespace modules."""
    print("generate ldraw.library.parts, this might take a long time...")
    parts_dir = Path(library_path) / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    recursive_gen_parts(parts.parts, parts_dir)


def recursive_gen_parts(parts_parts: AttriDict, directory: Path):
    """Recursively generate parts modules for nested part categories."""
    for name, value in list(parts_parts.items()):
        if isinstance(value, AttriDict):
            recurse = False
            for v in value.values():
                if len(v) > 0:
                    recurse = True

            if recurse:
                subdir = directory / name
                subdir.mkdir(parents=True, exist_ok=True)
                recursive_gen_parts(value, subdir)

    sections = {
        name: value
        for name, value in parts_parts.items()
        if not isinstance(value, AttriDict)
    }

    module_parts = {}
    for section_name, section_parts in sections.items():
        if section_name == "":
            continue
        for desc, code in section_parts.items():
            module_parts[desc] = code  # noqa: PERF403

        parts_py = directory / f"{section_name}.py"
        part_str = section_content(section_parts, section_name)
        parts_py.write_text(part_str)

    generate_parts__init__(directory=directory, sections=sections)


def generate_parts__init__(directory, sections):
    """Generate __init__.py to make submodules in ldraw.library.parts."""
    parts__init__str = parts__init__content(sections)

    parts__init__ = directory / "__init__.py"
    parts__init__.parent.mkdir(parents=True, exist_ok=True)
    parts__init__.write_text(parts__init__str)


def parts__init__content(sections):
    """Generate the content for __init__.py files in parts modules."""
    sections = [
        {"module_name": module_name} for module_name in sections if module_name != ""
    ]
    return pystache.render(PARTS__INIT__TEMPLATE, context={"sections": sections})


def section_content(section_parts, section_key):
    """Generate the content for a section of parts."""
    parts_list = []
    progress_bar = Bar("section %s ..." % str(section_key), max=len(section_parts))
    for description in section_parts:
        parts_list.append(get_part_dict(section_parts, description))
        progress_bar.next()
    progress_bar.finish()
    parts_list = [x for x in parts_list if x != {}]
    parts_list.sort(key=lambda o: o["description"])
    return pystache.render(PARTS_TEMPLATE, context={"parts": parts_list})


PARTS__INIT__TEMPLATE = pystache.parse(
    _get_resource_content(os.path.join("templates", "parts__init__.mustache")),
)
PARTS_TEMPLATE = pystache.parse(
    _get_resource_content(os.path.join("templates", "parts.mustache")),
)


def get_part_dict(parts_parts, description):
    """Get a dict context for a part."""
    try:
        code = parts_parts[description]
        return {
            "description": description,
            "class_name": clean(camel(description)),
            "code": code,
        }
    except (PartError, KeyError):
        return {}
