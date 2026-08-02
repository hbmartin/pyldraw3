"""Studio connectivity JSON adapter."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ldraw.connection_metadata import ShadowConnectionResult
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
    GenericProfile,
    SectionShape,
    frame_for_axis,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.geometry import Vector

_CONNECTIVITY_FIELDS = frozenset(
    {
        "id",
        "type",
        "position",
        "axis",
        "gender",
        "group",
        "radius",
        "length",
        "width",
    },
)
_PART_FIELDS = frozenset({"part_id", "connections"})


@dataclass(frozen=True, slots=True)
class _StudioPart:
    code: str
    result: ShadowConnectionResult


class StudioConnectionLibrary:
    """Read the supported connectivity subset of a Studio JSON export.

    A part row with an empty or absent ``connections`` list contributes no
    authoritative evidence: heuristic and primitive features are kept and
    coverage is unchanged. Explicit clear-to-empty is an LDCad ``SNAP_CLEAR``
    or override concern.
    """

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source).expanduser()
        self._parts: dict[str, ShadowConnectionResult] = {}
        self._fallback_result = ShadowConnectionResult()
        self._load()

    def connections_for(self, code: str) -> ShadowConnectionResult:
        """Return Studio connection metadata for one normalized part code."""
        key = _part_key(code)
        result = self._parts.get(key)
        if result is not None:
            return result
        return self._fallback_result

    def _load(self) -> None:
        diagnostics: list[Diagnostic] = []
        document_id = str(self.source.resolve())
        try:
            document = json.loads(self.source.read_text(encoding="utf-8-sig"))
        except (OSError, RecursionError, UnicodeError, json.JSONDecodeError) as error:
            self._fallback_result = ShadowConnectionResult(
                diagnostics=(
                    _diagnostic(
                        f"could not read Studio connectivity JSON: {error}",
                        path=self.source,
                        cause=error,
                    ),
                ),
                source_count=1,
                invalid_record_count=1,
                document_ids=(document_id,),
            )
            return
        rows = document.get("parts") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            self._fallback_result = ShadowConnectionResult(
                diagnostics=(
                    _diagnostic(
                        "Studio connectivity document must contain a parts list",
                        path=self.source,
                        offending_value=document,
                    ),
                ),
                source_count=1,
                invalid_record_count=1,
                document_ids=(document_id,),
            )
            return
        for part_index, row in enumerate(rows):
            parsed = _studio_part(
                row,
                path=self.source,
                part_index=part_index,
                document_diagnostics=diagnostics,
            )
            if parsed is None:
                continue
            previous = self._parts.get(parsed.code)
            self._parts[parsed.code] = (
                parsed.result if previous is None else previous.combined(parsed.result)
            )
        if diagnostics:
            self._fallback_result = ShadowConnectionResult(
                diagnostics=tuple(diagnostics),
                source_count=1,
                invalid_record_count=len(diagnostics),
                document_ids=(document_id,),
            )


def _studio_part(
    value: object,
    *,
    path: Path,
    part_index: int,
    document_diagnostics: list[Diagnostic],
) -> _StudioPart | None:
    if not isinstance(value, dict) or not isinstance(value.get("part_id"), str):
        document_diagnostics.append(
            _diagnostic(
                "Studio part record has no string part_id",
                path=path,
                offending_value=value,
            ),
        )
        return None
    code = _part_key(value["part_id"])
    diagnostics = [
        _excluded_field_diagnostic(field, path=path, part_id=code)
        for field in value
        if field not in _PART_FIELDS
    ]
    rows = value.get("connections", [])
    invalid = 0
    if not isinstance(rows, list):
        invalid += 1
        diagnostics.append(
            _diagnostic(
                f"Studio connections for {code!r} must be a list",
                path=path,
                offending_value=rows,
            ),
        )
        rows = []
    features: list[ConnectionFeature] = []
    for index, row in enumerate(rows):
        normalized_row = row
        if isinstance(row, dict):
            excluded = tuple(
                field for field in row if field not in _CONNECTIVITY_FIELDS
            )
            diagnostics.extend(
                _excluded_field_diagnostic(field, path=path, part_id=code)
                for field in excluded
            )
            normalized_row = {
                field: item
                for field, item in row.items()
                if field in _CONNECTIVITY_FIELDS
            }
        try:
            features.append(
                _studio_feature(
                    normalized_row,
                    code=code,
                    path=path,
                    part_index=part_index,
                    index=index,
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            invalid += 1
            diagnostics.append(
                _diagnostic(
                    f"invalid Studio connection for {code!r}: {error}",
                    path=path,
                    offending_value=row,
                    cause=error,
                ),
            )
    identifiers = [feature.metadata_id for feature in features]
    repeated = {
        identifier.casefold()
        for identifier in identifiers
        if identifier is not None
        and sum(
            candidate is not None and candidate.casefold() == identifier.casefold()
            for candidate in identifiers
        )
        > 1
    }
    features = [
        replace(
            feature,
            feature_id=f"{feature.metadata_id}@P{part_index}:I{index}",
        )
        if feature.metadata_id is not None
        and feature.metadata_id.casefold() in repeated
        else feature
        for index, feature in enumerate(features)
    ]
    has_evidence = bool(features) or invalid > 0
    return _StudioPart(
        code,
        ShadowConnectionResult(
            features=tuple(features),
            diagnostics=tuple(diagnostics),
            source_count=int(has_evidence),
            recognized_record_count=len(features),
            unsupported_record_count=sum(
                diagnostic.code is DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION
                for diagnostic in diagnostics
            ),
            invalid_record_count=invalid,
            document_ids=(str(path.resolve()),) if has_evidence else (),
        ),
    )


def _studio_feature(
    value: object,
    *,
    code: str,
    path: Path,
    part_index: int,
    index: int,
) -> ConnectionFeature:
    if not isinstance(value, dict):
        message = "connection must be an object"
        raise TypeError(message)
    raw_type = _required_string(value, "type")
    normalized_type = raw_type.strip().casefold().replace("-", "_")
    role = _studio_role(value.get("gender"))
    position = _vector(value.get("position"), label="position")
    axis = _vector(value.get("axis"), label="axis")
    if not abs(axis):
        message = "axis cannot be zero"
        raise ValueError(message)
    raw_id = value.get("id")
    metadata_id = raw_id if isinstance(raw_id, str) and raw_id else None
    feature_id = metadata_id or f"studio@P{part_index}:I{index}"
    kind, profile, freedoms = _studio_semantics(
        normalized_type,
        role=role,
        value=value,
    )
    provenance = ConnectionProvenance(
        source=ConnectionSource.STUDIO,
        path=path,
        command=f"Studio part {part_index} connection {index}",
    )
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=position,
        frame=frame_for_axis(axis),
        profile=profile,
        name=metadata_id or f"Studio {normalized_type}",
        feature_id=feature_id,
        metadata_id=metadata_id,
        group=(str(value["group"]) if value.get("group") is not None else None),
        freedoms=freedoms,
        source=ConnectionSource.STUDIO,
        confidence=0.95,
        owner_code=code,
        provenance=(f"{path}: Studio connection {index}",),
        connection_provenance=provenance,
    )


def _studio_semantics(  # noqa: PLR0911
    kind: str,
    *,
    role: ConnectionRole,
    value: dict[str, Any],
) -> tuple[
    ConnectionKind,
    CylindricalProfile | FingerProfile | AnnularProfile | GenericProfile,
    frozenset[ConnectionFreedom],
]:
    radius = _positive_number(value.get("radius", 6.0), label="radius")
    length = _positive_number(value.get("length", 8.0), label="length")
    cylindrical = CylindricalProfile(
        (CylindricalSection(SectionShape.ROUND, radius, length),),
    )
    rotate = frozenset((ConnectionFreedom.ROTATE,))
    slide_rotate = frozenset((ConnectionFreedom.ROTATE, ConnectionFreedom.SLIDE))
    match kind:
        case "stud":
            return (
                ConnectionKind.STUD
                if role is ConnectionRole.MALE
                else ConnectionKind.STUD_RECEPTACLE,
                cylindrical,
                rotate,
            )
        case "pin" | "technic_pin":
            return (
                ConnectionKind.PIN
                if role is ConnectionRole.MALE
                else ConnectionKind.PIN_HOLE,
                cylindrical,
                slide_rotate,
            )
        case "axle":
            profile = CylindricalProfile(
                (CylindricalSection(SectionShape.AXLE, radius, length),),
            )
            return (
                ConnectionKind.AXLE
                if role is ConnectionRole.MALE
                else ConnectionKind.AXLE_HOLE,
                profile,
                slide_rotate,
            )
        case "bar" | "clip":
            bar_kind = (
                ConnectionKind.BAR
                if kind == "bar" and role is not ConnectionRole.FEMALE
                else ConnectionKind.CLIP
            )
            return bar_kind, cylindrical, slide_rotate
        case "hinge":
            return (
                ConnectionKind.HINGE,
                FingerProfile((length,), radius, first_role=role),
                rotate,
            )
        case "tyre_rim":
            width = _positive_number(value.get("width", length), label="width")
            return (
                ConnectionKind.RIM_SEAT
                if role is ConnectionRole.MALE
                else ConnectionKind.TYRE_BEAD,
                AnnularProfile(radius, width),
                rotate,
            )
        case "ball" | "ball_joint":
            return (
                ConnectionKind.GENERIC,
                GenericProfile("ball_joint", length=2 * radius),
                frozenset((ConnectionFreedom.FREE_ROTATE,)),
            )
        case "turntable":
            return ConnectionKind.GENERIC, GenericProfile("turntable"), rotate
        case _:
            message = f"unsupported connection type {kind!r}"
            raise ValueError(message)


def _studio_role(value: object) -> ConnectionRole:
    normalized = str(value or "neutral").strip().casefold()
    aliases = {
        "m": ConnectionRole.MALE,
        "male": ConnectionRole.MALE,
        "f": ConnectionRole.FEMALE,
        "female": ConnectionRole.FEMALE,
        "neutral": ConnectionRole.NEUTRAL,
        "bidirectional": ConnectionRole.NEUTRAL,
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        message = f"unsupported gender {value!r}"
        raise ValueError(message) from error


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        message = f"{key} must be a non-empty string"
        raise ValueError(message)
    return item


def _vector(value: object, *, label: str) -> Vector:
    if not isinstance(value, list | tuple) or len(value) != 3:
        message = f"{label} must contain three finite numbers"
        raise ValueError(message)
    numbers = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in numbers):
        message = f"{label} must contain three finite numbers"
        raise ValueError(message)
    return Vector(*numbers)


def _positive_number(value: object, *, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        message = f"{label} must be finite and positive"
        raise ValueError(message)
    return number


def _part_key(value: str) -> str:
    normalized = value.replace("\\", "/").rpartition("/")[2].casefold()
    return normalized.removesuffix(".dat")


def _excluded_field_diagnostic(
    field: str,
    *,
    path: Path,
    part_id: str,
) -> Diagnostic:
    return Diagnostic(
        message=f"excluded Studio physical metadata field {field!r} for {part_id!r}",
        severity=Severity.WARNING,
        code=DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
        path=path,
        offending_value=field,
    )


def _diagnostic(
    message: str,
    *,
    path: Path,
    offending_value: object | None = None,
    cause: BaseException | None = None,
) -> Diagnostic:
    return Diagnostic(
        message=message,
        severity=Severity.WARNING,
        code=DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
        path=path,
        offending_value=offending_value,
        cause=cause,
    )


__all__ = ["StudioConnectionLibrary"]
