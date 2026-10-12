"""Executable Python counterparts of the adoption CLI walkthroughs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from ldraw import Model, Parts, Piece, Vector, api_inventory, inspect_model
from ldraw.bom import rows_to_json
from ldraw.rendering import render_preview
from ldraw.validation import iter_ldr_issues


def workflows(
    library: Path, output: Path, *, render: bool = False
) -> dict[str, object]:
    """Search, save, inspect, count, validate, and optionally render a model."""
    parts = Parts.from_directory(library)
    matches = parts.search("3001", limit=5)
    model = Model(name="scene.ldr")
    model.add(Piece.place("3001", colour=4, position=Vector(0, 0, 0)))
    model.save(output)
    inspection = inspect_model(model, parts)
    bom = model.bill_of_materials(parts=parts)
    output.with_suffix(".json").write_text(rows_to_json(bom), encoding="utf-8")
    issues = tuple(iter_ldr_issues(output, parts=parts))
    result: dict[str, object] = {
        "search": matches,
        "inspection": inspection,
        "bom": bom,
        "validation": issues,
        "api": api_inventory("Model.save"),
    }
    if render:
        result["render"] = render_preview(output, parts=parts)
    return result
