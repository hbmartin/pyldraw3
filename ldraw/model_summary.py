"""Whole-model geometry summaries built from model occurrences."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.errors import PartError
from ldraw.part_geometry_types import BoundingBox

if TYPE_CHECKING:
    from ldraw.colour import Colour
    from ldraw.geometry import Vector
    from ldraw.model import Model
    from ldraw.parts import Parts

LDU_TO_MM = 0.4


@dataclass(frozen=True, slots=True)
class SkippedGeometry:
    """A part occurrence whose geometry could not be folded into bounds."""

    part: str
    source_model: str
    source_line: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class ModelSummary:
    """Reusable summary of a model's placed parts and geometry extents."""

    bounds: BoundingBox | None
    origin_bounds: BoundingBox | None
    part_counts: dict[str, int]
    colour_usage: dict[int | str | None, int]
    skipped_geometry: tuple[SkippedGeometry, ...]
    occurrence_count: int

    @classmethod
    def from_model(cls, model: Model, parts: Parts) -> ModelSummary:
        """Build a summary for ``model`` using geometry from ``parts``."""
        geometry = _BoundsAccumulator()
        origins = _BoundsAccumulator()
        part_counts: Counter[str] = Counter()
        colour_usage: Counter[int | str | None] = Counter()
        skipped: list[SkippedGeometry] = []
        occurrence_count = 0

        for occurrence in model.iter_occurrences():
            occurrence_count += 1
            part_counts[occurrence.part_code] += 1
            colour_usage[_colour_key(occurrence.colour)] += 1
            origins.add(occurrence.position)
            try:
                local_box = parts.bounding_box(occurrence.part_code)
            except PartError as error:
                skipped.append(
                    SkippedGeometry(
                        part=occurrence.part_code,
                        source_model=occurrence.source_model.name,
                        source_line=occurrence.source_line,
                        reason=error.message,
                    ),
                )
                continue
            for corner in local_box.corners():
                geometry.add(occurrence.position + occurrence.matrix * corner)

        return cls(
            bounds=geometry.box(),
            origin_bounds=origins.box(),
            part_counts=dict(part_counts),
            colour_usage=dict(colour_usage),
            skipped_geometry=tuple(skipped),
            occurrence_count=occurrence_count,
        )

    @property
    def size_ldu(self) -> Vector | None:
        """Overall model size in LDraw units."""
        return None if self.bounds is None else self.bounds.size

    @property
    def size_mm(self) -> Vector | None:
        """Overall model size in millimetres."""
        return None if self.size_ldu is None else LDU_TO_MM * self.size_ldu


def model_bounds(model: Model, parts: Parts) -> BoundingBox | None:
    """Return the true transformed bounds for ``model`` in LDraw units."""
    return ModelSummary.from_model(model, parts).bounds


def _colour_key(colour: Colour) -> int | str | None:
    if colour.code is not None:
        return colour.code
    return colour.rgb


class _BoundsAccumulator:
    """Fold points into an axis-aligned bounding box."""

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
