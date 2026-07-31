"""Generate the ldraw.library.parts namespace."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import pystache
from progress.bar import Bar

from ldraw.generation.exceptions import DuplicateSymbolError
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.resources import _get_resource_content
from ldraw.snippets import symbol_name_for_description
from ldraw.utils import clean, safe_identifier

if TYPE_CHECKING:
    from ldraw.parts import Parts

SECTION_SEP = "#|#"

logger = logging.getLogger("ldraw")


def gen_parts(
    parts: Parts,
    library_path: str | Path,
    *,
    cancellation: CancellationToken | None = None,
) -> None:
    """Generate the ldraw.library.parts namespace modules."""
    print("Generating ldraw.library.parts, this might take a long time...")
    parts_dir = Path(library_path) / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    recursive_gen_parts(
        sections=parts.catalog.module_sections(),
        directory=parts_dir,
        prefix=(),
        cancellation=cancellation,
    )


def recursive_gen_parts(
    sections: dict[tuple[str, ...], dict[str, str]],
    directory: Path,
    prefix: tuple[str, ...],
    *,
    cancellation: CancellationToken | None = None,
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
        check_cancelled(cancellation)
        subdir = directory / child_name
        subdir.mkdir(parents=True, exist_ok=True)
        recursive_gen_parts(
            sections=sections,
            directory=subdir,
            prefix=(*prefix, child_name),
            cancellation=cancellation,
        )

    for section_name, section_parts in local_sections.items():
        check_cancelled(cancellation)
        parts_py = directory / f"{section_name}.py"
        parts_py.write_text(
            section_content(
                section_parts,
                section_name,
                cancellation=cancellation,
            ),
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


def section_content(
    section_parts: dict[str, str],
    section_key: str,
    *,
    cancellation: CancellationToken | None = None,
) -> str:
    """Generate the content for a section of parts."""
    parts_list: list[dict[str, str]] = []
    progress_bar = Bar(f"section {section_key} ...", max=len(section_parts))
    for description, code in section_parts.items():
        check_cancelled(cancellation)
        context = _part_context(
            description=description,
            code=code,
            section_key=section_key,
        )
        if context is not None:
            parts_list.append(context)
        progress_bar.next()
    progress_bar.finish()
    _dedupe_class_names(parts_list, section_key)
    parts_list.sort(key=lambda part: part["description"])
    return pystache.render(PARTS_TEMPLATE, context={"parts": parts_list})


def _part_context(
    *,
    description: str,
    code: str,
    section_key: str,
) -> dict[str, str] | None:
    """Build a template context for one part, or None when it cannot render."""
    if not description.strip():
        logger.warning(
            "skipping part %r in module %r: empty description",
            code,
            section_key,
        )
        return None
    class_name = safe_identifier(symbol_name_for_description(description))
    if class_name is None:
        logger.warning(
            "skipping part %r in module %r: description %r yields no valid identifier",
            code,
            section_key,
            description,
        )
        return None
    return {
        "description": description,
        "class_name": class_name,
        "code": code,
        "code_literal": repr(code),
    }


def _dedupe_class_names(parts_list: list[dict[str, str]], section_key: str) -> None:
    """Make sanitized symbol names unique within a generated module.

    Distinct descriptions can sanitize to the same identifier — e.g. the
    ``Tile 1 x 1 with Silver "." / "-" / "@" Pattern`` variants all become
    ``Tile1X1WithSilver_Pattern``. Without deduplication the later
    assignments silently shadow the earlier ones, leaving those parts
    unreachable by name; colliding symbols get a part-code suffix instead.
    """
    by_name: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for part in parts_list:
        by_name[part["class_name"]].append(part)
    for class_name, group in by_name.items():
        if len(group) == 1:
            continue
        logger.warning(
            "%d parts in module %r sanitize to the same symbol %r;"
            " suffixing each with its part code",
            len(group),
            section_key,
            class_name,
        )
        for part in group:
            part["class_name"] = f"{class_name}_{clean(part['code'])}"
    seen: defaultdict[str, int] = defaultdict(int)
    for part in parts_list:
        seen[part["class_name"]] += 1
    if colliding := [name for name, count in seen.items() if count > 1]:
        raise DuplicateSymbolError(section_key, colliding)


PARTS__INIT__TEMPLATE = pystache.parse(
    _get_resource_content("templates/parts__init__.mustache"),
)
PARTS_TEMPLATE = pystache.parse(
    _get_resource_content("templates/parts.mustache"),
)
