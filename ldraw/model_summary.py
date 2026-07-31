"""Whole-model geometry summaries built from model occurrences."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.errors import NoGeometryError, PartError
from ldraw.inspection import transformed_bounds
from ldraw.part_geometry_types import BoundingBox

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.colour import Colour
    from ldraw.geometry import Vector
    from ldraw.inspection import ModelInspection
    from ldraw.model import Model, ModelOccurrence
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
    def from_model(cls, model: Model, parts: Parts | None) -> ModelSummary:
        """Build a summary for ``model`` using geometry from ``parts``.

        Cyclic submodel references (possible in tolerantly-loaded models)
        are skipped rather than raising.
        """
        from ldraw.model import _iter_occurrences_skip_cycles  # noqa: PLC0415

        return cls.from_occurrences(
            tuple(_iter_occurrences_skip_cycles(model)),
            parts,
        )

    @classmethod
    def from_inspection(cls, inspection: ModelInspection) -> ModelSummary:
        """Build a summary reusing bounds already computed by an inspection.

        ``inspect_model`` already transforms every occurrence's expanded
        points into exact world bounds; this constructor folds those
        results instead of recomputing them, so callers building both an
        inspection and a summary pay for the geometry only once.
        """
        origins = _BoundsAccumulator()
        part_counts: Counter[str] = Counter()
        colour_usage: Counter[int | str | None] = Counter()
        skipped: list[SkippedGeometry] = []
        for resolved in inspection.occurrences:
            occurrence = resolved.attribution.occurrence
            part_counts[occurrence.part_code] += 1
            colour_usage[_colour_key(occurrence.colour)] += 1
            origins.add(occurrence.position)
        for entry in inspection.skipped_geometry:
            occurrence = entry.attribution.occurrence
            part_counts[occurrence.part_code] += 1
            colour_usage[_colour_key(occurrence.colour)] += 1
            origins.add(occurrence.position)
            skipped.append(
                SkippedGeometry(
                    part=occurrence.part_code,
                    source_model=occurrence.source_model.name,
                    source_line=occurrence.source_line,
                    reason=entry.diagnostic.message,
                ),
            )
        return cls(
            bounds=inspection.bounds,
            origin_bounds=origins.box(),
            part_counts=dict(part_counts),
            colour_usage=dict(colour_usage),
            skipped_geometry=tuple(skipped),
            occurrence_count=inspection.occurrence_count,
        )

    @classmethod
    def from_occurrences(
        cls,
        occurrences: Iterable[ModelOccurrence],
        parts: Parts | None,
    ) -> ModelSummary:
        """Build a summary from occurrences already traversed by a caller."""
        geometry = _BoundsAccumulator()
        origins = _BoundsAccumulator()
        part_counts: Counter[str] = Counter()
        colour_usage: Counter[int | str | None] = Counter()
        skipped: list[SkippedGeometry] = []
        occurrence_count = 0

        for occurrence in occurrences:
            occurrence_count += 1
            part_counts[occurrence.part_code] += 1
            colour_usage[_colour_key(occurrence.colour)] += 1
            origins.add(occurrence.position)
            if parts is None:
                continue
            try:
                local = parts.geometry(occurrence.part_code)
                world_box = transformed_bounds(
                    local.points,
                    position=occurrence.position,
                    matrix=occurrence.matrix,
                )
                if world_box is None:
                    raise NoGeometryError(occurrence.part_code)
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
            geometry.add(world_box.min)
            geometry.add(world_box.max)

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
