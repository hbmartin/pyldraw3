"""Conservative part measurements with explicit geometric and mating evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from ldraw.connection_types import ConnectionKind, ConnectionSource
from ldraw.coverage import Coverage
from ldraw.diagnostics import Diagnostic, Severity
from ldraw.geometry import Identity, Vector
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.part_geometry_types import BoundingBox
from ldraw.pieces import Piece
from ldraw.units import STUD_PITCH

if TYPE_CHECKING:
    from ldraw.connection_types import ConnectionFeature
    from ldraw.geometry import Matrix
    from ldraw.part_geometry_types import PartGeometry
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class PartMeasurements:
    """Optional measurements in LDU and stud units, qualified by evidence.

    ``footprint_studs`` contains local X/Z top-stud positions divided by
    STUD_PITCH, preserving the part origin. ``stack_height`` is the distance
    between unique supported top and underside seating planes.
    """

    code: str
    body_bounds: BoundingBox | None
    stack_height: float | None
    footprint_studs: tuple[tuple[float, float], ...] | None
    provenance: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize optional values without substituting guesses."""
        bounds = self.body_bounds
        return {
            "code": self.code,
            "body_bounds": {
                "min": _coordinates(bounds.min),
                "max": _coordinates(bounds.max),
            }
            if bounds
            else None,
            "stack_height": self.stack_height,
            "footprint_studs": self.footprint_studs,
            "provenance": list(self.provenance),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


_CACHE: WeakKeyDictionary[Parts, dict[str, tuple[PartGeometry, PartMeasurements]]] = (
    WeakKeyDictionary()
)


def _coordinates(vector: Vector) -> tuple[float, float, float]:
    return vector.x, vector.y, vector.z


def part_measurements(parts: Parts, code: str) -> PartMeasurements:
    """Measure supported geometry and cache its geometry/connection dependencies."""
    geometry = parts.geometry(code)
    cache = _CACHE.setdefault(parts, {})
    if (previous := cache.get(code)) is not None:
        source, result = previous
        if (
            source.points is geometry.points
            and source.connections is geometry.connections
            and source.connection_metadata is geometry.connection_metadata
        ):
            return result
    result = _measure(parts, geometry=geometry)
    cache[code] = (geometry, result)
    return result


def _unsupported(message: str) -> Diagnostic:
    return Diagnostic(
        code="measurement.unsupported", severity=Severity.WARNING, message=message
    )


def _measure(parts: Parts, *, geometry: PartGeometry) -> PartMeasurements:
    diagnostics = list(geometry.diagnostics)
    body = None
    if geometry.geometry_coverage == Coverage.COMPLETE:
        points: list[Vector] = []
        _body_points(
            parts,
            code=geometry.code,
            position=Vector(0, 0, 0),
            matrix=Identity(),
            visiting=frozenset(),
            points=points,
        )
        if points:
            body = BoundingBox(
                min=Vector(
                    *(
                        min(value)
                        for value in zip(*map(_coordinates, points), strict=True)
                    )
                ),
                max=Vector(
                    *(
                        max(value)
                        for value in zip(*map(_coordinates, points), strict=True)
                    )
                ),
            )
    if body is None:
        diagnostics.append(
            _unsupported("Complete body geometry could not be established")
        )
    studs = tuple(
        feature
        for feature in geometry.connections
        if feature.kind is ConnectionKind.STUD
        and feature.confidence > 0
        and feature.source is not ConnectionSource.HEURISTIC
        and feature.axis.dot(Vector(0, -1, 0)) >= 0.999
    )
    footprint = (
        tuple(
            sorted(
                {
                    (feature.position.x / STUD_PITCH, feature.position.z / STUD_PITCH)
                    for feature in studs
                }
            )
        )
        or None
    )
    if footprint is None:
        diagnostics.append(
            _unsupported("No supported top-stud positions for a footprint")
        )
    height = _stack_height(geometry, body=body)
    if height is None:
        diagnostics.append(
            _unsupported(
                "A unique stacking direction and seating planes were not established"
            )
        )
    return PartMeasurements(
        code=geometry.code,
        body_bounds=body,
        stack_height=height,
        footprint_studs=footprint,
        provenance=(
            "expanded drawable records; recognized top-stud primitives excluded",
            "supported stud and receptacle features; local X/Z in stud units",
        ),
        diagnostics=tuple(diagnostics),
    )


def _body_points(  # noqa: PLR0913 - transformed dependency traversal
    parts: Parts,
    *,
    code: str,
    position: Vector,
    matrix: Matrix,
    visiting: frozenset[str],
    points: list[Vector],
) -> None:
    key = code.casefold()
    if key in visiting:
        return
    for obj in parts.part(code=code).objects:
        if isinstance(obj, Line | Triangle | Quadrilateral | OptionalLine):
            values = obj.points[:2] if isinstance(obj, OptionalLine) else obj.points
            points.extend(position + matrix * point for point in values)
        elif isinstance(obj, Piece):
            child_matrix = matrix * obj.matrix
            child_code = obj.part if obj.suffix.casefold() == ".dat" else obj.reference
            description = parts.part(code=child_code).description.casefold()
            top = (
                obj.part.casefold().startswith("stud")
                and not any(
                    marker in description
                    for marker in ("tube", "underside", "placeholder")
                )
                and (child_matrix * Vector(0, -1, 0)).dot(Vector(0, -1, 0)) > 0.99
            )
            if not top:
                _body_points(
                    parts,
                    code=child_code,
                    position=position + matrix * obj.position,
                    matrix=child_matrix,
                    visiting=visiting | {key},
                    points=points,
                )


def _stack_height(geometry: PartGeometry, *, body: BoundingBox | None) -> float | None:
    if body is None or geometry.geometry_coverage != Coverage.COMPLETE:
        return None
    studs = _stacking_features(
        geometry, kind=ConnectionKind.STUD, normal=Vector(0, -1, 0)
    )
    sockets = _stacking_features(
        geometry, kind=ConnectionKind.STUD_RECEPTACLE, normal=Vector(0, 1, 0)
    )
    if studs is None or sockets is None:
        return None
    top = {round(feature.position.y, 6) for feature in studs}
    bottom = {round(feature.position.y, 6) for feature in sockets}
    if len(top) != 1 or len(bottom) != 1:
        return None
    upper, lower = next(iter(top)), next(iter(bottom))
    if (
        abs(upper - body.min.y) > 1e-6
        or abs(lower - body.max.y) > 1e-6
        or lower <= upper
    ):
        return None
    return lower - upper


def _stacking_features(
    geometry: PartGeometry, *, kind: ConnectionKind, normal: Vector
) -> tuple[ConnectionFeature, ...] | None:
    features = tuple(
        feature
        for feature in geometry.connections
        if feature.kind is kind
        and feature.confidence > 0
        and feature.source is not ConnectionSource.HEURISTIC
    )
    if not features or any(feature.axis.dot(normal) < 0.999 for feature in features):
        return None
    return features
