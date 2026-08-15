"""Connection inference from reusable primitives and part-level evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from math import floor
from typing import TYPE_CHECKING, Final, cast

from ldraw.connection_types import (
    AnnularProfile,
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionProvenance,
    ConnectionRole,
    ConnectionSource,
    CylindricalProfile,
    CylindricalSection,
    FingerProfile,
    SectionShape,
    default_frame,
    frame_for_axis,
)
from ldraw.geometry import Matrix, Vector

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.part_geometry_types import BoundingBox


_CLIP_RE = re.compile(r"clip\d+[a-z]*$")
_HINGE_RE = re.compile(r"(?:clh\w*|h[12]|arm[123]|d(?:door)?hinge\w*)$")
_PIN_HOLE_RE = re.compile(r"(?:n?peghol\w*|beamhole|connhol\w*|wpinhol\w*)$")
_PIN_RE = re.compile(r"(?:connect\w*|confric\w*|wpin\w*)$")
_AXLE_RE = re.compile(r"(?:axle\w*|axl\w*|daxle\w*)$")
_AXLE_EXCLUDED_RE = re.compile(r".*(?:end|cap|edge)\w*$")
_AXIS_VECTORS = (Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1))

_SOCKET_PROVENANCE: Final[str] = "derived:stud-socket"
_SOCKET_NAME: Final[str] = "Stud Socket"
_SOCKET_GRID_PITCH: Final[int] = 20
_SOCKET_HALF_PITCH: Final[float] = _SOCKET_GRID_PITCH / 2
_SOCKET_LATERAL_MARGIN: Final[float] = 4.0
_SOCKET_MERGE_TOLERANCE: Final[float] = 0.5
_SOCKET_MERGE_TOLERANCE_SQUARED: Final[float] = _SOCKET_MERGE_TOLERANCE**2
_SOCKET_AXIS_ALIGNMENT: Final[float] = 0.999
_SOCKET_NEIGHBOR_OFFSETS: Final[tuple[tuple[int, int, int], ...]] = tuple(
    (x_offset, y_offset, z_offset)
    for x_offset in (-1, 0, 1)
    for y_offset in (-1, 0, 1)
    for z_offset in (-1, 0, 1)
)
_OPEN_SOCKET_OFFSETS: Final[tuple[tuple[int, int], ...]] = (
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
)
_SOLID_SOCKET_OFFSETS: Final[tuple[tuple[int, int], ...]] = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
)

type _GridOrientation = tuple[float, ...]
type _SocketCell = tuple[int, int, int]
type _SeenSockets = dict[_SocketCell, list[tuple[Vector, Vector]]]


@dataclass(frozen=True, slots=True)
class StudSocketDerivation:
    """Resolved sockets plus tube evidence retained for an enclosing part."""

    features: tuple[ConnectionFeature, ...]
    deferred: tuple[ConnectionFeature, ...]


@dataclass(frozen=True, slots=True)
class _TubeSocketExpansion:
    sockets: tuple[ConnectionFeature, ...]
    defer_to_parent: bool


@dataclass(frozen=True, slots=True)
class _SocketCandidate:
    index: int
    feature: ConnectionFeature
    priority: int


def primitive_connections(  # noqa: PLR0913 - primitive context is explicit
    *,
    parent_code: str,
    parent_description: str,
    stem: str,
    description: str,
    bounds: BoundingBox | None,
    position: Vector,
    matrix: Matrix,
) -> tuple[ConnectionFeature, ...]:
    """Return semantic features represented by one referenced primitive."""
    lowered = stem.casefold()
    feature: ConnectionFeature | None = None
    if lowered.startswith("stud"):
        feature = _stud_feature(
            code=parent_code,
            stem=lowered,
            description=description,
        )
    elif _CLIP_RE.fullmatch(lowered):
        feature = _clip_feature(
            code=parent_code,
            stem=lowered,
            description=description,
            bounds=bounds,
        )
    elif _HINGE_RE.fullmatch(lowered):
        feature = _hinge_feature(
            code=parent_code,
            stem=lowered,
            description=description,
            bounds=bounds,
        )
    elif _PIN_HOLE_RE.fullmatch(lowered):
        feature = _round_feature(
            code=parent_code,
            stem=lowered,
            description=description,
            bounds=bounds,
            kind=ConnectionKind.PIN_HOLE,
            role=ConnectionRole.FEMALE,
            friction=False,
        )
    elif _PIN_RE.fullmatch(lowered) and "hole" not in lowered:
        feature = _round_feature(
            code=parent_code,
            stem=lowered,
            description=description,
            bounds=bounds,
            kind=ConnectionKind.PIN,
            role=ConnectionRole.MALE,
            friction="fric" in lowered,
        )
    elif _AXLE_RE.fullmatch(lowered) and not _AXLE_EXCLUDED_RE.fullmatch(lowered):
        feature = _axle_feature(
            code=parent_code,
            parent_description=parent_description,
            stem=lowered,
            description=description,
            bounds=bounds,
            axial_scale=abs(matrix * Vector(0, 1, 0)),
        )
    if feature is None:
        return ()
    return (feature.transformed(position=position, matrix=matrix),)


def infer_part_connections(
    *,
    code: str,
    description: str,
    bounds: BoundingBox | None,
    existing: Iterable[ConnectionFeature],
    compatible_parts: tuple[str, ...] = (),
) -> tuple[ConnectionFeature, ...]:
    """Add conservative part-level bar, rim, and tyre semantics."""
    connections = list(existing)
    normalized = description.strip(" ~=_|-")
    lowered = normalized.casefold()
    if (
        bounds is not None
        and lowered.startswith("bar ")
        and not any(feature.kind is ConnectionKind.BAR for feature in connections)
        and (feature := _slender_bar(code=code, bounds=bounds)) is not None
    ):
        connections.append(feature)
    if bounds is not None and " with tyre " not in lowered:
        if lowered.startswith("wheel rim ") and not any(
            feature.kind is ConnectionKind.RIM_SEAT for feature in connections
        ):
            connections.append(
                _annular_feature(
                    code=code,
                    bounds=bounds,
                    kind=ConnectionKind.RIM_SEAT,
                    role=ConnectionRole.MALE,
                    compatible_parts=compatible_parts,
                ),
            )
        elif lowered.startswith("tyre ") and not any(
            feature.kind is ConnectionKind.TYRE_BEAD for feature in connections
        ):
            connections.append(
                _annular_feature(
                    code=code,
                    bounds=bounds,
                    kind=ConnectionKind.TYRE_BEAD,
                    role=ConnectionRole.FEMALE,
                    compatible_parts=compatible_parts,
                ),
            )
    return normalize_connections(connections)


def normalize_connections(
    features: Iterable[ConnectionFeature],
) -> tuple[ConnectionFeature, ...]:
    """Merge structural primitive halves without geometric deduplication.

    Distinct metadata identifiers are intentionally allowed to describe
    colocated interfaces. Precedence replacement is therefore performed by
    stable feature identifier in the metadata resolution pipeline.
    """
    return _merge_hole_endpoints(_merge_hinge_halves(tuple(features)))


def mark_internal_fit_occupied(
    features: Iterable[ConnectionFeature],
    *,
    assembly_code: str,
) -> tuple[ConnectionFeature, ...]:
    """Mark rim and tyre features inherited by a complete shortcut as occupied."""
    values = tuple(features)
    kinds = {feature.kind for feature in values}
    if not {ConnectionKind.RIM_SEAT, ConnectionKind.TYRE_BEAD} <= kinds:
        return values
    return tuple(
        replace(feature, occupied=True, occupied_by=assembly_code)
        if feature.kind in {ConnectionKind.RIM_SEAT, ConnectionKind.TYRE_BEAD}
        else feature
        for feature in values
    )


def derive_stud_sockets(
    features: Iterable[ConnectionFeature],
    *,
    bounds: BoundingBox | None,
    bounds_fallback: bool,
) -> tuple[ConnectionFeature, ...]:
    """Return tube receptacles projected onto the stud-mating grid."""
    return derive_stud_socket_evidence(
        features=features,
        bounds=bounds,
        bounds_fallback=bounds_fallback,
    ).features


def derive_stud_socket_evidence(
    features: Iterable[ConnectionFeature],
    *,
    bounds: BoundingBox | None,
    bounds_fallback: bool,
) -> StudSocketDerivation:
    """Project tube receptacles onto the stud-mating grid.

    Tube primitives carry their receptacle evidence on the tube centreline,
    which is a cell centre — no stud mates there except through an open
    tube's own socket. Strict stud matching keys on centreline residuals, so
    each tube is expanded into sockets on the adjacent mating centrelines:
    diagonal grid corners for open tubes, axial neighbours for solid tubes,
    validated against the part's own stud grid, and placed at the far end of
    the transformed tube primitive so snap placement mates flush. An open tube
    keeps a socket on its own centreline; a solid tube's centreline accepts
    nothing and is dropped during final catalog-part expansion.

    Stud-group primitives and subparts see only a slice of the part, so a
    tube whose grid cannot be validated in the current feature set is kept
    untouched for an enclosing resolution level to expand. Only a catalog
    part (``bounds_fallback``) may fall back to lateral bounds filtering —
    studless undersides such as tiles have no grid to validate against. A final
    bounds rejection yields no offset socket; an open tube still keeps its
    centre socket. Catalog parts retain the raw tube privately so an enclosing
    assembly can reconsider candidates against its own grid and bounds.
    """
    values = tuple(features)
    tube_flags = tuple(_is_tube_receptacle(feature) for feature in values)
    if not any(tube_flags):
        return StudSocketDerivation(features=values, deferred=())
    studs = tuple(feature for feature in values if feature.kind is ConnectionKind.STUD)
    seen = _fixed_socket_index(values=values, tube_flags=tube_flags)
    emissions, candidates, deferred = _socket_emissions(
        values=values,
        tube_flags=tube_flags,
        studs=studs,
        bounds=bounds,
        bounds_fallback=bounds_fallback,
    )
    return StudSocketDerivation(
        features=_deduplicate_socket_emissions(
            emissions=emissions,
            candidates=candidates,
            seen=seen,
        ),
        deferred=deferred,
    )


def _fixed_socket_index(
    *,
    values: tuple[ConnectionFeature, ...],
    tube_flags: tuple[bool, ...],
) -> _SeenSockets:
    seen: _SeenSockets = {}
    for feature, is_tube in zip(values, tube_flags, strict=True):
        if (
            feature.kind is ConnectionKind.STUD_RECEPTACLE
            and not is_tube
            and not _is_derived_socket(feature)
        ):
            _remember_socket(seen, position=feature.position, axis=feature.axis)
    return seen


def _socket_emissions(
    *,
    values: tuple[ConnectionFeature, ...],
    tube_flags: tuple[bool, ...],
    studs: tuple[ConnectionFeature, ...],
    bounds: BoundingBox | None,
    bounds_fallback: bool,
) -> tuple[
    list[ConnectionFeature | _SocketCandidate],
    list[_SocketCandidate],
    tuple[ConnectionFeature, ...],
]:
    emissions: list[ConnectionFeature | _SocketCandidate] = []
    candidates: list[_SocketCandidate] = []
    deferred: list[ConnectionFeature] = []
    phase_cache: dict[_GridOrientation, frozenset[tuple[int, int]]] = {}
    for feature, is_tube in zip(values, tube_flags, strict=True):
        if not is_tube:
            if _is_derived_socket(feature):
                _append_socket_candidate(
                    emissions=emissions,
                    candidates=candidates,
                    feature=feature,
                )
            else:
                emissions.append(feature)
            continue
        expansion = _tube_sockets(
            tube=feature,
            studs=studs,
            bounds=bounds,
            bounds_fallback=bounds_fallback,
            phase_cache=phase_cache,
        )
        if expansion is None:
            # The enclosing resolution level sees the complete stud grid.
            emissions.append(feature)
            continue
        if expansion.defer_to_parent:
            deferred.append(feature)
        for socket in expansion.sockets:
            _append_socket_candidate(
                emissions=emissions,
                candidates=candidates,
                feature=socket,
            )
    return emissions, candidates, tuple(deferred)


def _append_socket_candidate(
    *,
    emissions: list[ConnectionFeature | _SocketCandidate],
    candidates: list[_SocketCandidate],
    feature: ConnectionFeature,
) -> None:
    candidate = _SocketCandidate(
        index=len(candidates),
        feature=feature,
        priority=int(feature.name != _SOCKET_NAME),
    )
    candidates.append(candidate)
    emissions.append(candidate)


def _deduplicate_socket_emissions(
    *,
    emissions: list[ConnectionFeature | _SocketCandidate],
    candidates: list[_SocketCandidate],
    seen: _SeenSockets,
) -> tuple[ConnectionFeature, ...]:
    selected: set[int] = set()
    for candidate in sorted(
        candidates,
        key=lambda value: (-value.priority, value.index),
    ):
        socket = candidate.feature
        if _socket_was_seen(
            seen,
            position=socket.position,
            axis=socket.axis,
        ):
            continue
        _remember_socket(seen, position=socket.position, axis=socket.axis)
        selected.add(candidate.index)

    result: list[ConnectionFeature] = []
    for emission in emissions:
        if isinstance(emission, _SocketCandidate):
            if emission.index in selected:
                result.append(emission.feature)
        else:
            result.append(emission)
    return tuple(result)


def _is_derived_socket(feature: ConnectionFeature) -> bool:
    return (
        feature.kind is ConnectionKind.STUD_RECEPTACLE
        and _SOCKET_PROVENANCE in feature.provenance
    )


def _is_tube_receptacle(feature: ConnectionFeature) -> bool:
    return (
        feature.kind is ConnectionKind.STUD_RECEPTACLE
        and isinstance(feature.profile, CylindricalProfile)
        and "tube" in feature.name.casefold()
        and not _is_derived_socket(feature)
    )


def _tube_sockets(
    *,
    tube: ConnectionFeature,
    studs: tuple[ConnectionFeature, ...],
    bounds: BoundingBox | None,
    bounds_fallback: bool,
    phase_cache: dict[_GridOrientation, frozenset[tuple[int, int]]],
) -> _TubeSocketExpansion | None:
    axis = tube.axis
    x_direction = tube.frame * Vector(1, 0, 0)
    z_direction = tube.frame * Vector(0, 0, 1)
    center = _opening_position(tube)
    open_tube = "open" in tube.name.casefold()
    offsets = _OPEN_SOCKET_OFFSETS if open_tube else _SOLID_SOCKET_OFFSETS
    candidates = tuple(
        (
            offset_x,
            offset_z,
            center
            + x_direction * (offset_x * _SOCKET_HALF_PITCH)
            + z_direction * (offset_z * _SOCKET_HALF_PITCH),
        )
        for offset_x, offset_z in offsets
    )
    orientation = _grid_orientation(
        axis=axis,
        x_direction=x_direction,
        z_direction=z_direction,
    )
    if (phases := phase_cache.get(orientation)) is None:
        phases = _stud_grid_phases(
            studs=studs,
            axis=axis,
            x_direction=x_direction,
            z_direction=z_direction,
        )
        phase_cache[orientation] = phases
    matched = [
        candidate
        for candidate in candidates
        if _grid_phase(
            position=candidate[2],
            x_direction=x_direction,
            z_direction=z_direction,
        )
        in phases
    ]
    defer_to_parent = False
    if not matched:
        if not bounds_fallback:
            # Defer: the enclosing resolution level sees the full grid.
            return None
        matched = [
            candidate
            for candidate in candidates
            if _within_lateral_bounds(candidate[2], axis=axis, bounds=bounds)
        ]
        defer_to_parent = len(matched) < len(candidates)
    sockets: list[ConnectionFeature] = []
    if open_tube:
        sockets.append(
            replace(
                tube,
                position=center,
                provenance=(*tube.provenance, _SOCKET_PROVENANCE),
            ),
        )
    for offset_x, offset_z, position in matched:
        suffix = f"socket:{offset_x:+d}{offset_z:+d}"
        sockets.append(
            replace(
                tube,
                position=position,
                name=_SOCKET_NAME,
                feature_id=(
                    f"{tube.feature_id}:{suffix}" if tube.feature_id else suffix
                ),
                provenance=(*tube.provenance, _SOCKET_PROVENANCE),
            ),
        )
    return _TubeSocketExpansion(
        sockets=tuple(sockets),
        defer_to_parent=defer_to_parent,
    )


def _stud_grid_phases(
    *,
    studs: tuple[ConnectionFeature, ...],
    axis: Vector,
    x_direction: Vector,
    z_direction: Vector,
) -> frozenset[tuple[int, int]]:
    return frozenset(
        _grid_phase(
            position=feature.position,
            x_direction=x_direction,
            z_direction=z_direction,
        )
        for feature in studs
        if feature.axis.dot(axis) <= -_SOCKET_AXIS_ALIGNMENT
    )


def _grid_orientation(
    *,
    axis: Vector,
    x_direction: Vector,
    z_direction: Vector,
) -> _GridOrientation:
    return tuple(
        round(_component(direction, index), 9)
        for direction in (axis, x_direction, z_direction)
        for index in range(3)
    )


def _grid_phase(
    *,
    position: Vector,
    x_direction: Vector,
    z_direction: Vector,
) -> tuple[int, int]:
    return (
        round(position.dot(x_direction)) % _SOCKET_GRID_PITCH,
        round(position.dot(z_direction)) % _SOCKET_GRID_PITCH,
    )


def _opening_position(tube: ConnectionFeature) -> Vector:
    """Return the far end of the transformed, origin-anchored tube primitive."""
    return tube.position + tube.axis * tube.length


def _socket_was_seen(
    seen: _SeenSockets,
    *,
    position: Vector,
    axis: Vector,
) -> bool:
    cell_x, cell_y, cell_z = _socket_cell(position)
    for x_offset, y_offset, z_offset in _SOCKET_NEIGHBOR_OFFSETS:
        for seen_position, seen_axis in seen.get(
            (cell_x + x_offset, cell_y + y_offset, cell_z + z_offset),
            (),
        ):
            if (
                _squared_distance(first=position, second=seen_position)
                <= _SOCKET_MERGE_TOLERANCE_SQUARED
                and _axis_alignment(first=axis, second=seen_axis)
                >= _SOCKET_AXIS_ALIGNMENT
            ):
                return True
    return False


def _remember_socket(
    seen: _SeenSockets,
    *,
    position: Vector,
    axis: Vector,
) -> None:
    seen.setdefault(_socket_cell(position), []).append((position, axis))


def _socket_cell(position: Vector) -> _SocketCell:
    return (
        floor(_component(position, 0) / _SOCKET_MERGE_TOLERANCE),
        floor(_component(position, 1) / _SOCKET_MERGE_TOLERANCE),
        floor(_component(position, 2) / _SOCKET_MERGE_TOLERANCE),
    )


def _squared_distance(first: Vector, second: Vector) -> float:
    delta = first - second
    return delta.dot(delta)


def _axis_alignment(first: Vector, second: Vector) -> float:
    return first.dot(second)


def _within_lateral_bounds(
    position: Vector,
    *,
    axis: Vector,
    bounds: BoundingBox | None,
) -> bool:
    if bounds is None:
        return False
    dominant = max(range(3), key=lambda index: abs(_component(axis, index)))
    for index in range(3):
        if index == dominant:
            continue
        low = _component(bounds.min, index) + _SOCKET_LATERAL_MARGIN
        high = _component(bounds.max, index) - _SOCKET_LATERAL_MARGIN
        if not low <= _component(position, index) <= high:
            return False
    return True


def _component(value: Vector, index: int) -> float:
    match index:
        case 0:
            return float(value.x)
        case 1:
            return float(value.y)
        case 2:
            return float(value.z)
        case _:
            raise IndexError(index)


def _stud_feature(
    *,
    code: str,
    stem: str,
    description: str,
) -> ConnectionFeature:
    lowered = description.casefold()
    receptacle = "tube" in lowered or "underside" in lowered
    placeholder = "placeholder" in lowered
    kind = ConnectionKind.STUD_RECEPTACLE if receptacle else ConnectionKind.STUD
    role = ConnectionRole.FEMALE if receptacle else ConnectionRole.MALE
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=Vector(0, 0, 0),
        frame=frame_for_axis(Vector(0, -1, 0)),
        profile=CylindricalProfile(
            sections=(CylindricalSection(SectionShape.ROUND, 6.0, 4.0),),
            centered=not receptacle,
        ),
        name=description,
        feature_id=stem,
        source=ConnectionSource.PRIMITIVE,
        confidence=0.0 if placeholder else 1.0,
        owner_code=code,
        provenance=(stem,),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.PRIMITIVE,
            command=stem,
        ),
    )


def _clip_feature(
    *,
    code: str,
    stem: str,
    description: str,
    bounds: BoundingBox | None,
) -> ConnectionFeature:
    axis_index = _smallest_axis(bounds)
    length = _axis_size(bounds, axis_index, fallback=8.0)
    return ConnectionFeature(
        kind=ConnectionKind.CLIP,
        role=ConnectionRole.FEMALE,
        position=_box_center(bounds),
        frame=frame_for_axis(_AXIS_VECTORS[axis_index]),
        profile=CylindricalProfile(
            sections=(CylindricalSection(SectionShape.ROUND, 4.0, length),),
        ),
        name=description,
        feature_id=stem,
        freedoms=frozenset(
            (ConnectionFreedom.ROTATE, ConnectionFreedom.SLIDE),
        ),
        source=ConnectionSource.PRIMITIVE,
        confidence=0.8,
        owner_code=code,
        provenance=(stem,),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.PRIMITIVE,
            command=stem,
        ),
    )


def _hinge_feature(
    *,
    code: str,
    stem: str,
    description: str,
    bounds: BoundingBox | None,
) -> ConnectionFeature:
    lowered_description = description.casefold()
    sequence = (4.5, 8.0, 4.5) if stem.startswith("clh") else ()
    length = _axis_size(bounds, 1, fallback=sum(sequence) or 8.0)
    if not sequence:
        sequence = (length,)
    return ConnectionFeature(
        kind=ConnectionKind.HINGE,
        role=ConnectionRole.NEUTRAL,
        position=_box_center(bounds),
        frame=default_frame(),
        profile=FingerProfile(
            sequence=sequence,
            radius=6.0,
            first_role=(
                ConnectionRole.FEMALE
                if "single finger" in lowered_description
                else ConnectionRole.MALE
            ),
            detents=(
                tuple(
                    index * 22.5
                    for index in range(_hinge_position_count(lowered_description))
                )
                if stem.startswith("clh")
                else ()
            ),
        ),
        name=description,
        feature_id=stem,
        group="click_hinge" if stem.startswith("clh") else "hinge",
        freedoms=frozenset(
            (
                ConnectionFreedom.DISCRETE_ROTATE
                if stem.startswith("clh")
                else ConnectionFreedom.ROTATE,
            ),
        ),
        source=ConnectionSource.PRIMITIVE,
        confidence=0.75,
        owner_code=code,
        provenance=(stem,),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.PRIMITIVE,
            command=stem,
        ),
    )


def _hinge_position_count(description: str) -> int:
    match = re.search(r"(\d+)-position", description)
    return int(match.group(1)) if match is not None else 9


def _round_feature(  # noqa: PLR0913 - semantic feature fields are explicit
    *,
    code: str,
    stem: str,
    description: str,
    bounds: BoundingBox | None,
    kind: ConnectionKind,
    role: ConnectionRole,
    friction: bool,
) -> ConnectionFeature:
    length = _axis_size(bounds, 1, fallback=20.0)
    radius = (
        6.0
        if kind is ConnectionKind.PIN_HOLE
        else _radial_radius(bounds, axis_index=1, fallback=6.0)
    )
    origin_anchored = stem.startswith(("peghol", "npeghol"))
    center = Vector(0, 0, 0) if origin_anchored else _box_center(bounds)
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=center,
        frame=default_frame(),
        profile=CylindricalProfile(
            sections=(CylindricalSection(SectionShape.ROUND, radius, length),),
            centered=not origin_anchored,
            friction=friction,
        ),
        name=description,
        feature_id=stem,
        freedoms=frozenset((ConnectionFreedom.ROTATE, ConnectionFreedom.SLIDE)),
        source=ConnectionSource.PRIMITIVE,
        confidence=0.9,
        owner_code=code,
        provenance=(stem,),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.PRIMITIVE,
            command=stem,
        ),
    )


def _axle_feature(  # noqa: PLR0913 - semantic feature fields are explicit
    *,
    code: str,
    parent_description: str,
    stem: str,
    description: str,
    bounds: BoundingBox | None,
    axial_scale: float,
) -> ConnectionFeature:
    normalized_parent = parent_description.strip(" ~=_|-").casefold()
    unscaled_length = _axis_size(bounds, 1, fallback=1.0)
    male = (
        normalized_parent.startswith("technic axle ")
        and "hole" not in normalized_parent
    ) or unscaled_length * axial_scale > 4.0
    return ConnectionFeature(
        kind=ConnectionKind.AXLE if male else ConnectionKind.AXLE_HOLE,
        role=ConnectionRole.MALE if male else ConnectionRole.FEMALE,
        position=(
            Vector(0, 0, 0)
            if not male and unscaled_length <= 2.5
            else _box_center(bounds)
        ),
        frame=default_frame(),
        profile=CylindricalProfile(
            sections=(
                CylindricalSection(
                    SectionShape.AXLE,
                    _radial_radius(bounds, axis_index=1, fallback=6.0),
                    unscaled_length,
                ),
            ),
            centered=male,
        ),
        name=description,
        feature_id=stem,
        freedoms=frozenset((ConnectionFreedom.SLIDE,)),
        source=ConnectionSource.PRIMITIVE,
        confidence=0.85,
        owner_code=code,
        provenance=(stem,),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.PRIMITIVE,
            command=stem,
        ),
    )


def _slender_bar(
    *,
    code: str,
    bounds: BoundingBox,
) -> ConnectionFeature | None:
    sizes = (bounds.size.x, bounds.size.y, bounds.size.z)
    axis_index = max(range(3), key=sizes.__getitem__)
    radial_sizes = tuple(
        size for index, size in enumerate(sizes) if index != axis_index
    )
    if max(radial_sizes) > 14 or sizes[axis_index] < 8:
        return None
    return ConnectionFeature(
        kind=ConnectionKind.BAR,
        role=ConnectionRole.MALE,
        position=_box_center(bounds),
        frame=frame_for_axis(_AXIS_VECTORS[axis_index]),
        profile=CylindricalProfile(
            sections=(
                CylindricalSection(
                    SectionShape.ROUND,
                    min(radial_sizes) / 2,
                    sizes[axis_index],
                ),
            ),
        ),
        name="inferred bar",
        feature_id="bar",
        freedoms=frozenset((ConnectionFreedom.ROTATE, ConnectionFreedom.SLIDE)),
        source=ConnectionSource.HEURISTIC,
        confidence=0.65,
        owner_code=code,
        provenance=("part bounds and Bar description",),
        connection_provenance=ConnectionProvenance(
            source=ConnectionSource.HEURISTIC,
            command="part bounds and Bar description",
        ),
    )


def _annular_feature(
    *,
    code: str,
    bounds: BoundingBox,
    kind: ConnectionKind,
    role: ConnectionRole,
    compatible_parts: tuple[str, ...],
) -> ConnectionFeature:
    sizes = (bounds.size.x, bounds.size.y, bounds.size.z)
    axis_index = min(range(3), key=sizes.__getitem__)
    radial_sizes = tuple(
        size for index, size in enumerate(sizes) if index != axis_index
    )
    source = (
        ConnectionSource.SHORTCUT if compatible_parts else ConnectionSource.HEURISTIC
    )
    evidence = "official wheel/tyre shortcut" if compatible_parts else "part bounds"
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=_box_center(bounds),
        frame=frame_for_axis(_AXIS_VECTORS[axis_index]),
        profile=AnnularProfile(
            radius=max(radial_sizes) / 2,
            width=sizes[axis_index],
        ),
        name="inferred rim seat"
        if kind is ConnectionKind.RIM_SEAT
        else "inferred tyre bead",
        feature_id=kind.value,
        freedoms=frozenset((ConnectionFreedom.ROTATE,)),
        source=source,
        confidence=0.9 if compatible_parts else 0.45,
        owner_code=code,
        compatible_parts=compatible_parts,
        provenance=(evidence,),
        connection_provenance=ConnectionProvenance(
            source=source,
            command=evidence,
        ),
    )


def _merge_hole_endpoints(
    features: tuple[ConnectionFeature, ...],
) -> tuple[ConnectionFeature, ...]:
    pending = list(features)
    merged: list[ConnectionFeature] = []
    while pending:
        feature = pending.pop(0)
        if not _is_hole_endpoint(feature):
            merged.append(feature)
            continue
        match_index = next(
            (
                index
                for index, candidate in enumerate(pending)
                if _opposite_endpoint(feature, candidate)
            ),
            None,
        )
        if match_index is None:
            merged.append(feature)
            continue
        candidate = pending.pop(match_index)
        feature_profile = cast("CylindricalProfile", feature.profile)
        candidate_profile = cast("CylindricalProfile", candidate.profile)
        distance = abs(candidate.position - feature.position)
        middle = feature.position + 0.5 * (candidate.position - feature.position)
        axis = (candidate.position - feature.position).normalized()
        radius = min(
            feature_profile.mating_radius,
            candidate_profile.mating_radius,
        )
        merged.append(
            replace(
                feature,
                position=middle,
                frame=frame_for_axis(axis, radial=feature.radial),
                profile=CylindricalProfile(
                    sections=(
                        CylindricalSection(
                            feature_profile.primary_shape,
                            radius,
                            distance,
                        ),
                    ),
                ),
                feature_id=f"{feature.feature_id}:through",
                provenance=tuple(
                    dict.fromkeys((*feature.provenance, *candidate.provenance)),
                ),
            ),
        )
    return tuple(merged)


def _merge_hinge_halves(
    features: tuple[ConnectionFeature, ...],
) -> tuple[ConnectionFeature, ...]:
    pending = list(features)
    merged: list[ConnectionFeature] = []
    while pending:
        feature = pending.pop(0)
        if not _is_hinge_half(feature):
            merged.append(feature)
            continue
        match_index = next(
            (
                index
                for index, candidate in enumerate(pending)
                if _matching_hinge_half(feature, candidate)
            ),
            None,
        )
        if match_index is None:
            merged.append(feature)
            continue
        candidate = pending.pop(match_index)
        merged.append(
            replace(
                feature,
                position=0.5 * (feature.position + candidate.position),
                feature_id=f"{feature.feature_id}:complete",
                provenance=tuple(
                    dict.fromkeys((*feature.provenance, *candidate.provenance)),
                ),
            ),
        )
    return tuple(merged)


def _is_hinge_half(feature: ConnectionFeature) -> bool:
    return (
        feature.kind is ConnectionKind.HINGE
        and isinstance(feature.profile, FingerProfile)
        and "half dual finger" in feature.name.casefold()
    )


def _matching_hinge_half(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> bool:
    if not _is_hinge_half(right) or abs(left.axis.dot(right.axis)) < 0.999:
        return False
    delta = right.position - left.position
    axial = abs(delta.dot(left.axis))
    radial = abs(delta - left.axis * delta.dot(left.axis))
    left_profile = cast("FingerProfile", left.profile)
    right_profile = cast("FingerProfile", right.profile)
    return axial <= 0.1 and radial <= left_profile.radius + right_profile.radius + 0.5


def _is_hole_endpoint(feature: ConnectionFeature) -> bool:
    return (
        feature.kind in {ConnectionKind.PIN_HOLE, ConnectionKind.AXLE_HOLE}
        and isinstance(feature.profile, CylindricalProfile)
        and not feature.profile.centered
        and feature.length <= 2.5
    )


def _opposite_endpoint(
    left: ConnectionFeature,
    right: ConnectionFeature,
) -> bool:
    if not _is_hole_endpoint(right) or left.kind is not right.kind:
        return False
    delta = right.position - left.position
    if abs(delta) <= 2.5 or left.axis.dot(right.axis) > -0.99:
        return False
    along = left.axis * delta.dot(left.axis)
    return abs(delta - along) <= 0.1


def same_interface(left: ConnectionFeature, right: ConnectionFeature) -> bool:
    """Whether two features describe the same colocated physical interface."""
    if left.kind is not right.kind or abs(left.position - right.position) > 0.05:
        return False
    return abs(left.axis.dot(right.axis)) >= 0.999


def _box_center(bounds: BoundingBox | None) -> Vector:
    if bounds is None:
        return Vector(0, 0, 0)
    return 0.5 * (bounds.min + bounds.max)


def _smallest_axis(bounds: BoundingBox | None) -> int:
    if bounds is None:
        return 1
    sizes = (bounds.size.x, bounds.size.y, bounds.size.z)
    return min(range(3), key=sizes.__getitem__)


def _axis_size(
    bounds: BoundingBox | None,
    axis_index: int,
    *,
    fallback: float,
) -> float:
    if bounds is None:
        return fallback
    return float((bounds.size.x, bounds.size.y, bounds.size.z)[axis_index])


def _radial_radius(
    bounds: BoundingBox | None,
    *,
    axis_index: int,
    fallback: float,
) -> float:
    if bounds is None:
        return fallback
    sizes = (bounds.size.x, bounds.size.y, bounds.size.z)
    radial = tuple(size for index, size in enumerate(sizes) if index != axis_index)
    return float(min(radial) / 2)


__all__ = [
    "infer_part_connections",
    "mark_internal_fit_occupied",
    "normalize_connections",
    "primitive_connections",
]
