"""LDCad features implementation."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from ldraw._connection_common import (
    _NEGATIVE_Y_FRAME,
    _boolean,
    _finite_float,
    _float_tuple,
    _matrix,
    _MetadataValueError,
    _ParsedCommand,
    _role,
    _vector,
)
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionProvenance,
    ConnectionRole,
    ConnectionSource,
    CylindricalCaps,
    CylindricalProfile,
    CylindricalSection,
    FingerProfile,
    GenericBounds,
    GenericBoundsKind,
    GenericMatch,
    GenericPlacement,
    GenericProfile,
    SectionShape,
)
from ldraw.diagnostics import DiagnosticCode
from ldraw.geometry import Identity, Vector

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ldraw._connection_results import ShadowConnectionResult


def _feature_instances(
    *,
    code: str,
    command: _ParsedCommand,
    source: ConnectionSource,
    provenance: ConnectionProvenance,
    seen_ids: dict[str, int],
) -> tuple[ConnectionFeature, ...]:
    options = command.options
    base = _feature_for_command(code=code, command=command)
    orientation = _matrix(options.get("ori"), default=Identity())
    position = _vector(options.get("pos"), default=Vector(0, 0, 0))
    offsets = _grid_offsets(options.get("grid"))
    metadata_id = options.get("id")
    if metadata_id is not None:
        occurrence = seen_ids.get(metadata_id.casefold(), 0)
        seen_ids[metadata_id.casefold()] = occurrence + 1
    else:
        occurrence = 0
    features: list[ConnectionFeature] = []
    for instance, offset in enumerate(offsets):
        if metadata_id is None:
            feature_id = f"{command.kind.casefold()}@L{command.line_number}:I{instance}"
        elif len(offsets) == 1 and occurrence == 0:
            feature_id = metadata_id
        else:
            feature_id = f"{metadata_id}@L{command.line_number}:I{instance}"
        projected = replace(
            base,
            position=position + orientation * offset,
            # LDCad cylinder/finger lengths extend along local -Y.  Keep the
            # outward mating frame for female cylinders; profile.direction
            # retains their original negative-Y physical section locations.
            frame=orientation
            * (
                Identity()
                if isinstance(base.profile, CylindricalProfile)
                and base.role is ConnectionRole.FEMALE
                else _NEGATIVE_Y_FRAME
            ),
            feature_id=feature_id,
            metadata_id=metadata_id,
            source=source,
            connection_provenance=provenance,
            scale_inheritance=options.get("scale", "none").casefold(),
            mirror_inheritance=options.get(
                "mirror",
                "cor" if command.kind == "SNAP_CYL" else "none",
            ).casefold(),
        )
        from ldraw.connection_regions import engagement_regions  # noqa: PLC0415

        features.extend(engagement_regions(projected))
    return tuple(features)


def _suffix_first_repeated_id(
    feature: ConnectionFeature,
    *,
    raw_id: str,
) -> ConnectionFeature:
    if (
        feature.metadata_id is None
        or feature.metadata_id.casefold() != raw_id.casefold()
        or feature.feature_id != feature.metadata_id
    ):
        return feature
    line_number = (
        feature.connection_provenance.line_number
        if feature.connection_provenance is not None
        else 0
    )
    return replace(feature, feature_id=f"{raw_id}@L{line_number}:I0")


def _feature_for_command(
    *,
    code: str,
    command: _ParsedCommand,
) -> ConnectionFeature:
    match command.kind:
        case "SNAP_CYL":
            return _cylinder_feature(code=code, options=command.options)
        case "SNAP_CLP":
            return _clip_feature(code=code, options=command.options)
        case "SNAP_FGR":
            return _finger_feature(code=code, options=command.options)
        case "SNAP_GEN":
            return _generic_feature(code=code, options=command.options)
        case _:
            message = f"unsupported feature command {command.kind}"
            raise ValueError(message)


def _cylinder_feature(
    *,
    code: str,
    options: Mapping[str, str],
) -> ConnectionFeature:
    identifier = options.get("id")
    group = options.get("group")
    sections = _sections(options["secs"])
    role = _role(options.get("gender"))
    slide = _boolean(options.get("slide"), default=False)
    kind = _cylinder_kind(
        role=role,
        sections=sections,
        label=" ".join(value for value in (identifier, group) if value),
        slide=slide,
        caps=_caps(options.get("caps")),
    )
    freedoms = {ConnectionFreedom.ROTATE}
    if slide:
        freedoms.add(ConnectionFreedom.SLIDE)
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=CylindricalProfile(
            sections=sections,
            centered=_boolean(options.get("center"), default=False),
            direction=-1 if role is ConnectionRole.FEMALE else 1,
            caps=_caps(options.get("caps")),
        ),
        name=identifier or group or "LDCad cylinder",
        group=group,
        freedoms=frozenset(freedoms),
        owner_code=code,
        editor_slide=slide,
    )


def _clip_feature(
    *,
    code: str,
    options: Mapping[str, str],
) -> ConnectionFeature:
    identifier = options.get("id")
    group = options.get("group")
    if (gender := options.get("gender")) is not None and _role(
        gender
    ) is not ConnectionRole.FEMALE:
        message = "SNAP_CLP gender must be female"
        raise ValueError(message)
    freedoms = {ConnectionFreedom.ROTATE}
    if _boolean(options.get("slide"), default=False):
        freedoms.add(ConnectionFreedom.SLIDE)
    radius = _finite_float(options.get("radius", "4"))
    length = _finite_float(options.get("length", "8"))
    if radius <= 0 or length <= 0:
        message = "SNAP_CLP radius and length must be positive"
        raise ValueError(message)
    return ConnectionFeature(
        kind=ConnectionKind.CLIP,
        role=ConnectionRole.FEMALE,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=CylindricalProfile(
            sections=(
                CylindricalSection(
                    SectionShape.ROUND,
                    radius,
                    length,
                ),
            ),
            centered=_boolean(options.get("center"), default=False),
            direction=-1,
        ),
        name=identifier or group or "LDCad clip",
        group=group,
        freedoms=frozenset(freedoms),
        owner_code=code,
    )


def _finger_feature(
    *,
    code: str,
    options: Mapping[str, str],
) -> ConnectionFeature:
    identifier = options.get("id")
    group = options.get("group")
    sequence = _float_tuple(options["seq"])
    radius = _finite_float(options.get("radius", "6"))
    if any(value <= 0 for value in sequence) or radius <= 0:
        message = "SNAP_FGR sequence and radius must be positive"
        raise ValueError(message)
    return ConnectionFeature(
        kind=ConnectionKind.HINGE,
        role=ConnectionRole.NEUTRAL,
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=FingerProfile(
            sequence=sequence,
            radius=radius,
            first_role=_role(options.get("genderofs")),
            centered=_boolean(options.get("center"), default=True),
        ),
        name=identifier or group or "LDCad fingers",
        group=group,
        freedoms=frozenset({ConnectionFreedom.ROTATE}),
        owner_code=code,
    )


def _generic_feature(
    *,
    code: str,
    options: Mapping[str, str],
) -> ConnectionFeature:
    identifier = options.get("id")
    group = options.get("group")
    placement = GenericPlacement(options.get("placement", "aligned").casefold())
    match_mode = GenericMatch(options.get("match", "shape").casefold())
    freedoms = (
        frozenset((ConnectionFreedom.FREE_ROTATE,))
        if placement is GenericPlacement.FREE
        else frozenset()
    )
    bounds = _generic_bounds(options.get("bounding"))
    return ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=_role(options.get("gender")),
        position=Vector(0, 0, 0),
        frame=Identity(),
        profile=GenericProfile(
            name=group or identifier or "generic",
            length=_generic_length(bounds),
            bounds=bounds,
            match=match_mode,
            placement=placement,
        ),
        name=identifier or group or "LDCad generic",
        group=group,
        freedoms=freedoms,
        owner_code=code,
    )


def _transform_include(  # noqa: PLR0913 - include context is explicit
    included: ShadowConnectionResult,
    *,
    command: _ParsedCommand,
    owner_code: str,
    reference: str,
    effective_source: ConnectionSource,
    marker: str | None = None,
) -> ShadowConnectionResult:
    options = command.options
    position = _vector(options.get("pos"), default=Vector(0, 0, 0))
    orientation = _matrix(options.get("ori"), default=Identity())
    if scale_value := options.get("scale"):
        scale = _vector(scale_value, default=Vector(1, 1, 1))
        orientation = orientation.scale(scale.x, scale.y, scale.z)
    if orientation.det() < 0 and any(
        feature.mirror_inheritance == "none" for feature in included.features
    ):
        message = "include reflection is not allowed by inherited metadata"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    offsets = _grid_offsets(options.get("grid"))
    marker = marker or options.get("id") or f"snap_incl@L{command.line_number}"
    include_slide = _boolean(options.get("slide"), default=False)
    transformed: list[ConnectionFeature] = []
    for instance, offset in enumerate(offsets):
        prefix = f"{marker}:I{instance}"
        for feature in included.features:
            child_id = feature.feature_id or feature.name or feature.kind.value
            provenance = feature.connection_provenance
            if provenance is not None:
                provenance = replace(
                    provenance,
                    source=effective_source,
                    include_chain=(*provenance.include_chain, prefix, reference),
                )
            transformed.append(
                replace(
                    feature.transformed(
                        position=position + orientation * offset,
                        matrix=orientation,
                        inherit=False,
                    ),
                    owner_code=owner_code,
                    feature_id=f"{prefix}/{child_id}",
                    metadata_id=options.get("id") or feature.metadata_id,
                    source=effective_source,
                    freedoms=(
                        feature.freedoms | {ConnectionFreedom.SLIDE}
                        if include_slide
                        else feature.freedoms
                    ),
                    connection_provenance=provenance,
                    provenance=(
                        () if provenance is not None else (f"SNAP_INCL {reference}",)
                    ),
                ),
            )
    return replace(included, features=tuple(transformed))


def _validate_common_options(
    kind: str,
    options: Mapping[str, str],
) -> None:
    if "pos" in options:
        _vector(options["pos"], default=Vector(0, 0, 0))
    if "ori" in options:
        _matrix(options["ori"], default=Identity())
    for key in ("center", "slide"):
        if key in options:
            _boolean(options[key], default=False)
    if "gender" in options and kind == "SNAP_FGR":
        _role(options["gender"])
    _validate_scale_option(kind, options)
    if "mirror" in options and options["mirror"].casefold() not in {
        "none",
        "cor",
        "corx",
        "corz",
    }:
        message = f"invalid mirror mode {options['mirror']!r}"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    if "grid" in options:
        _grid_offsets(options["grid"])


def _validate_scale_option(kind: str, options: Mapping[str, str]) -> None:
    """SNAP_INCL scales are vectors; every other record names an inherit mode."""
    if kind == "SNAP_INCL" and (scale_value := options.get("scale")) is not None:
        scale = _vector(scale_value, default=Vector(1, 1, 1))
        if min(abs(scale.x), abs(scale.y), abs(scale.z)) == 0:
            message = "include scale transform must be non-zero"
            raise _MetadataValueError(
                message,
                code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
            )
        if not math.isclose(abs(scale.x), abs(scale.z), abs_tol=1e-6):
            message = "include radial scale must match on X and Z"
            raise _MetadataValueError(
                message,
                code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
            )
    if (
        kind != "SNAP_INCL"
        and "scale" in options
        and options["scale"].casefold() not in {"none", "yonly", "ronly", "yandr"}
    ):
        message = f"invalid scale inheritance mode {options['scale']!r}"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )


def _sections(value: str) -> tuple[CylindricalSection, ...]:
    tokens = value.split()
    if not tokens or len(tokens) % 3:
        message = "secs must contain shape/radius/length triples"
        raise ValueError(message)
    raw = [
        (
            tokens[index].upper(),
            _finite_float(tokens[index + 1]),
            _finite_float(tokens[index + 2]),
        )
        for index in range(0, len(tokens), 3)
    ]
    sections: list[CylindricalSection] = []
    for index, (shape_code, radius, length) in enumerate(raw):
        if radius <= 0 or length <= 0:
            message = "section radius and length must be positive"
            raise ValueError(message)
        flexible = shape_code in {"_L", "L_"}
        resolved_shape = shape_code
        if flexible:
            neighbour = index - 1 if shape_code.startswith("_") else index + 1
            if not 0 <= neighbour < len(raw) or raw[neighbour][0] in {"_L", "L_"}:
                message = "flexible section needs an adjacent rigid section"
                raise ValueError(message)
            resolved_shape = raw[neighbour][0]
        try:
            shape = {
                "R": SectionShape.ROUND,
                "A": SectionShape.AXLE,
                "S": SectionShape.SQUARE,
            }[resolved_shape]
        except KeyError as error:
            message = f"unsupported cylinder section shape {shape_code!r}"
            raise ValueError(message) from error
        sections.append(CylindricalSection(shape, radius, length, flexible))
    return tuple(sections)


def _cylinder_kind(
    *,
    role: ConnectionRole,
    sections: tuple[CylindricalSection, ...],
    label: str,
    slide: bool,
    caps: CylindricalCaps,
) -> ConnectionKind:
    if any(section.shape is SectionShape.AXLE for section in sections):
        return (
            ConnectionKind.AXLE
            if role is ConnectionRole.MALE
            else ConnectionKind.AXLE_HOLE
        )
    if "stud" in label.casefold() or _is_stud_shaped(sections, caps=caps):
        return (
            ConnectionKind.STUD
            if role is ConnectionRole.MALE
            else ConnectionKind.STUD_RECEPTACLE
        )
    if role is ConnectionRole.MALE and _is_bar_shaped(sections, slide=slide, caps=caps):
        return ConnectionKind.BAR
    return (
        ConnectionKind.PIN if role is ConnectionRole.MALE else ConnectionKind.PIN_HOLE
    )


def _min_rigid_radius(sections: tuple[CylindricalSection, ...]) -> float:
    return min(
        (section.radius for section in sections if not section.flexible),
        default=0.0,
    )


def _is_stud_shaped(
    sections: tuple[CylindricalSection, ...],
    *,
    caps: CylindricalCaps,
) -> bool:
    rigid_count = sum(not section.flexible for section in sections)
    length = sum(section.length for section in sections)
    return (
        rigid_count == 1
        and abs(_min_rigid_radius(sections) - 6.0) <= 0.25
        and (
            abs(length - 4.0) <= 0.5
            or (sections[0].shape is SectionShape.SQUARE and 4 <= length <= 24)
        )
        and caps is not CylindricalCaps.NONE
    )


def _is_bar_shaped(
    sections: tuple[CylindricalSection, ...],
    *,
    slide: bool,
    caps: CylindricalCaps,
) -> bool:
    return abs(_min_rigid_radius(sections) - 4.0) <= 0.35 and (
        slide or caps is CylindricalCaps.TWO
    )


def _caps(value: str | None) -> CylindricalCaps:
    return CylindricalCaps((value or "one").casefold())


def _generic_bounds(value: str | None) -> GenericBounds | None:
    if value is None:
        return GenericBounds(GenericBoundsKind.POINT)
    tokens = value.split()
    if not tokens:
        return GenericBounds(GenericBoundsKind.POINT)
    kind = {
        "pnt": GenericBoundsKind.POINT,
        "point": GenericBoundsKind.POINT,
        "box": GenericBoundsKind.BOX,
        "cube": GenericBoundsKind.BOX,
        "cyl": GenericBoundsKind.CYLINDER,
        "cylinder": GenericBoundsKind.CYLINDER,
        "sph": GenericBoundsKind.SPHERE,
        "sphere": GenericBoundsKind.SPHERE,
    }.get(tokens[0].casefold())
    if kind is None:
        message = f"unsupported generic bounding shape {tokens[0]!r}"
        raise ValueError(message)
    dimensions = _float_tuple(" ".join(tokens[1:]))
    expected = {
        GenericBoundsKind.POINT: 0,
        GenericBoundsKind.BOX: 3,
        GenericBoundsKind.CYLINDER: 2,
        GenericBoundsKind.SPHERE: 1,
    }[kind]
    if tokens[0].casefold() == "cube":
        if len(dimensions) != 1:
            message = "cube bounding shape needs one size"
            raise ValueError(message)
        dimensions = dimensions * 3
    elif len(dimensions) != expected:
        message = f"{kind.value} bounding shape needs {expected} value(s)"
        raise ValueError(message)
    if any(value <= 0 for value in dimensions):
        message = "generic bounding dimensions must be positive"
        raise ValueError(message)
    return GenericBounds(kind, dimensions)


def _generic_length(bounds: GenericBounds | None) -> float:
    if bounds is None or not bounds.dimensions:
        return 0.0
    if bounds.kind is GenericBoundsKind.BOX:
        return 2 * bounds.dimensions[1]
    if bounds.kind is GenericBoundsKind.CYLINDER:
        return bounds.dimensions[1]
    return 2 * bounds.dimensions[0]


def _grid_offsets(value: str | None) -> tuple[Vector, ...]:
    if not value:
        return (Vector(0, 0, 0),)
    tokens = value.split()
    numeric_count = sum(token.casefold() != "c" for token in tokens)
    dimensions = 2 if numeric_count == 4 else 3 if numeric_count == 6 else 0
    if not dimensions:
        message = "grid must contain X/Z or X/Y/Z counts and steps"
        raise _MetadataValueError(message, code=DiagnosticCode.CONNECTION_INVALID_GRID)
    counts, centered, index = _grid_axes(tokens, dimensions)
    if len(tokens) - index != dimensions:
        message = "grid has an invalid number of step values"
        raise _MetadataValueError(message, code=DiagnosticCode.CONNECTION_INVALID_GRID)
    try:
        steps = [_finite_float(token) for token in tokens[index:]]
    except ValueError as error:
        message = f"grid steps must be finite numbers: {error}"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_GRID,
        ) from error
    if dimensions == 2:
        x_count, z_count = counts
        x_centered, z_centered = centered
        x_step, z_step = steps
        y_count = 1
        y_values = ((0, False, 0.0),)
    else:
        x_count, y_count, z_count = counts
        x_centered, y_centered, z_centered = centered
        x_step, y_step, z_step = steps
        y_values = tuple((value, y_centered, y_step) for value in range(y_count))
    return tuple(
        Vector(
            _grid_coordinate(
                x_index,
                x_count,
                centered=x_centered,
                step=x_step,
            ),
            _grid_coordinate(
                y_index,
                y_count,
                centered=y_centered,
                step=y_step,
            ),
            _grid_coordinate(
                z_index,
                z_count,
                centered=z_centered,
                step=z_step,
            ),
        )
        for x_index in range(x_count)
        for y_index, y_centered, y_step in y_values
        for z_index in range(z_count)
    )


def _grid_axes(
    tokens: list[str],
    dimensions: int,
) -> tuple[list[int], list[bool], int]:
    """Parse per-axis counts and centering flags; return the next token index."""
    index = 0
    counts: list[int] = []
    centered: list[bool] = []
    for _ in range(dimensions):
        is_centered = index < len(tokens) and tokens[index].casefold() == "c"
        index += int(is_centered)
        if index >= len(tokens):
            message = "grid is missing an axis count"
            raise _MetadataValueError(
                message,
                code=DiagnosticCode.CONNECTION_INVALID_GRID,
            )
        try:
            count = int(tokens[index])
        except ValueError as error:
            message = f"grid count must be an integer, got {tokens[index]!r}"
            raise _MetadataValueError(
                message,
                code=DiagnosticCode.CONNECTION_INVALID_GRID,
            ) from error
        if count <= 0:
            message = "grid counts must be positive"
            raise _MetadataValueError(
                message,
                code=DiagnosticCode.CONNECTION_INVALID_GRID,
            )
        counts.append(count)
        centered.append(is_centered)
        index += 1
    return counts, centered, index


def _grid_coordinate(
    index: int,
    count: int,
    *,
    centered: bool,
    step: float,
) -> float:
    return (index - (count - 1) / 2 if centered else index) * step
