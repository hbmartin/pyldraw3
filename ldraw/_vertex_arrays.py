"""Bulk transforms of expanded vertices; public geometry retains Vector values."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ldraw.geometry import Vector
from ldraw.part_geometry_types import BoundingBox

if TYPE_CHECKING:
    from collections.abc import Iterable

    from numpy.typing import NDArray

    from ldraw.geometry import Matrix


def transform_vertices(
    points: Iterable[Vector], *, position: Vector, matrix: Matrix
) -> NDArray[np.float64]:
    """Transform each actual vertex, preserving exact drawable AABB semantics."""
    coordinates = np.fromiter(
        (coordinate for point in points for coordinate in (point.x, point.y, point.z)),
        dtype=float,
    ).reshape(-1, 3)
    return coordinates @ np.asarray(matrix.rows).T + (
        position.x,
        position.y,
        position.z,
    )


def vertex_bounds(vertices: NDArray[np.float64]) -> BoundingBox | None:
    """Reduce transformed vertices to an AABB with public Vector endpoints."""
    if not len(vertices):
        return None
    low = vertices.min(axis=0)
    high = vertices.max(axis=0)
    return BoundingBox(min=Vector(*map(float, low)), max=Vector(*map(float, high)))
