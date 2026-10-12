"""Rotational geometry evidence for wheels wider than their diameter."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ldraw.geometry import Identity, Vector
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.geometry import Matrix
    from ldraw.part_geometry import _PartGeometryLibrary

_CIRCULAR = re.compile(r"\d+-\d+(?:edge|cyli|ring\d*|con\d*)$", re.IGNORECASE)


def annular_axis(parts: _PartGeometryLibrary, code: str) -> Vector | None:
    """Find a unique dominant axis from placed circular primitives."""
    axes: list[Vector] = []
    _collect_axes(parts, code=code, matrix=Identity(), visiting=frozenset(), axes=axes)
    if not axes:
        return None
    groups: list[tuple[Vector, int]] = []
    for axis in axes:
        for index, (direction, count) in enumerate(groups):
            if abs(direction.dot(axis)) >= 0.999:
                groups[index] = (direction, count + 1)
                break
        else:
            groups.append((axis, 1))
    groups.sort(key=lambda pair: -pair[1])
    if len(groups) > 1 and groups[0][1] == groups[1][1]:
        return None
    axis = groups[0][0]
    values = (axis.x, axis.y, axis.z)
    largest = max(range(3), key=lambda index: abs(values[index]))
    return axis if values[largest] >= 0 else -1 * axis


def _collect_axes(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    matrix: Matrix,
    visiting: frozenset[str],
    axes: list[Vector],
) -> None:
    key = code.casefold()
    if key in visiting:
        return
    from ldraw.errors import PartError  # noqa: PLC0415

    try:
        objects = tuple(parts.part(code=code).objects)
    except (PartError, OSError, UnicodeError):
        return
    for obj in objects:
        if not isinstance(obj, Piece):
            continue
        placed = matrix * obj.matrix
        if _CIRCULAR.fullmatch(obj.part):
            x = placed * Vector(1, 0, 0)
            y = placed * Vector(0, 1, 0)
            z = placed * Vector(0, 0, 1)
            if (
                abs(y)
                and abs(x)
                and abs(z)
                and abs(abs(x) - abs(z)) <= 0.01 * max(abs(x), abs(z))
            ):
                axes.append(y / abs(y))
        else:
            _collect_axes(
                parts,
                code=obj.part if obj.suffix.casefold() == ".dat" else obj.reference,
                matrix=placed,
                visiting=visiting | {key},
                axes=axes,
            )
