"""LDCad common implementation."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionRole,
    _feature_origin,
    frame_for_axis,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.geometry import Matrix, Vector

if TYPE_CHECKING:
    from pathlib import Path

    from ldraw._connection_results import ShadowConnectionResult

_SHADOW_LINE_RE = re.compile(
    r"^\s*0\s+!LDCAD\s+(SNAP_\w+)\b(.*)$",
    re.IGNORECASE,
)

_SUSPECT_SNAP_RE = re.compile(r"^\s*0?\s*!LDCAD\s+SNAP", re.IGNORECASE)

_VALID_OPTION_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

_NEGATIVE_Y_FRAME = Matrix([[1, 0, 0], [0, -1, 0], [0, 0, -1]])

_SUPPORTED_OPTIONS: dict[str, frozenset[str]] = {
    "SNAP_CLEAR": frozenset(("id",)),
    "SNAP_INCL": frozenset(("id", "ref", "pos", "ori", "scale", "grid", "slide")),
    "SNAP_CYL": frozenset(
        (
            "id",
            "group",
            "pos",
            "ori",
            "scale",
            "mirror",
            "gender",
            "secs",
            "caps",
            "grid",
            "center",
            "slide",
        ),
    ),
    "SNAP_CLP": frozenset(
        (
            "id",
            "group",
            "pos",
            "ori",
            "radius",
            "length",
            "center",
            "slide",
            "scale",
            "mirror",
            "gender",
        ),
    ),
    "SNAP_FGR": frozenset(
        (
            "id",
            "group",
            "pos",
            "ori",
            "genderofs",
            "gender",
            "seq",
            "radius",
            "center",
            "scale",
            "mirror",
        ),
    ),
    "SNAP_GEN": frozenset(
        (
            "id",
            "group",
            "pos",
            "ori",
            "gender",
            "bounding",
            "scale",
            "mirror",
            "match",
            "placement",
        ),
    ),
}

_REQUIRED_OPTIONS = {
    "SNAP_INCL": frozenset(("ref",)),
    "SNAP_CYL": frozenset(("secs",)),
    "SNAP_FGR": frozenset(("seq",)),
}


class _MetadataValueError(ValueError):
    """Invalid metadata value carrying a structured diagnostic code."""

    def __init__(
        self,
        message: str,
        *,
        code: DiagnosticCode = DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _ParsedCommand:
    kind: str
    options: dict[str, str]
    line_number: int
    raw: str


def _overlay_features(
    existing: Iterable[ConnectionFeature],
    incoming: Iterable[ConnectionFeature],
    *,
    diagnostics: list[Diagnostic] | None,
) -> list[ConnectionFeature]:
    values = list(existing)
    for feature in incoming:
        feature_key = (
            feature.feature_id.casefold() if feature.feature_id is not None else None
        )
        replacement = next(
            (
                index
                for index, candidate in enumerate(values)
                if feature_key is not None
                and candidate.feature_id is not None
                and candidate.feature_id.casefold() == feature_key
            ),
            None,
        )
        if replacement is None:
            values.append(feature)
            continue
        previous = values[replacement]
        values[replacement] = feature
        if diagnostics is not None and previous != feature:
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_FEATURE_CONFLICT,
                    (
                        f"connection feature {feature.feature_id!r} from "
                        f"{_feature_origin(feature)} overrides "
                        f"{_feature_origin(previous)}"
                    ),
                    path=(
                        feature.connection_provenance.path
                        if feature.connection_provenance is not None
                        else None
                    ),
                    line_number=(
                        feature.connection_provenance.line_number
                        if feature.connection_provenance is not None
                        else None
                    ),
                    offending_value=feature.feature_id,
                ),
            )
    return values


def _normalized_code(value: str) -> str:
    normalized = value.replace("\\", "/").casefold().strip("/")
    normalized = normalized.removesuffix(".dat")
    if normalized.startswith("s/"):
        return f"parts/{normalized}"
    if normalized.startswith(("8/", "48/")):
        return f"p/{normalized}"
    return normalized


def _canonical_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    values = cycle[:-1] if len(cycle) > 1 and cycle[0] == cycle[-1] else cycle
    rotations = tuple(values[index:] + values[:index] for index in range(len(values)))
    return min(rotations)


def _deduplicate_cycle_diagnostics(
    diagnostics: Iterable[Diagnostic],
) -> tuple[Diagnostic, ...]:
    seen_cycles: set[object] = set()
    values: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic.code is DiagnosticCode.CONNECTION_INCLUDE_CYCLE:
            key = diagnostic.offending_value
            if key in seen_cycles:
                continue
            seen_cycles.add(key)
        values.append(diagnostic)
    return tuple(values)


def _vector(value: str | None, *, default: Vector) -> Vector:
    if value is None:
        return default
    numbers = _float_tuple(value)
    if len(numbers) != 3:
        message = "vector must contain three numbers"
        raise ValueError(message)
    return Vector(*numbers)


def _matrix(value: str | None, *, default: Matrix) -> Matrix:
    if value is None:
        return default
    numbers = _float_tuple(value)
    if len(numbers) != 9:
        message = "orientation matrix must contain nine numbers"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    matrix = Matrix([list(numbers[0:3]), list(numbers[3:6]), list(numbers[6:9])])
    if matrix.is_singular():
        message = "orientation matrix must not be singular"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    if not matrix.is_orthonormal(tolerance=5e-3):
        message = "orientation matrix must be orthonormal"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    if matrix.det() < 0:
        message = "orientation matrix must not mirror; use the mirror option"
        raise _MetadataValueError(
            message,
            code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
        )
    return frame_for_axis(
        matrix * Vector(0, 1, 0),
        radial=matrix * Vector(1, 0, 0),
    )


def _float_tuple(value: str) -> tuple[float, ...]:
    return tuple(_finite_float(token) for token in value.split())


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        message = f"numeric value must be finite, got {value!r}"
        raise ValueError(message)
    return result


def _role(value: str | None) -> ConnectionRole:
    normalized = (value or "M").casefold()
    if normalized in {"m", "male"}:
        return ConnectionRole.MALE
    if normalized in {"f", "female"}:
        return ConnectionRole.FEMALE
    message = f"gender must be M or F, got {value!r}"
    raise ValueError(message)


def _boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    lowered = value.casefold()
    if lowered not in {"true", "false"}:
        message = f"expected true or false, got {value!r}"
        raise ValueError(message)
    return lowered == "true"


def _diagnostic(  # noqa: PLR0913
    code: DiagnosticCode,
    message: str,
    *,
    line_number: int | None = None,
    path: Path | None = None,
    offending_value: object | None = None,
    cause: BaseException | None = None,
) -> Diagnostic:
    return Diagnostic(
        line_number=line_number,
        message=message,
        severity=Severity.WARNING,
        code=code,
        path=path,
        offending_value=offending_value,
        cause=cause,
    )


IncludeResolver = Callable[[_ParsedCommand, tuple[str, ...]], "ShadowConnectionResult"]
