"""Generate the ldraw.library.colours module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pystache

from ldraw.resources import _get_resource_content
from ldraw.utils import camel, clean, safe_identifier

if TYPE_CHECKING:
    from ldraw.colour import Colour
    from ldraw.parts import Parts

logger = logging.getLogger("ldraw")


def gen_colours(parts: Parts, library_path: str | Path) -> None:
    """Generate a colours.py from library data."""
    print("Generating ldraw.library.colours...")

    colours_str = colours_module_content(parts)
    colours_py = Path(library_path) / "colours.py"
    colours_py.write_text(colours_str, encoding="utf-8")


def colours_module_content(parts: Parts) -> str:
    """Generate the contents of the colours.py module from parts data."""
    colours_mustache = _get_resource_content("templates/colours.mustache")
    colours_template = pystache.parse(colours_mustache)
    rows: list[dict[str, object]] = []
    for colour in parts.colours_by_name.values():
        name = safe_identifier(camel(clean(colour.name or "")))
        if name is None:
            logger.warning(
                "skipping colour %r (code %s): name yields no valid identifier",
                colour.name,
                colour.code,
            )
            continue
        rows.append(get_c_dict(colour, name=name))
    rows.sort(key=lambda row: row["code"])
    return pystache.render(colours_template, context={"colours": rows})


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
