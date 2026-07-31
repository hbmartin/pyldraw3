"""Generate the ldraw.library.colours module."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pystache

from ldraw.generation.exceptions import DuplicateSymbolError
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.resources import _get_resource_content
from ldraw.utils import camel, clean, safe_identifier

if TYPE_CHECKING:
    from ldraw.colour import Colour
    from ldraw.parts import Parts

logger = logging.getLogger("ldraw")


def gen_colours(
    parts: Parts,
    library_path: str | Path,
    *,
    cancellation: CancellationToken | None = None,
) -> None:
    """Generate a colours.py from library data."""
    print("Generating ldraw.library.colours...")

    colours_str = colours_module_content(parts, cancellation=cancellation)
    colours_py = Path(library_path) / "colours.py"
    colours_py.write_text(colours_str, encoding="utf-8")


def colours_module_content(
    parts: Parts,
    *,
    cancellation: CancellationToken | None = None,
) -> str:
    """Generate the contents of the colours.py module from parts data."""
    colours_mustache = _get_resource_content("templates/colours.mustache")
    colours_template = pystache.parse(colours_mustache)
    rows: list[dict[str, object]] = []
    for colour in parts.colours_by_name.values():
        check_cancelled(cancellation)
        name = safe_identifier(camel(clean(colour.name or "")))
        if name is None:
            logger.warning(
                "skipping colour %r (code %s): name yields no valid identifier",
                colour.name,
                colour.code,
            )
            continue
        rows.append(get_c_dict(colour, name=name))
    _dedupe_colour_names(rows)
    rows.sort(key=lambda row: cast("int", row["code"]))
    return pystache.render(colours_template, context={"colours": rows})


def _dedupe_colour_names(rows: list[dict[str, object]]) -> None:
    """Make sanitized colour symbols unique using their LDraw colour codes."""
    by_name: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        name = row["name"]
        if not isinstance(name, str):
            message = f"invalid generated colour name: {name!r}"
            raise TypeError(message)
        by_name[name].append(row)

    for name, group in by_name.items():
        if len(group) == 1:
            continue
        logger.warning(
            "%d colours sanitize to the same symbol %r;"
            " suffixing each with its colour code",
            len(group),
            name,
        )
        for row in group:
            row["name"] = f"{name}_{row['code']}"

    seen: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        seen[str(row["name"])] += 1
    if colliding := [name for name, count in seen.items() if count > 1]:
        raise DuplicateSymbolError("colours", colliding)


def get_c_dict(colour: Colour, *, name: str) -> dict[str, object]:
    """Get a template context dict from a Colour object."""
    return {
        "code": colour.code,
        "full_name_literal": repr(colour.name or ""),
        "name": name,
        "alpha": colour.alpha,
        "rgb_literal": repr(colour.rgb),
        "colour_attributes": colour.colour_attributes,
    }
