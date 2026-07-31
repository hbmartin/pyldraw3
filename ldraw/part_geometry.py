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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from weakref import WeakKeyDictionary

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError, PartError
from ldraw.geometry import Vector
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.part import Part

logger = logging.getLogger("ldraw")

_STUD_PREFIX = "stud"

__all__ = [
    "BoundingBox",
    "PartGeometry",
    "StudReference",
    "part_bounding_box",
    "part_geometry",
    "part_studs",
]


class _PartGeometryLibrary(Protocol):
    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part: ...


@dataclass(frozen=True, slots=True)
class _LocalGeometry:
    """Memoized per-file geometry, in the file's own coordinates."""

    description: str
    box: BoundingBox | None
    points: tuple[Vector, ...]
    studs: tuple[StudReference, ...]
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
    ``NoGeometryError`` when the part draws nothing.
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


def _require_local(parts: _PartGeometryLibrary, code: str) -> _LocalGeometry:
    parts.part(code=code)
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
        error_message = f"subfile reference cycle at {code!r}"
        logger.warning("%s; skipping", error_message)
        return _LocalGeometry(
            description=code,
            box=None,
            points=(),
            studs=(),
            diagnostics=(
                Diagnostic(
                    message=error_message,
                    severity=Severity.WARNING,
                    code=DiagnosticCode.PART_REFERENCE_CYCLE,
                    offending_value=code,
                ),
            ),
        )
    cache = _cache_for(parts)
    if key in cache:
        return cache[key]

    part: Part | None = None
    try:
        part = parts.part(code=code)
        objects = list(part.objects)
    except (OSError, PartError, UnicodeError) as error:
        message = error.message if isinstance(error, PartError) else str(error)
        logger.warning("skipping unresolvable subfile %r: %s", code, message)
        local = _LocalGeometry(
            description=code,
            box=None,
            points=(),
            studs=(),
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
        cache[key] = local
        return local

    box = _BoxAccumulator()
    points: list[Vector] = []
    studs: list[StudReference] = []
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
                    diagnostics=diagnostics,
                    visiting=visiting | {key},
                )

    local = _LocalGeometry(
        description=part.description,
        box=box.box(),
        points=tuple(points),
        studs=tuple(studs),
        diagnostics=tuple(diagnostics),
    )
    cache[key] = local
    return local


def _fold_child(  # noqa: PLR0913 - traversal outputs are explicit
    *,
    parts: _PartGeometryLibrary,
    piece: Piece,
    box: _BoxAccumulator,
    points: list[Vector],
    studs: list[StudReference],
    diagnostics: list[Diagnostic],
    visiting: frozenset[str],
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
