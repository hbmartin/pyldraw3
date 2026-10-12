"""Equivalent physical interfaces retain the strongest available evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ldraw.connection_types import ConnectionSource, CylindricalProfile

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.connection_types import ConnectionFeature

_PRIORITY = {source: index for index, source in enumerate(ConnectionSource)}


def deduplicate_interfaces(
    features: Iterable[ConnectionFeature],
) -> tuple[ConnectionFeature, ...]:
    """Merge equivalent ports, preserving distinct locations, profiles, and groups."""
    result: dict[tuple[object, ...], ConnectionFeature] = {}
    for feature in features:
        profile = feature.profile
        if isinstance(profile, CylindricalProfile) and profile.friction is not None:
            profile = replace(profile, friction=None)
        key = (
            feature.kind,
            feature.role,
            feature.group,
            profile,
            feature.compatible_parts,
            feature.occupied,
            *(
                round(value, 6)
                for value in (
                    feature.position.x,
                    feature.position.y,
                    feature.position.z,
                    *feature.frame.flatten(),
                )
            ),
        )
        previous = result.get(key)
        if previous is None or (_PRIORITY[feature.source], feature.confidence) > (
            _PRIORITY[previous.source],
            previous.confidence,
        ):
            result[key] = feature
    return tuple(result.values())
