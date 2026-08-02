"""Geometry queries over resolved part files: bounding boxes and studs.

LDraw part files place their geometry around a conventional origin (for
bricks: the plane under the studs, with the body extending towards +Y and
studs towards -Y). These helpers resolve a part's subfile tree and answer
the two questions a placement tool needs — how big is the part, and where
are its studs — without the caller reading ``.dat`` files by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from weakref import WeakKeyDictionary

from ldraw.connection_inference import (
    infer_part_connections,
    mark_internal_fit_occupied,
    normalize_connections,
    primitive_connections,
)
from ldraw.connection_metadata import parse_ldcad_commands
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError, PartError
from ldraw.geometry import Vector
from ldraw.lines import Line, MetaCommand, OptionalLine, Quadrilateral, Triangle
from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.connection_metadata import ShadowConnectionResult
    from ldraw.connection_types import ConnectionFeature
    from ldraw.part import Part

logger = logging.getLogger("ldraw")

_STUD_PREFIX = "stud"

__all__ = [
    "BoundingBox",
    "PartGeometry",
    "StudReference",
    "clear_part_geometry_cache",
    "part_bounding_box",
    "part_connections",
    "part_geometry",
    "part_studs",
]


class _PartGeometryLibrary(Protocol):
    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part: ...


@runtime_checkable
class _CatalogDescriptionSource(Protocol):
    def description_for(self, code: str) -> str | None: ...


@runtime_checkable
class _CompatibleTyresSource(Protocol):
    def compatible_tyres(self, rim_code: str) -> tuple[str, ...]: ...


@runtime_checkable
class _CompatibleRimsSource(Protocol):
    def compatible_rims(self, tyre_code: str) -> tuple[str, ...]: ...


@runtime_checkable
class _ConnectionShadowSource(Protocol):
    def _shadow_connections_for(self, code: str) -> ShadowConnectionResult: ...


@runtime_checkable
class _ConnectionOverrideSource(Protocol):
    def _connection_overrides_for(
        self,
        code: str,
    ) -> tuple[tuple[ConnectionFeature, ...], bool]: ...


@dataclass(frozen=True, slots=True)
class _LocalGeometry:
    """Memoized per-file geometry, in the file's own coordinates."""

    description: str
    box: BoundingBox | None
    points: tuple[Vector, ...]
    studs: tuple[StudReference, ...]
    connections: tuple[ConnectionFeature, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


_caches: WeakKeyDictionary[_PartGeometryLibrary, dict[str, _LocalGeometry | None]] = (
    WeakKeyDictionary()
)


def part_bounding_box(parts: _PartGeometryLibrary, code: str) -> BoundingBox:
    """Axis-aligned bounding box of a part's geometry, in LDU.

    Subfiles are resolved recursively and the expanded drawable points are
    transformed before the box is folded, including under oblique transforms.
    Unresolvable subfiles are skipped with a warning.

    Raises ``PartNotFoundError`` for an unknown code and
    ``NoGeometryError`` when the part draws nothing. Read failures
    (``OSError``/``UnicodeError``) on the part's own file are tolerated
    the same way as unresolvable subfiles: the file contributes no
    geometry, so the query raises ``NoGeometryError`` rather than the
    underlying IO error.
    """
    local = _require_local(parts, code)
    if local.box is None:
        raise NoGeometryError(code)
    return local.box


def part_geometry(parts: _PartGeometryLibrary, code: str) -> PartGeometry:
    """Return exact expanded points, bounds, connectors, and diagnostics."""
    local = _require_local(parts, code)
    return PartGeometry(
        code=code,
        description=local.description,
        bounds=local.box,
        points=local.points,
        studs=local.studs,
        connections=local.connections,
        diagnostics=local.diagnostics,
    )


def part_studs(parts: _PartGeometryLibrary, code: str) -> tuple[StudReference, ...]:
    """All stud primitives a part places, in the part's own coordinates.

    Stud groups and subparts are expanded down to individual ``stud*``
    primitives; recursion stops at each stud so nothing is counted twice.
    Filter with ``StudReference.is_top_stud`` (or use
    ``Parts.stud_positions``) to keep only upward connectors.
    """
    return _require_local(parts, code).studs


def part_connections(
    parts: _PartGeometryLibrary,
    code: str,
) -> tuple[ConnectionFeature, ...]:
    """Return all detected physical connection features for a part."""
    return _require_local(parts, code).connections


def clear_part_geometry_cache(parts: _PartGeometryLibrary | None = None) -> None:
    """Clear derived geometry for one parts library or for all libraries."""
    if parts is None:
        _caches.clear()
    else:
        _caches.pop(parts, None)


def _require_local(parts: _PartGeometryLibrary, code: str) -> _LocalGeometry:
    cached = _cache_for(parts).get(_local_key(code))
    if cached is not None and cached.box is not None:
        # Cache hit with drawable geometry: skip re-resolving the file path.
        return cached
    parts.part(code=code)  # raises the precise PartError for this code
    local = _local_geometry(parts, code, frozenset())
    if local is None:
        raise NoGeometryError(code)  # pragma: no cover - cache raced with disk
    return local


def _cache_for(parts: _PartGeometryLibrary) -> dict[str, _LocalGeometry | None]:
    return _caches.setdefault(parts, {})


def _local_key(code: str) -> str:
    return code.replace("\\", "/").casefold()


def _local_geometry(
    parts: _PartGeometryLibrary,
    code: str,
    visiting: frozenset[str],
) -> _LocalGeometry | None:
    key = _local_key(code)
    if key in visiting:
        return _reference_cycle_geometry(code)
    cache = _cache_for(parts)
    if key in cache:
        return cache[key]

    source = _load_geometry_source(parts, code)
    if isinstance(source, _LocalGeometry):
        cache[key] = source
        return source
    part, objects = source
    box, points, studs, connections, diagnostics = _fold_objects(
        parts,
        code=code,
        description=part.description,
        objects=objects,
        visiting=visiting | {key},
    )
    connections = _resolve_connections(
        parts,
        code=code,
        description=part.description,
        path=part.path,
        objects=objects,
        box=box,
        connections=connections,
        diagnostics=diagnostics,
    )
    local = _LocalGeometry(
        description=part.description,
        box=box.box(),
        points=tuple(points),
        studs=tuple(studs),
        connections=tuple(connections),
        diagnostics=tuple(diagnostics),
    )
    cache[key] = local
    return local


def _reference_cycle_geometry(code: str) -> _LocalGeometry:
    error_message = f"subfile reference cycle at {code!r}"
    logger.warning("%s; skipping", error_message)
    return _LocalGeometry(
        description=code,
        box=None,
        points=(),
        studs=(),
        connections=(),
        diagnostics=(
            Diagnostic(
                message=error_message,
                severity=Severity.WARNING,
                code=DiagnosticCode.PART_REFERENCE_CYCLE,
                offending_value=code,
            ),
        ),
    )


def _load_geometry_source(
    parts: _PartGeometryLibrary,
    code: str,
) -> tuple[Part, list[object]] | _LocalGeometry:
    part: Part | None = None
    try:
        part = parts.part(code=code)
        return part, list(part.objects)
    except (OSError, PartError, UnicodeError) as error:
        message = error.message if isinstance(error, PartError) else str(error)
        logger.warning("skipping unresolvable subfile %r: %s", code, message)
        return _LocalGeometry(
            description=code,
            box=None,
            points=(),
            studs=(),
            connections=(),
            diagnostics=(
                Diagnostic(
                    line_number=(
                        error.line_number if isinstance(error, PartError) else None
                    ),
                    message=message,
                    severity=Severity.WARNING,
                    code=DiagnosticCode.PART_REFERENCE_UNRESOLVED,
                    path=(
                        Path(error.source)
                        if isinstance(error, PartError) and error.source is not None
                        else part.path
                        if part is not None
                        else None
                    ),
                    offending_value=code,
                    cause=error,
                ),
            ),
        )


def _fold_objects(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    objects: list[object],
    visiting: frozenset[str],
) -> tuple[
    _BoxAccumulator,
    list[Vector],
    list[StudReference],
    list[ConnectionFeature],
    list[Diagnostic],
]:
    box = _BoxAccumulator()
    points: list[Vector] = []
    studs: list[StudReference] = []
    connections: list[ConnectionFeature] = []
    diagnostics: list[Diagnostic] = []
    for obj in objects:
        match obj:
            case Line() | Triangle() | Quadrilateral():
                for point in obj.points:
                    box.add(point)
                    points.append(point.copy())
            case OptionalLine():
                # Points 3 and 4 only control visibility; they can sit far
                # off the surface and must not stretch the box.
                box.add(obj.point1)
                box.add(obj.point2)
                points.extend((obj.point1.copy(), obj.point2.copy()))
            case Piece():
                _fold_child(
                    parts=parts,
                    piece=obj,
                    box=box,
                    points=points,
                    studs=studs,
                    connections=connections,
                    diagnostics=diagnostics,
                    visiting=visiting,
                    parent_code=code,
                    parent_description=description,
                )
    return box, points, studs, connections, diagnostics


def _resolve_connections(  # noqa: PLR0913 - resolution inputs are explicit
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    path: Path,
    objects: list[object],
    box: _BoxAccumulator,
    connections: list[ConnectionFeature],
    diagnostics: list[Diagnostic],
) -> list[ConnectionFeature]:
    connections = list(normalize_connections(connections))
    catalog_part = _is_catalog_part(parts, code)
    connections = _infer_catalog_connections(
        parts,
        code=code,
        description=description,
        bounds=box.box(),
        connections=connections,
    )
    inline_result = parse_ldcad_commands(
        code,
        (
            obj.text
            for obj in objects
            if isinstance(obj, MetaCommand) and obj.type.casefold() == "ldcad"
        ),
        source=path,
    )
    connections = _apply_connection_metadata_result(
        connections=connections,
        result=inline_result,
    )
    diagnostics.extend(inline_result.diagnostics)
    connections, shadow_diagnostics = _apply_shadow_connections(
        parts,
        code=code,
        connections=connections,
    )
    diagnostics.extend(shadow_diagnostics)
    connections = _apply_connection_overrides(
        parts,
        code=code,
        connections=connections,
    )
    if catalog_part and " with tyre " in description.casefold():
        connections = list(
            mark_internal_fit_occupied(connections, assembly_code=code),
        )
    return connections


def _fold_child(  # noqa: PLR0913 - traversal outputs are explicit
    *,
    parts: _PartGeometryLibrary,
    piece: Piece,
    box: _BoxAccumulator,
    points: list[Vector],
    studs: list[StudReference],
    connections: list[ConnectionFeature],
    diagnostics: list[Diagnostic],
    visiting: frozenset[str],
    parent_code: str,
    parent_description: str,
) -> None:
    local = _local_geometry(parts, piece.part, visiting)
    if local is None:
        return
    diagnostics.extend(local.diagnostics)
    for point in local.points:
        transformed = piece.position + piece.matrix * point
        box.add(transformed)
        points.append(transformed)
    stem = _local_key(piece.part).rpartition("/")[2]
    inferred = primitive_connections(
        parent_code=parent_code,
        parent_description=parent_description,
        stem=stem,
        description=local.description,
        bounds=local.box,
        position=piece.position,
        matrix=piece.matrix,
    )
    connections.extend(inferred)
    connections.extend(
        _transformed_child_connection(
            parts,
            feature=feature,
            piece=piece,
            parent_code=parent_code,
        )
        for feature in local.connections
    )
    if stem.startswith(_STUD_PREFIX):
        studs.append(
            StudReference(
                name=stem,
                description=local.description,
                position=piece.position.copy(),
                up=piece.matrix * Vector(0, -1, 0),
            ),
        )
        return
    studs.extend(
        StudReference(
            name=stud.name,
            description=stud.description,
            position=piece.position + piece.matrix * stud.position,
            up=piece.matrix * stud.up,
        )
        for stud in local.studs
    )


def _transformed_child_connection(
    parts: _PartGeometryLibrary,
    *,
    feature: ConnectionFeature,
    piece: Piece,
    parent_code: str,
) -> ConnectionFeature:
    transformed = feature.transformed(position=piece.position, matrix=piece.matrix)
    return (
        transformed
        if _is_catalog_part(parts, piece.part)
        else replace(transformed, owner_code=parent_code)
    )


def _compatible_parts(
    parts: _PartGeometryLibrary,
    code: str,
    description: str,
) -> tuple[str, ...]:
    normalized = description.strip(" ~=_|-").casefold()
    if normalized.startswith("wheel rim ") and isinstance(
        parts,
        _CompatibleTyresSource,
    ):
        return tuple(parts.compatible_tyres(code))
    if normalized.startswith("tyre ") and isinstance(
        parts,
        _CompatibleRimsSource,
    ):
        return tuple(parts.compatible_rims(code))
    return ()


def _infer_catalog_connections(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    bounds: BoundingBox | None,
    connections: list[ConnectionFeature],
) -> list[ConnectionFeature]:
    if not _is_catalog_part(parts, code):
        return connections
    return list(
        infer_part_connections(
            code=code,
            description=description,
            bounds=bounds,
            existing=connections,
            compatible_parts=_compatible_parts(parts, code, description),
        ),
    )


def _is_catalog_part(parts: _PartGeometryLibrary, code: str) -> bool:
    if not isinstance(parts, _CatalogDescriptionSource):
        return True
    return parts.description_for(code) is not None


def _apply_shadow_connections(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    connections: list[ConnectionFeature],
) -> tuple[list[ConnectionFeature], tuple[Diagnostic, ...]]:
    if not isinstance(parts, _ConnectionShadowSource):
        return connections, ()
    result = parts._shadow_connections_for(code)  # noqa: SLF001 - protocol member
    connections = _apply_connection_metadata_result(
        connections=connections,
        result=result,
    )
    return connections, result.diagnostics


def _apply_connection_metadata_result(
    *,
    connections: list[ConnectionFeature],
    result: ShadowConnectionResult,
) -> list[ConnectionFeature]:
    if result.clear_all:
        connections.clear()
    elif result.clear_ids:
        cleared = set(result.clear_ids)
        connections = [
            feature for feature in connections if feature.feature_id not in cleared
        ]
    connections.extend(result.features)
    return list(normalize_connections(connections))


def _apply_connection_overrides(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    connections: list[ConnectionFeature],
) -> list[ConnectionFeature]:
    if not isinstance(parts, _ConnectionOverrideSource):
        return connections
    features, replace_existing = parts._connection_overrides_for(code)  # noqa: SLF001
    values = list(features) if replace_existing else [*connections, *features]
    return list(normalize_connections(values))


class _BoxAccumulator:
    """Folds points into an axis-aligned min/max pair."""

    def __init__(self) -> None:
        self._min: Vector | None = None
        self._max: Vector | None = None

    def add(self, point: Vector) -> None:
        if self._min is None or self._max is None:
            self._min = point.copy()
            self._max = point.copy()
            return
        self._min.x = min(self._min.x, point.x)
        self._min.y = min(self._min.y, point.y)
        self._min.z = min(self._min.z, point.z)
        self._max.x = max(self._max.x, point.x)
        self._max.y = max(self._max.y, point.y)
        self._max.z = max(self._max.z, point.z)

    def box(self) -> BoundingBox | None:
        if self._min is None or self._max is None:
            return None
        return BoundingBox(min=self._min.copy(), max=self._max.copy())
