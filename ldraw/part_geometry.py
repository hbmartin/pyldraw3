"""Geometry queries over resolved part files: bounding boxes and studs.

LDraw part files place their geometry around a conventional origin (for
bricks: the plane under the studs, with the body extending towards +Y and
studs towards -Y). These helpers resolve a part's subfile tree and answer
the two questions a placement tool needs — how big is the part, and where
are its studs — without the caller reading ``.dat`` files by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from weakref import WeakKeyDictionary

from ldraw.errors import NoGeometryError, PartError
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.part_geometry_types import BoundingBox, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.geometry import Vector
    from ldraw.part import Part

logger = logging.getLogger("ldraw")

_STUD_PREFIX = "stud"


class _PartGeometryLibrary(Protocol):
    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _LocalGeometry:
    """Memoized per-file geometry, in the file's own coordinates."""

    description: str
    box: BoundingBox | None
    studs: tuple[StudReference, ...]


_caches: WeakKeyDictionary[_PartGeometryLibrary, dict[str, _LocalGeometry | None]] = (
    WeakKeyDictionary()
)


def part_bounding_box(parts: _PartGeometryLibrary, code: str) -> BoundingBox:
    """Axis-aligned bounding box of a part's geometry, in LDU.

    Subfiles are resolved recursively and their memoized boxes composed by
    transforming box corners, which is exact under the axis-aligned
    rotations that dominate the library and slightly conservative under
    oblique ones. Unresolvable subfiles are skipped with a warning.

    Raises ``PartNotFoundError`` for an unknown code and
    ``NoGeometryError`` when the part draws nothing.
    """
    local = _require_local(parts, code)
    if local.box is None:
        raise NoGeometryError(code)
    return local.box


def part_studs(parts: _PartGeometryLibrary, code: str) -> tuple[StudReference, ...]:
    """All stud primitives a part places, in the part's own coordinates.

    Stud groups and subparts are expanded down to individual ``stud*``
    primitives; recursion stops at each stud so nothing is counted twice.
    Filter with ``StudReference.is_top_stud`` (or use
    ``Parts.stud_positions``) to keep only upward connectors.
    """
    return _require_local(parts, code).studs


def _require_local(parts: _PartGeometryLibrary, code: str) -> _LocalGeometry:
    local = _local_geometry(parts, code, frozenset())
    if local is None:
        parts.part(code=code)  # raises the precise PartError for this code
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
        logger.warning("subfile reference cycle at %r; skipping", code)
        return None
    cache = _cache_for(parts)
    if key in cache:
        return cache[key]

    try:
        part = parts.part(code=code)
        objects = list(part.objects)
    except PartError as error:
        logger.warning("skipping unresolvable subfile %r: %s", code, error.message)
        cache[key] = None
        return None

    box = _BoxAccumulator()
    studs: list[StudReference] = []
    for obj in objects:
        match obj:
            case Line() | Triangle() | Quadrilateral():
                for point in obj.points:
                    box.add(point)
            case OptionalLine():
                # Points 3 and 4 only control visibility; they can sit far
                # off the surface and must not stretch the box.
                box.add(obj.point1)
                box.add(obj.point2)
            case Piece():
                _fold_child(
                    parts=parts,
                    piece=obj,
                    box=box,
                    studs=studs,
                    visiting=visiting | {key},
                )

    local = _LocalGeometry(
        description=part.description,
        box=box.box(),
        studs=tuple(studs),
    )
    cache[key] = local
    return local


def _fold_child(
    *,
    parts: _PartGeometryLibrary,
    piece: Piece,
    box: _BoxAccumulator,
    studs: list[StudReference],
    visiting: frozenset[str],
) -> None:
    local = _local_geometry(parts, piece.part, visiting)
    if local is None:
        return
    if local.box is not None:
        for corner in local.box.corners():
            box.add(piece.position + piece.matrix * corner)
    stem = _local_key(piece.part).rpartition("/")[2]
    if stem.startswith(_STUD_PREFIX):
        studs.append(
            StudReference(
                name=stem,
                description=local.description,
                position=piece.position.copy(),
            ),
        )
        return
    studs.extend(
        StudReference(
            name=stud.name,
            description=stud.description,
            position=piece.position + piece.matrix * stud.position,
        )
        for stud in local.studs
    )


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
