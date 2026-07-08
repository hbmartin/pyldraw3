"""Generate the ldraw.library.colours module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pystache

from ldraw.resources import _get_resource_content
from ldraw.utils import camel, clean

if TYPE_CHECKING:
    from ldraw.colour import Colour
    from ldraw.parts import Parts


def gen_colours(parts: Parts, library_path: str | Path) -> None:
    """Generate a colours.py from library data."""
    print("Generating ldraw.library.colours...")

    colours_str = colours_module_content(parts)
    colours_py = Path(library_path) / "colours.py"
    colours_py.write_text(colours_str, encoding="utf-8")
    colours_py.with_suffix(".pyi").write_text(colours_str, encoding="utf-8")


def colours_module_content(parts: Parts) -> str:
    """Generate the contents of the colours.py module from parts data."""
    colours_mustache = _get_resource_content("templates/colours.mustache")
    colours_template = pystache.parse(colours_mustache)
    context = {"colours": [get_c_dict(c) for c in parts.colours_by_name.values()]}
    context["colours"].sort(key=lambda row: row["code"])
    return pystache.render(colours_template, context=context)


def get_c_dict(colour: Colour) -> dict[str, object]:
    """Get a dict from a Colour object."""
    return {
        "code": colour.code,
        "full_name": colour.name,
        "name": camel(clean(colour.name or "")),
        "alpha": colour.alpha,
        "rgb": colour.rgb,
        "colour_attributes": colour.colour_attributes,
    }
