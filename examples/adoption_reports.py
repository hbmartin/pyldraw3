"""Executable document reuse and qualified connection workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ldraw import Model, Parts, Piece, Vector, bom_report, inspect_model, parse_model

if TYPE_CHECKING:
    from pathlib import Path


def document_workflows(parts: Parts, output: Path) -> dict[str, object]:
    """Count physical leaves, inspect raw geometry, and extract attributed parts."""
    model = parse_model(
        "0 FILE scene.ldr\n"
        "1 4 0 0 0 1 0 0 0 1 0 0 0 1 pair.dat\n"
        "0 FILE pair.dat\n0 Pair\n0 !LDRAW_ORG Shortcut\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 local.dat\n"
        "1 16 20 0 0 1 0 0 0 1 0 0 0 1 local.dat\n"
        "0 FILE local.dat\n0 Local block\n0 Author: Example author\n"
        "0 !LICENSE Redistributable under CC BY 4.0 : see CAreadme.txt\n"
        "0 !LDRAW_ORG Part\n2 24 0 0 0 20 8 20\n"
    )
    model.save(output)
    extraction = model.extract("local.dat", namespace="reuse-")
    extraction.model.save(output.with_name("reuse-local.mpd"), mpd=True)
    return {
        "bom": bom_report(model, parts=parts),
        "inspection": inspect_model(model, parts),
        "extraction": extraction,
        "bounded_bom": bom_report(model, parts=parts, occurrence_budget=1),
    }


def connection_workflows(
    parts: Parts, output: Path, *, code: str = "3001", height: float = 24
) -> dict[str, object]:
    """Report contact evidence, topology, snap suggestions, and measurements."""
    model = Model.from_pieces(
        [
            Piece.place(code, colour=4),
            Piece.place(code, colour=2, position=Vector(0, -height, 0)),
        ],
        name="stack.ldr",
    )
    model.save(output)
    inspection = inspect_model(model, parts)
    return {
        "inspection": inspection,
        "snap": inspection.snap_report(moving=1, fixed=0, feature_pair_budget=100),
        "confirmed_components": inspection.connection_graphs().confirmed.components(),
        "optimistic_components": inspection.connection_graphs().optimistic.components(),
        "measurements": parts.measurements(code),
    }
