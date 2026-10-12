"""Addressable cylindrical regions and positive physical engagement checks."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionKind,
    ConnectionRole,
    CylindricalCaps,
    CylindricalProfile,
    CylindricalSection,
    SectionShape,
)


def engagement_regions(feature: ConnectionFeature) -> tuple[ConnectionFeature, ...]:
    """Split mixed axle/round ports without relocating their physical sections."""
    profile = feature.profile
    if not isinstance(profile, CylindricalProfile) or not {
        SectionShape.AXLE,
        SectionShape.ROUND,
    } <= {section.shape for section in profile.sections}:
        return (feature,)
    groups: list[list[CylindricalSection]] = []
    for section in profile.sections:
        if groups and groups[-1][-1].shape == section.shape:
            groups[-1].append(section)
        else:
            groups.append([section])
    offset = -profile.length / 2 if profile.centered else 0.0
    regions: list[ConnectionFeature] = []
    for index, sections in enumerate(groups):
        male = feature.role is ConnectionRole.MALE
        kind = (
            (ConnectionKind.AXLE if male else ConnectionKind.AXLE_HOLE)
            if sections[0].shape is SectionShape.AXLE
            else (ConnectionKind.PIN if male else ConnectionKind.PIN_HOLE)
        )
        region = replace(
            feature,
            kind=kind,
            position=feature.position + feature.axis * (profile.direction * offset),
            feature_id=f"{feature.feature_id or 'cylinder'}:region:{index}",
            profile=replace(
                profile,
                sections=tuple(sections),
                centered=False,
                caps=_region_caps(
                    feature, first=index == 0, last=index == len(groups) - 1
                ),
            ),
        )
        regions.append(region)
        offset += region.length
    return tuple(regions)


def _region_caps(
    feature: ConnectionFeature, *, first: bool, last: bool
) -> CylindricalCaps:
    profile = cast("CylindricalProfile", feature.profile)
    caps = profile.caps
    if caps is CylindricalCaps.ONE:
        caps = (
            CylindricalCaps.A
            if feature.role is ConnectionRole.MALE
            else CylindricalCaps.B
        )
    a = first and caps in {CylindricalCaps.A, CylindricalCaps.TWO}
    b = last and caps in {CylindricalCaps.B, CylindricalCaps.TWO}
    return (
        CylindricalCaps.TWO
        if a and b
        else CylindricalCaps.A
        if a
        else CylindricalCaps.B
        if b
        else CylindricalCaps.NONE
    )


def _section_spans(
    feature: ConnectionFeature, *, axis: ConnectionFeature
) -> tuple[tuple[float, float, CylindricalSection], ...]:
    profile = cast("CylindricalProfile", feature.profile)
    origin = (feature.position - axis.position).dot(axis.axis)
    direction = feature.axis.dot(axis.axis) * profile.direction
    offset = -profile.length / 2 if profile.centered else 0.0
    values: list[tuple[float, float, CylindricalSection]] = []
    for section in profile.sections:
        start = origin + direction * offset
        end = start + direction * section.length
        values.append((min(start, end), max(start, end), section))
        offset += section.length
    return tuple(values)


def supported_engagement(left: ConnectionFeature, right: ConnectionFeature) -> bool:
    """Require positive compatible overlap and respect supported blocked ends.

    This checks interface profiles, without certifying seating, collisions,
    friction, physical support, or rigidity of the containing parts.
    """
    if not isinstance(left.profile, CylindricalProfile) or not isinstance(
        right.profile, CylindricalProfile
    ):
        return True
    male, female = (left, right) if left.role is ConnectionRole.MALE else (right, left)
    first = _section_spans(male, axis=male)
    second = _section_spans(female, axis=male)
    if not first or not second or _crosses_blocked_end(male, female):
        return False
    engaged = False
    for low, high, section in first:
        for other_low, other_high, other in second:
            if min(high, other_high) - max(low, other_low) <= 1e-7:
                continue
            if section.flexible or other.flexible:
                continue
            if not _shapes_fit(section, other, male=male, female=female):
                return False
            engaged = True
    return engaged


def _shapes_fit(
    male_section: CylindricalSection,
    female_section: CylindricalSection,
    *,
    male: ConnectionFeature,
    female: ConnectionFeature,
) -> bool:
    bearing = (
        male.kind is ConnectionKind.AXLE and female.kind is ConnectionKind.PIN_HOLE
    )
    square_socket = (
        male.kind is ConnectionKind.STUD
        and female.kind is ConnectionKind.STUD_RECEPTACLE
        and female_section.shape is SectionShape.SQUARE
    )
    shape = male_section.shape is female_section.shape or bearing or square_socket
    return shape and -0.35 <= female_section.radius - male_section.radius <= 0.35


def _crosses_blocked_end(male: ConnectionFeature, female: ConnectionFeature) -> bool:
    profile = cast("CylindricalProfile", female.profile)
    caps = profile.caps
    if caps is CylindricalCaps.TWO:
        return True
    if caps is CylindricalCaps.ONE:
        caps = CylindricalCaps.B
    start = -profile.length / 2 if profile.centered else 0.0
    start *= profile.direction
    end = start + profile.direction * profile.length
    spans = _section_spans(male, axis=female)
    low = min(item[0] for item in spans)
    high = max(item[1] for item in spans)
    blocked = start if caps is CylindricalCaps.A else end
    if caps is CylindricalCaps.NONE:
        return False
    return (
        low < blocked - 0.25 if blocked < (start + end) / 2 else high > blocked + 0.25
    )
