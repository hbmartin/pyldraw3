"""The generated-library symbol mapping, independent of generated imports."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from ldraw.generation.exceptions import DuplicateSymbolError
from ldraw.parts import symbol_name_for_description
from ldraw.utils import clean, safe_identifier

if TYPE_CHECKING:
    from ldraw.parts import CatalogEntry, PartsCatalog

logger = logging.getLogger(__name__)


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


def symbol_mapping(catalog: PartsCatalog) -> dict[str, CatalogEntry]:
    """Resolve full generated names using generation's collision rules."""
    result: dict[str, CatalogEntry] = {}
    for module, entries in catalog.module_sections().items():
        contexts = [
            context
            for description, code in entries.items()
            if (
                context := _part_context(
                    description=description, code=code, section_key=module[-1]
                )
            )
            is not None
        ]
        _dedupe_class_names(contexts, module[-1])
        prefix = f"ldraw.library.parts.{'.'.join(module)}"
        for context in contexts:
            result[f"{prefix}.{context['class_name']}"] = catalog.by_code[
                context["code"]
            ]
    return result
