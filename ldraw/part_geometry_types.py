"""Value objects returned by part geometry queries."""

from __future__ import annotations

from dataclasses import dataclass, field

from ldraw.geometry import Vector

__all__ = ["BoundingBox", "StudReference"]

# Stud primitives whose description carries one of these markers connect
# downwards (underside tubes and the like) or are drawing aids, not studs a
# brick above would sit on.
_NON_TOP_STUD_MARKERS = ("tube", "underside", "placeholder")

# A top stud's transformed up direction must stay within ~8 degrees of
# straight up; anything looser is a sideways or inverted placement.
_TOP_STUD_MIN_ALIGNMENT = 0.99


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned box in LDraw units (LDU).

    LDraw's Y axis points down, so ``min.y`` is the highest point of the
    part (typically the stud tops) and ``max.y`` the lowest.
    """

    min: Vector
    max: Vector

    @property
    def size(self) -> Vector:
        """Extent along each axis."""
        return self.max - self.min

    def corners(self) -> tuple[Vector, ...]:
        """Return the eight corner points of the box."""
        return tuple(
            Vector(x, y, z)
            for x in (self.min.x, self.max.x)
            for y in (self.min.y, self.max.y)
            for z in (self.min.z, self.max.z)
        )


@dataclass(frozen=True, slots=True)
class StudReference:
    """A stud primitive placed by a part, in the part's own coordinates."""

    name: str
    """Casefolded primitive stem, e.g. ``stud`` or ``stud4``."""

    description: str
    """The primitive's header description, e.g. ``Stud Tube Open``."""

    position: Vector
    """The primitive's origin -- for top studs, the centre of the stud base."""

    up: Vector = field(default_factory=lambda: Vector(0, -1, 0))
    """Image of the stud's local up direction (0, -1, 0) under the placing
    transforms; unit length under rigid placements."""

    @property
    def is_top_stud(self) -> bool:
        """Whether this stud is an upward connector a brick can sit on.

        Excludes underside tubes and placeholder primitives by description,
        and any stud whose placing transforms point it away from up (LDraw
        up is -Y), such as the sideways front stud of a headlight brick.
        """
        lowered = self.description.casefold()
        if any(marker in lowered for marker in _NON_TOP_STUD_MARKERS):
            return False
        length = abs(self.up)
        return length > 0 and self.up.y <= -_TOP_STUD_MIN_ALIGNMENT * length
