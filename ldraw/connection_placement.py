"""Reuse validated local frames when placing repeated parts with rigid rotations."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from ldraw.connection_types import METADATA_SOURCES

if TYPE_CHECKING:
    from ldraw.connection_types import ConnectionFeature
    from ldraw.geometry import Matrix, Vector
    from ldraw.parts import Parts

_CACHE: WeakKeyDictionary[
    Parts,
    dict[
        str, tuple[tuple[ConnectionFeature, ...], tuple[ConnectionFeature | None, ...]]
    ],
] = WeakKeyDictionary()


def place_connections(
    parts: Parts,
    *,
    code: str,
    features: tuple[ConnectionFeature, ...],
    position: Vector,
    matrix: Matrix,
) -> tuple[ConnectionFeature, ...]:
    """Place validated profiles without rebuilding unchanged unit-scale sections.

    Scales, shears, reflections, and invalid local frames use the general
    transformation path, including its metadata validity checks.
    """
    if not features:
        return ()
    if not matrix.is_orthonormal() or matrix.det() < 0:
        return tuple(
            feature.transformed(position=position, matrix=matrix)
            for feature in features
        )
    cache = _CACHE.setdefault(parts, {})
    previous = cache.get(code)
    if previous is None or previous[0] is not features:
        templates = tuple(_rigid_template(feature) for feature in features)
        cache[code] = (features, templates)
    else:
        templates = previous[1]
    return tuple(
        replace(
            template,
            position=position + matrix * feature.position,
            frame=matrix * template.frame,
        )
        if template is not None
        else feature.transformed(position=position, matrix=matrix)
        for feature, template in zip(features, templates, strict=True)
    )


def _rigid_template(feature: ConnectionFeature) -> ConnectionFeature | None:
    if not feature.frame.is_orthonormal():
        return None
    reflected = feature.frame.det() < 0
    frame = feature._mirror_corrected(feature.frame, reflected=reflected)  # noqa: SLF001
    confidence = (
        0.0
        if reflected
        and feature.source in METADATA_SOURCES
        and feature.mirror_inheritance == "none"
        else feature.confidence
    )
    return replace(feature, frame=frame, confidence=confidence)
