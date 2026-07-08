"""Generate the ldraw.library.parts namespace."""

from __future__ import annotations

from pathlib import Path

import pystache
from progress.bar import Bar

from ldraw.parts import PartError, Parts
from ldraw.resources import _get_resource_content
from ldraw.utils import camel, clean

SECTION_SEP = "#|#"


def gen_parts(parts: Parts, library_path: str | Path) -> None:
    """Generate the ldraw.library.parts namespace modules."""
    print("Generating ldraw.library.parts, this might take a long time...")
    parts_dir = Path(library_path) / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    recursive_gen_parts(
        sections=parts.catalog.module_sections(),
        directory=parts_dir,
        prefix=(),
    )


def recursive_gen_parts(
    sections: dict[tuple[str, ...], dict[str, str]],
    directory: Path,
    prefix: tuple[str, ...],
) -> None:
    """Recursively generate parts modules for nested part categories."""
    child_directories = sorted(
        {
            module_path[len(prefix)]
            for module_path in sections
            if module_path[: len(prefix)] == prefix
            and len(module_path) > len(prefix) + 1
        },
    )
    local_sections = {
        module_path[-1]: section_parts
        for module_path, section_parts in sections.items()
        if module_path[: len(prefix)] == prefix and len(module_path) == len(prefix) + 1
    }

    for child_name in child_directories:
        subdir = directory / child_name
        subdir.mkdir(parents=True, exist_ok=True)
        recursive_gen_parts(
            sections=sections,
            directory=subdir,
            prefix=(*prefix, child_name),
        )

    for section_name, section_parts in local_sections.items():
        parts_py = directory / f"{section_name}.py"
        parts_py.write_text(
            section_content(section_parts, section_name),
            encoding="utf-8",
        )

    generate_parts__init__(
        directory=directory,
        sections=[*child_directories, *sorted(local_sections)],
    )


def generate_parts__init__(directory: Path, sections: list[str]) -> None:
    """Generate __init__.py to make submodules in ldraw.library.parts."""
    parts__init__ = directory / "__init__.py"
    parts__init__.parent.mkdir(parents=True, exist_ok=True)
    parts__init__.write_text(parts__init__content(sections), encoding="utf-8")


def parts__init__content(sections: list[str]) -> str:
    """Generate the content for __init__.py files in parts modules."""
    section_context = [{"module_name": module_name} for module_name in sections]
    return pystache.render(
        PARTS__INIT__TEMPLATE,
        context={"sections": section_context},
    )


def section_content(section_parts: dict[str, str], section_key: str) -> str:
    """Generate the content for a section of parts."""
    parts_list = []
    progress_bar = Bar(f"section {section_key} ...", max=len(section_parts))
    for description in section_parts:
        parts_list.append(get_part_dict(section_parts, description))
        progress_bar.next()
    progress_bar.finish()
    parts_list = [part for part in parts_list if part != {}]
    parts_list.sort(key=lambda part: part["description"])
    return pystache.render(PARTS_TEMPLATE, context={"parts": parts_list})


PARTS__INIT__TEMPLATE = pystache.parse(
    _get_resource_content(str(Path("templates") / "parts__init__.mustache")),
)
PARTS_TEMPLATE = pystache.parse(
    _get_resource_content(str(Path("templates") / "parts.mustache")),
)


def get_part_dict(parts_parts: dict[str, str], description: str) -> dict[str, str]:
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
