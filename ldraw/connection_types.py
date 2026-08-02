"""Typed physical connection features and compatibility helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ldraw.geometry import Identity, Matrix, Vector


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
    OVERRIDE = "override"


class ConnectionFreedom(StrEnum):
    """Motion retained after a connection is made."""

    ROTATE = "rotate"
    SLIDE = "slide"
    DISCRETE_ROTATE = "discrete_rotate"


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
class GenericProfile:
    """Named interface for shapes which need curated compatibility."""

    name: str
    length: float = 0.0

    def scaled(self, *, radial: float, axial: float) -> GenericProfile:
        """Return this profile under axial scaling."""
        del radial
        return replace(self, length=abs(axial) * self.length)


type ConnectionProfile = (
    CylindricalProfile | FingerProfile | AnnularProfile | GenericProfile
)


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
        return replace(
            self,
            position=position + matrix * self.position,
            frame=normalized,
            profile=self.profile.scaled(radial=radial_scale, axial=y_scale),
            confidence=(
                self.confidence
                if max(radial_mismatch, shear) <= 1e-6
                else self.confidence * 0.5
            ),
        )


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


def connections_compatible(  # noqa: PLR0911 - compatibility rejects are explicit
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
    if left.kind is ConnectionKind.HINGE and right.kind is ConnectionKind.HINGE:
        return _hinges_compatible(left, right)
    if left.kind is ConnectionKind.GENERIC and right.kind is ConnectionKind.GENERIC:
        return left.group is not None and left.group == right.group
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
        case _:
            return type(left.profile) is type(right.profile)


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
    return (
        left.primary_shape is right.primary_shape
        and abs(left.mating_radius - right.mating_radius) <= radius_tolerance
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
    alignment = abs(left_axis.dot(right_axis))
    roll_alignment = (
        max(
            abs(left.radial.dot(right.radial)),
            abs(left.radial.dot(right.frame * Vector(0, 0, 1))),
        )
        if _roll_constrained(left) and _roll_constrained(right)
        else 1.0
    )
    delta = right.position - left.position
    projected = left_axis * delta.dot(left_axis)
    distance = abs(delta - projected)
    left_half = left.length / 2
    right_half = right.length / 2
    axial_gap = max(abs(delta.dot(left_axis)) - left_half - right_half, 0.0)
    return ConnectionResidual(
        distance=distance,
        axial_gap=axial_gap,
        alignment=alignment,
        roll_alignment=roll_alignment,
    )


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
    "ConnectionResidual",
    "ConnectionRole",
    "ConnectionSource",
    "CylindricalProfile",
    "CylindricalSection",
    "FingerProfile",
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
