"""Typed physical connection features and compatibility helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from ldraw.geometry import Identity, Matrix, Vector

if TYPE_CHECKING:
    from pathlib import Path


class ConnectionKind(StrEnum):
    """Physical interface represented by a connection feature."""

    STUD = "stud"
    STUD_RECEPTACLE = "stud_receptacle"
    BAR = "bar"
    CLIP = "clip"
    PIN = "pin"
    PIN_HOLE = "pin_hole"
    AXLE = "axle"
    AXLE_HOLE = "axle_hole"
    HINGE = "hinge"
    RIM_SEAT = "rim_seat"
    TYRE_BEAD = "tyre_bead"
    GENERIC = "generic"


class ConnectionRole(StrEnum):
    """Mating role of a feature."""

    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class ConnectionSource(StrEnum):
    """Evidence from which a connection feature was derived."""

    HEURISTIC = "heuristic"
    PRIMITIVE = "primitive"
    SHORTCUT = "shortcut"
    LDCAD_INLINE = "ldcad_inline"
    LDCAD_SHADOW = "ldcad_shadow"
    STUDIO = "studio"
    OVERRIDE = "override"


class ConnectionStatus(StrEnum):
    """Confidence tier assigned to a placed feature contact."""

    CONFIRMED = "confirmed"
    POTENTIAL = "potential"


class ConnectionFreedom(StrEnum):
    """Motion retained after a connection is made."""

    ROTATE = "rotate"
    SLIDE = "slide"
    DISCRETE_ROTATE = "discrete_rotate"
    FREE_ROTATE = "free_rotate"


class CylindricalCaps(StrEnum):
    """Blocked ends of an LDCad cylindrical connection profile."""

    NONE = "none"
    ONE = "one"
    TWO = "two"
    A = "a"
    B = "b"


class GenericBoundsKind(StrEnum):
    """Bounding shape used to rank and validate a generic interface."""

    POINT = "point"
    BOX = "box"
    CYLINDER = "cylinder"
    SPHERE = "sphere"


class GenericMatch(StrEnum):
    """LDCad matching rule for generic interfaces."""

    SHAPE = "shape"
    SIZE = "size"
    GROUP = "group"


class GenericPlacement(StrEnum):
    """Orientation behavior retained by a generic interface."""

    ALIGNED = "aligned"
    FREE = "free"


class SectionShape(StrEnum):
    """Cross-section used by one cylindrical profile section."""

    ROUND = "round"
    AXLE = "axle"
    SQUARE = "square"


@dataclass(frozen=True, slots=True)
class CylindricalSection:
    """One axial section of a pin, hole, axle, bar, or clip profile."""

    shape: SectionShape
    radius: float
    length: float
    flexible: bool = False

    def scaled(self, *, radial: float, axial: float) -> CylindricalSection:
        """Return this section under radial and axial scaling."""
        return replace(
            self,
            radius=abs(radial) * self.radius,
            length=abs(axial) * self.length,
        )


@dataclass(frozen=True, slots=True)
class CylindricalProfile:
    """Axial profile composed of round, axle, or square sections."""

    sections: tuple[CylindricalSection, ...]
    centered: bool = True
    friction: bool = False
    caps: CylindricalCaps = CylindricalCaps.NONE

    @property
    def length(self) -> float:
        """Total length along the feature axis."""
        return sum(section.length for section in self.sections)

    @property
    def primary_shape(self) -> SectionShape:
        """Most constraining cross-section in the profile."""
        shapes = {section.shape for section in self.sections}
        if SectionShape.AXLE in shapes:
            return SectionShape.AXLE
        if SectionShape.SQUARE in shapes:
            return SectionShape.SQUARE
        return SectionShape.ROUND

    @property
    def mating_radius(self) -> float:
        """Smallest rigid radius, used for broad compatibility checks."""
        rigid = tuple(
            section.radius for section in self.sections if not section.flexible
        )
        values = rigid or tuple(section.radius for section in self.sections)
        return min(values, default=0.0)

    def scaled(self, *, radial: float, axial: float) -> CylindricalProfile:
        """Return this profile under radial and axial scaling."""
        return replace(
            self,
            sections=tuple(
                section.scaled(radial=radial, axial=axial) for section in self.sections
            ),
        )


@dataclass(frozen=True, slots=True)
class FingerProfile:
    """Interlocking hinge fingers arranged along the hinge axis."""

    sequence: tuple[float, ...]
    radius: float
    first_role: ConnectionRole = ConnectionRole.MALE
    detents: tuple[float, ...] = ()
    centered: bool = True

    @property
    def length(self) -> float:
        """Total finger span along the hinge axis."""
        return sum(self.sequence)

    def scaled(self, *, radial: float, axial: float) -> FingerProfile:
        """Return this profile under radial and axial scaling."""
        return replace(
            self,
            sequence=tuple(abs(axial) * value for value in self.sequence),
            radius=abs(radial) * self.radius,
        )


@dataclass(frozen=True, slots=True)
class AnnularProfile:
    """Axisymmetric tyre bead or wheel-rim seat."""

    radius: float
    width: float
    offset: float = 0.0

    @property
    def length(self) -> float:
        """Axial width of the fitted interface."""
        return self.width

    def scaled(self, *, radial: float, axial: float) -> AnnularProfile:
        """Return this profile under radial and axial scaling."""
        return replace(
            self,
            radius=abs(radial) * self.radius,
            width=abs(axial) * self.width,
            offset=axial * self.offset,
        )


@dataclass(frozen=True, slots=True)
class GenericBounds:
    """One validated LDCad generic bounding shape."""

    kind: GenericBoundsKind
    dimensions: tuple[float, ...] = ()

    def scaled(self, *, radial: float, axial: float) -> GenericBounds:
        """Return the bounds under radial and axial scaling."""
        match self.kind, self.dimensions:
            case GenericBoundsKind.BOX, (x, y, z):
                dimensions = (abs(radial) * x, abs(axial) * y, abs(radial) * z)
            case GenericBoundsKind.CYLINDER, (radius, length):
                dimensions = (abs(radial) * radius, abs(axial) * length)
            case GenericBoundsKind.SPHERE, (radius,):
                dimensions = (abs(radial) * radius,)
            case _:
                dimensions = self.dimensions
        return replace(self, dimensions=dimensions)


@dataclass(frozen=True, slots=True)
class GenericProfile:
    """Named interface for shapes which need curated compatibility."""

    name: str
    length: float = 0.0
    bounds: GenericBounds | None = None
    match: GenericMatch = GenericMatch.SHAPE
    placement: GenericPlacement = GenericPlacement.ALIGNED

    def scaled(self, *, radial: float, axial: float) -> GenericProfile:
        """Return this profile under axial scaling."""
        return replace(
            self,
            length=abs(axial) * self.length,
            bounds=(
                self.bounds.scaled(radial=radial, axial=axial)
                if self.bounds is not None
                else None
            ),
        )


type ConnectionProfile = (
    CylindricalProfile | FingerProfile | AnnularProfile | GenericProfile
)


@dataclass(frozen=True, slots=True)
class ConnectionProvenance:
    """Structured origin of a normalized connection feature."""

    source: ConnectionSource
    path: Path | None = None
    archive_member: str | None = None
    line_number: int | None = None
    command: str | None = None
    include_chain: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectionFeature:
    """One physical connection interface in a part's local coordinates.

    The feature frame uses local +Y as its axis. The X and Z axes retain
    cross-section roll, which is significant for Technic axles and clips.
    """

    kind: ConnectionKind
    role: ConnectionRole
    position: Vector
    frame: Matrix
    profile: ConnectionProfile
    name: str = ""
    feature_id: str | None = None
    group: str | None = None
    freedoms: frozenset[ConnectionFreedom] = field(default_factory=frozenset)
    source: ConnectionSource = ConnectionSource.PRIMITIVE
    confidence: float = 1.0
    owner_code: str | None = None
    compatible_parts: tuple[str, ...] = ()
    occupied: bool = False
    occupied_by: str | None = None
    provenance: tuple[str, ...] = ()
    metadata_id: str | None = None
    connection_provenance: ConnectionProvenance | None = None
    scale_inheritance: str = "yandr"
    mirror_inheritance: str = "none"

    def __post_init__(self) -> None:
        if self.connection_provenance is not None:
            provenance = self.connection_provenance
            location = provenance.archive_member or (
                str(provenance.path)
                if provenance.path is not None
                else provenance.command or provenance.source.value
            )
            if provenance.line_number is not None:
                location = f"{location}:{provenance.line_number}"
            if provenance.include_chain:
                location = f"{location} via {' > '.join(provenance.include_chain)}"
            object.__setattr__(self, "provenance", (location,))

    @property
    def axis(self) -> Vector:
        """Unit axis, or the zero vector after a degenerate transform."""
        axis = self.frame * Vector(0, 1, 0)
        return axis / length if (length := abs(axis)) else Vector(0, 0, 0)

    @property
    def radial(self) -> Vector:
        """Unit roll reference, or zero after a degenerate transform."""
        radial = self.frame * Vector(1, 0, 0)
        return radial / length if (length := abs(radial)) else Vector(0, 0, 0)

    @property
    def length(self) -> float:
        """Axial span represented by the profile."""
        return self.profile.length

    def transformed(
        self,
        *,
        position: Vector,
        matrix: Matrix,
        inherit: bool = True,
    ) -> ConnectionFeature:
        """Return this feature transformed by an LDraw placement."""
        raw_frame = matrix * self.frame
        x_axis = raw_frame * Vector(1, 0, 0)
        y_axis = raw_frame * Vector(0, 1, 0)
        z_axis = raw_frame * Vector(0, 0, 1)
        x_scale = abs(x_axis)
        y_scale = abs(y_axis)
        z_scale = abs(z_axis)
        if min(x_scale, y_scale, z_scale) == 0 or raw_frame.is_singular():
            return replace(
                self,
                position=position + matrix * self.position,
                frame=raw_frame,
                confidence=0.0,
            )
        normalized = _orthonormalized_frame(x_axis, y_axis, z_axis)
        reflected = raw_frame.det() < 0
        if reflected and self.mirror_inheritance in {"cor", "corx", "corz"}:
            correction = (
                Matrix([[-1, 0, 0], [0, 1, 0], [0, 0, 1]])
                if self.mirror_inheritance != "corz"
                else Matrix([[1, 0, 0], [0, 1, 0], [0, 0, -1]])
            )
            normalized = normalized * correction
        radial_scale = (x_scale + z_scale) / 2
        radial_mismatch = abs(x_scale - z_scale) / max(x_scale, z_scale)
        normalized_x = x_axis / x_scale
        normalized_y = y_axis / y_scale
        normalized_z = z_axis / z_scale
        shear = max(
            abs(normalized_x.dot(normalized_y)),
            abs(normalized_x.dot(normalized_z)),
            abs(normalized_y.dot(normalized_z)),
        )
        applied_radial, applied_axial = (
            _inherited_scales(
                self.scale_inheritance,
                radial=radial_scale,
                axial=y_scale,
            )
            if inherit
            else (radial_scale, y_scale)
        )
        has_radial_scale = not math.isclose(radial_scale, 1.0, abs_tol=1e-6)
        has_axial_scale = not math.isclose(y_scale, 1.0, abs_tol=1e-6)
        scale_allowed = {
            "none": not has_radial_scale and not has_axial_scale,
            "yonly": not has_radial_scale,
            "ronly": not has_axial_scale,
            "yandr": True,
        }.get(self.scale_inheritance.casefold(), False)
        invalid_metadata_transform = self.source in {
            ConnectionSource.LDCAD_INLINE,
            ConnectionSource.LDCAD_SHADOW,
            ConnectionSource.STUDIO,
        } and (
            (inherit and not scale_allowed)
            or radial_mismatch > 1e-6
            or shear > 1e-6
            or (reflected and self.mirror_inheritance == "none")
        )
        return replace(
            self,
            position=position + matrix * self.position,
            frame=normalized,
            profile=self.profile.scaled(
                radial=applied_radial,
                axial=applied_axial,
            ),
            confidence=(
                0.0
                if invalid_metadata_transform
                else self.confidence
                if max(radial_mismatch, shear) <= 1e-6
                else self.confidence * 0.5
            ),
        )


def _inherited_scales(
    mode: str,
    *,
    radial: float,
    axial: float,
) -> tuple[float, float]:
    match mode.casefold():
        case "none":
            return 1.0, 1.0
        case "yonly":
            return 1.0, axial
        case "ronly":
            return radial, 1.0
        case _:
            return radial, axial


@dataclass(frozen=True, slots=True)
class PartCompatibility:
    """Evidence that two complete parts fit one another."""

    first: str
    second: str
    relation: str
    source: ConnectionSource
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionResidual:
    """Geometric residuals between two compatible features."""

    distance: float
    axial_gap: float
    alignment: float
    roll_alignment: float = 1.0
    entry_face_gap: float | None = None
    penetration: float | None = None


@dataclass(frozen=True, slots=True)
class SnapTransform:
    """Rigid placement aligning one local feature to another feature."""

    position: Vector
    matrix: Matrix


_KIND_PAIRS = {
    frozenset((ConnectionKind.STUD, ConnectionKind.STUD_RECEPTACLE)),
    frozenset((ConnectionKind.BAR, ConnectionKind.CLIP)),
    frozenset((ConnectionKind.PIN, ConnectionKind.PIN_HOLE)),
    frozenset((ConnectionKind.AXLE, ConnectionKind.AXLE_HOLE)),
    frozenset((ConnectionKind.RIM_SEAT, ConnectionKind.TYRE_BEAD)),
}
_X_REFLECTION = Matrix([[-1, 0, 0], [0, 1, 0], [0, 0, 1]])


def connections_compatible(  # noqa: C901, PLR0911
    left: ConnectionFeature,
    right: ConnectionFeature,
    *,
    radius_tolerance: float = 0.35,
) -> bool:
    """Return whether two features are physically eligible to mate."""
    if radius_tolerance < 0:
        message = "radius tolerance must be non-negative"
        raise ValueError(message)
    if not _features_available(left, right):
        return False
    if (
        left.role is not ConnectionRole.NEUTRAL
        and right.role is not ConnectionRole.NEUTRAL
        and left.role is right.role
    ):
        return False
    if (
        left.group is not None or right.group is not None
    ) and left.group != right.group:
        return False
    if left.kind is ConnectionKind.HINGE and right.kind is ConnectionKind.HINGE:
        return _hinges_compatible(left, right)
    if left.kind is ConnectionKind.GENERIC and right.kind is ConnectionKind.GENERIC:
        return _generic_profiles_compatible(left, right)
    if frozenset((left.kind, right.kind)) not in _KIND_PAIRS:
        return False
    if not _part_restrictions_allow(left, right):
        return False
    match left.profile, right.profile:
        case (
            CylindricalProfile() as left_profile,
            CylindricalProfile() as right_profile,
        ):
            return _cylindrical_profiles_compatible(
                left_profile,
                right_profile,
                radius_tolerance=radius_tolerance,
            )
        case AnnularProfile() as left_profile, AnnularProfile() as right_profile:
            if left.compatible_parts or right.compatible_parts:
                return True
            return (
                abs(left_profile.radius - right_profile.radius) <= radius_tolerance
                and min(left_profile.width, right_profile.width) > 0
            )
        case _:
            return type(left.profile) is type(right.profile)


def _generic_profiles_compatible(  # noqa: PLR0911
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> bool:
    if not isinstance(left.profile, GenericProfile) or not isinstance(
        right.profile,
        GenericProfile,
    ):
        return False
    if left.group != right.group and (
        left.group is not None or right.group is not None
    ):
        return False
    mode = (
        GenericMatch.GROUP
        if GenericMatch.GROUP in {left.profile.match, right.profile.match}
        else (
            GenericMatch.SIZE
            if GenericMatch.SIZE in {left.profile.match, right.profile.match}
            else GenericMatch.SHAPE
        )
    )
    if mode is GenericMatch.GROUP:
        return left.group == right.group
    if left.profile.bounds is None or right.profile.bounds is None:
        return left.group is not None and left.group == right.group
    if left.profile.bounds.kind is not right.profile.bounds.kind:
        return False
    if mode is GenericMatch.SHAPE:
        return True
    return len(left.profile.bounds.dimensions) == len(
        right.profile.bounds.dimensions,
    ) and all(
        math.isclose(left_value, right_value, abs_tol=0.35)
        for left_value, right_value in zip(
            left.profile.bounds.dimensions,
            right.profile.bounds.dimensions,
            strict=True,
        )
    )


def _features_available(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> bool:
    return not (
        left.occupied or right.occupied or left.confidence <= 0 or right.confidence <= 0
    )


def _part_restrictions_allow(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> bool:
    return _owner_allowed(left, right.owner_code) and _owner_allowed(
        right,
        left.owner_code,
    )


def _owner_allowed(feature: ConnectionFeature, owner_code: str | None) -> bool:
    return (
        not feature.compatible_parts
        or owner_code is None
        or owner_code.casefold()
        in {code.casefold() for code in feature.compatible_parts}
    )


def _cylindrical_profiles_compatible(
    left: CylindricalProfile,
    right: CylindricalProfile,
    *,
    radius_tolerance: float,
) -> bool:
    left_rigid = tuple(section for section in left.sections if not section.flexible)
    right_rigid = tuple(section for section in right.sections if not section.flexible)
    return bool(left_rigid and right_rigid) and any(
        left_section.shape is right_section.shape
        and abs(left_section.radius - right_section.radius) <= radius_tolerance
        for left_section in left_rigid
        for right_section in right_rigid
    )


def _hinges_compatible(left: ConnectionFeature, right: ConnectionFeature) -> bool:
    if left.group is not None and right.group is not None and left.group != right.group:
        return False
    if not (
        left.group == right.group == "click_hinge"
        and isinstance(left.profile, FingerProfile)
        and isinstance(right.profile, FingerProfile)
    ):
        return True
    return (
        len(left.profile.sequence) == len(right.profile.sequence)
        and all(
            math.isclose(left_length, right_length, abs_tol=0.1)
            for left_length, right_length in zip(
                left.profile.sequence,
                right.profile.sequence,
                strict=True,
            )
        )
        and left.profile.first_role is not right.profile.first_role
    )


def connection_residual(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> ConnectionResidual:
    """Return centerline, axial, and orientation residuals for two features."""
    left_axis = left.axis
    right_axis = right.axis
    free_placement = any(
        isinstance(feature.profile, GenericProfile)
        and feature.profile.placement is GenericPlacement.FREE
        for feature in (left, right)
    )
    alignment = 1.0 if free_placement else abs(left_axis.dot(right_axis))
    if free_placement:
        roll_alignment = 1.0
    elif _roll_constrained(left) and _roll_constrained(right):
        roll_alignment = max(
            abs(left.radial.dot(right.radial)),
            abs(left.radial.dot(right.frame * Vector(0, 0, 1))),
        )
    elif isinstance(left.profile, FingerProfile) and isinstance(
        right.profile,
        FingerProfile,
    ):
        roll_alignment = _finger_roll_alignment(left, right)
    else:
        roll_alignment = 1.0
    delta = right.position - left.position
    projected = left_axis * delta.dot(left_axis)
    distance = abs(delta - projected)
    left_interval = _feature_interval(left, origin=0.0, direction=1.0)
    right_interval = _feature_interval(
        right,
        origin=delta.dot(left_axis),
        direction=right_axis.dot(left_axis),
    )
    axial_gap = max(
        left_interval[0] - right_interval[1],
        right_interval[0] - left_interval[1],
        0.0,
    )
    return ConnectionResidual(
        distance=distance,
        axial_gap=axial_gap,
        alignment=alignment,
        roll_alignment=roll_alignment,
    )


def _feature_interval(
    feature: ConnectionFeature,
    *,
    origin: float,
    direction: float,
) -> tuple[float, float]:
    centered = (
        feature.profile.centered
        if isinstance(feature.profile, CylindricalProfile | FingerProfile)
        else True
    )
    local = (
        (-feature.length / 2, feature.length / 2) if centered else (0.0, feature.length)
    )
    values = (origin + direction * local[0], origin + direction * local[1])
    return min(values), max(values)


def _finger_roll_alignment(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> float:
    left_profile = left.profile
    right_profile = right.profile
    if not isinstance(left_profile, FingerProfile) or not isinstance(
        right_profile,
        FingerProfile,
    ):
        return 1.0
    detents = tuple(dict.fromkeys((*left_profile.detents, *right_profile.detents)))
    if not detents:
        return 1.0
    cosine = max(-1.0, min(1.0, left.radial.dot(right.radial)))
    angle = math.degrees(math.acos(cosine)) % 360
    difference = min(abs((angle - detent + 180) % 360 - 180) for detent in detents)
    return math.cos(math.radians(difference))


def snap_transform(
    moving: ConnectionFeature,
    target: ConnectionFeature,
) -> SnapTransform:
    """Return a rigid transform placing ``moving`` onto ``target``.

    Cylindrical interfaces are direction-symmetric, so the target frame is
    flipped when that gives the smaller axis rotation. Cross-section roll is
    preserved for axle profiles. Candidate frames are matched to the moving
    frame's handedness, so the delta is always a proper rotation and a part
    placed with a mirroring matrix is never reflected.
    """
    _validate_snap_frame(moving, argument="moving")
    _validate_snap_frame(target, argument="target")
    moving_left_handed = moving.frame.det() < 0
    target_frame = max(
        (
            frame * _X_REFLECTION if (frame.det() < 0) != moving_left_handed else frame
            for frame in _equivalent_target_frames(moving, target)
        ),
        key=lambda frame: _frame_similarity(moving.frame, frame),
    )
    rotation = target_frame * moving.frame.transpose()
    return SnapTransform(
        position=target.position - rotation * moving.position,
        matrix=rotation,
    )


def _validate_snap_frame(
    feature: ConnectionFeature,
    *,
    argument: str,
) -> None:
    if feature.frame.is_orthonormal():
        return
    message = f"{argument} feature frame must be orthonormal"
    raise ValueError(message)


def _roll_constrained(feature: ConnectionFeature) -> bool:
    return isinstance(
        feature.profile, CylindricalProfile
    ) and feature.profile.primary_shape in {SectionShape.AXLE, SectionShape.SQUARE}


def _equivalent_target_frames(
    moving: ConnectionFeature,
    target: ConnectionFeature,
) -> tuple[Matrix, ...]:
    target_axis = target.axis if moving.axis.dot(target.axis) >= 0 else -1 * target.axis
    if (
        isinstance(moving.profile, CylindricalProfile)
        and isinstance(target.profile, CylindricalProfile)
        and moving.profile.primary_shape is SectionShape.ROUND
        and target.profile.primary_shape is SectionShape.ROUND
    ) or (
        isinstance(moving.profile, AnnularProfile)
        and isinstance(target.profile, AnnularProfile)
    ):
        return (frame_for_axis(target_axis, radial=moving.radial),)

    base = target.frame
    if (base * Vector(0, 1, 0)).dot(target_axis) < 0:
        base = base * Matrix([[-1, 0, 0], [0, -1, 0], [0, 0, 1]])
    if _roll_constrained(moving) and _roll_constrained(target):
        quarter_turns = (
            Identity(),
            Matrix([[0, 0, 1], [0, 1, 0], [-1, 0, 0]]),
            Matrix([[-1, 0, 0], [0, 1, 0], [0, 0, -1]]),
            Matrix([[0, 0, -1], [0, 1, 0], [1, 0, 0]]),
        )
        return tuple(base * rotation for rotation in quarter_turns)
    return (base,)


def _frame_similarity(left: Matrix, right: Matrix) -> float:
    axes = (Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1))
    return sum((left * axis).dot(right * axis) for axis in axes)


def angular_alignment_within(alignment: float, tolerance_degrees: float) -> bool:
    """Return whether an absolute axis alignment is within a tolerance."""
    if tolerance_degrees < 0:
        message = "angular tolerance must be non-negative"
        raise ValueError(message)
    return alignment >= math.cos(math.radians(tolerance_degrees))


def _matrix_from_columns(x_axis: Vector, y_axis: Vector, z_axis: Vector) -> Matrix:
    return Matrix(
        [
            [x_axis.x, y_axis.x, z_axis.x],
            [x_axis.y, y_axis.y, z_axis.y],
            [x_axis.z, y_axis.z, z_axis.z],
        ],
    )


def _orthonormalized_frame(
    raw_x: Vector,
    raw_y: Vector,
    raw_z: Vector,
) -> Matrix:
    y_axis = raw_y.normalized()
    projected_x = raw_x - y_axis * raw_x.dot(y_axis)
    if abs(projected_x) <= 1e-12:
        projected_x = raw_z.cross(y_axis)
    x_axis = projected_x.normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    if z_axis.dot(raw_z) < 0:
        z_axis = -1 * z_axis
    return _matrix_from_columns(x_axis, y_axis, z_axis)


def frame_for_axis(axis: Vector, *, radial: Vector | None = None) -> Matrix:
    """Build an orthonormal feature frame whose local +Y follows ``axis``."""
    y_axis = axis.normalized()
    basis = (Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1))
    candidate = radial or min(basis, key=lambda value: abs(value.dot(y_axis)))
    z_axis = candidate.cross(y_axis)
    if abs(z_axis) == 0:
        candidate = min(basis, key=lambda value: abs(value.dot(y_axis)))
        z_axis = candidate.cross(y_axis)
    z_axis = z_axis.normalized()
    x_axis = y_axis.cross(z_axis).normalized()
    return _matrix_from_columns(x_axis, y_axis, z_axis)


def default_frame() -> Matrix:
    """Return the standard +Y-oriented feature frame."""
    return Identity()


__all__ = [
    "AnnularProfile",
    "ConnectionFeature",
    "ConnectionFreedom",
    "ConnectionKind",
    "ConnectionProfile",
    "ConnectionProvenance",
    "ConnectionResidual",
    "ConnectionRole",
    "ConnectionSource",
    "ConnectionStatus",
    "CylindricalCaps",
    "CylindricalProfile",
    "CylindricalSection",
    "FingerProfile",
    "GenericBounds",
    "GenericBoundsKind",
    "GenericMatch",
    "GenericPlacement",
    "GenericProfile",
    "PartCompatibility",
    "SectionShape",
    "SnapTransform",
    "angular_alignment_within",
    "connection_residual",
    "connections_compatible",
    "default_frame",
    "frame_for_axis",
    "snap_transform",
]
