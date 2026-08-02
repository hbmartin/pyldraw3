"""Optional LDCad shadow-library connection metadata support."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionFreedom,
    ConnectionKind,
    ConnectionRole,
    ConnectionSource,
    CylindricalProfile,
    CylindricalSection,
    FingerProfile,
    GenericProfile,
    SectionShape,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.geometry import Identity, Matrix, Vector

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_OPTION_RE = re.compile(r"\[([^=\]]+)=([^\]]*)\]")
_SHADOW_LINE_RE = re.compile(
    r"^\s*0\s+!LDCAD\s+(SNAP_\w+)(?:\s+(.*))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ShadowConnectionResult:
    """Connections and inheritance controls read from one shadow file."""

    features: tuple[ConnectionFeature, ...] = ()
    clear_all: bool = False
    clear_ids: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


class LDCadShadowLibrary:
    """Read connection metadata from an unpacked or zipped LDCad shadow library."""

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source).expanduser()
        if not self.source.exists():
            message = f"shadow library not found: {self.source}"
            raise FileNotFoundError(message)
        self._zip_index: dict[str, str] | None = None
        if self.source.is_file():
            with zipfile.ZipFile(self.source) as archive:
                self._zip_index = {
                    name.replace("\\", "/").casefold(): name
                    for name in archive.namelist()
                    if name.casefold().endswith(".dat")
                }
        self._cache: dict[str, ShadowConnectionResult] = {}

    def connections_for(self, code: str) -> ShadowConnectionResult:
        """Return resolved shadow features for a part or primitive code."""
        return self._connections_for(_normalized_code(code), visiting=frozenset())

    def _connections_for(
        self,
        code: str,
        *,
        visiting: frozenset[str],
    ) -> ShadowConnectionResult:
        if code in visiting:
            return ShadowConnectionResult(
                diagnostics=(
                    Diagnostic(
                        message=f"LDCad SNAP_INCL cycle at {code!r}",
                        severity=Severity.WARNING,
                        code=DiagnosticCode.CONNECTION_METADATA_INVALID,
                        path=self.source,
                        offending_value=code,
                    ),
                ),
            )
        if (cached := self._cache.get(code)) is not None:
            return cached
        text = self._read_shadow_text(code)
        if text is None:
            result = ShadowConnectionResult()
            self._cache[code] = result
            return result
        result = self._parse_shadow_text(
            code=code,
            text=text,
            visiting=visiting | {code},
        )
        self._cache[code] = result
        return result

    def _read_shadow_text(self, code: str) -> str | None:
        candidates = _shadow_candidates(code)
        if self.source.is_dir():
            for candidate in candidates:
                path = self.source / candidate
                if path.is_file():
                    return path.read_text(encoding="utf-8-sig")
            return None
        if self._zip_index is None:  # pragma: no cover - constructor invariant
            return None
        for candidate in candidates:
            lowered = candidate.casefold()
            name = self._zip_index.get(lowered)
            if name is None:
                name = next(
                    (
                        stored
                        for indexed, stored in self._zip_index.items()
                        if indexed.endswith(f"/{lowered}")
                    ),
                    None,
                )
            if name is not None:
                with zipfile.ZipFile(self.source) as archive:
                    return archive.read(name).decode("utf-8-sig")
        return None

    def _parse_shadow_text(
        self,
        *,
        code: str,
        text: str,
        visiting: frozenset[str],
    ) -> ShadowConnectionResult:
        return _parse_commands(
            code=code,
            text=text,
            source=self.source,
            include_resolver=lambda options: self._include_features(
                code=code,
                options=options,
                visiting=visiting,
            ),
        )

    def _include_features(
        self,
        *,
        code: str,
        options: dict[str, str],
        visiting: frozenset[str],
    ) -> ShadowConnectionResult:
        reference = _normalized_code(options["ref"])
        included = self._connections_for(reference, visiting=visiting)
        position = _vector(options.get("pos"), default=Vector(0, 0, 0))
        orientation = _matrix(options.get("ori"), default=Identity())
        if scale_value := options.get("scale"):
            scale = _vector(scale_value, default=Vector(1, 1, 1))
            orientation = orientation.scale(scale.x, scale.y, scale.z)
        transformed: list[ConnectionFeature] = []
        for grid_offset in _grid_offsets(options.get("grid")):
            transformed.extend(
                replace(
                    feature.transformed(
                        position=position + orientation * grid_offset,
                        matrix=orientation,
                    ),
                    owner_code=code,
                    provenance=(*feature.provenance, f"SNAP_INCL {reference}"),
                )
                for feature in included.features
            )
        return ShadowConnectionResult(
            features=tuple(transformed),
            diagnostics=included.diagnostics,
        )


def parse_ldcad_commands(
    code: str,
    commands: Iterable[str],
    *,
    source: str | Path | None = None,
) -> ShadowConnectionResult:
    """Parse inline ``!LDCAD SNAP_*`` commands from a part file.

    Direct feature and clear commands are supported inline. ``SNAP_INCL``
    needs a shadow-library resolver, so unresolved inline includes produce a
    structured diagnostic instead of being silently ignored.
    """
    lines = tuple(
        command if _SHADOW_LINE_RE.match(command) else f"0 !LDCAD {command.strip()}"
        for command in commands
    )
    result = _parse_commands(
        code=_normalized_code(code),
        text="\n".join(lines),
        source=Path(source) if source is not None else None,
        include_resolver=None,
    )
    return replace(
        result,
        features=tuple(
            replace(
                feature,
                source=ConnectionSource.LDCAD_INLINE,
                provenance=tuple(
                    "inline " + item if item.startswith("LDCad ") else item
                    for item in feature.provenance
                ),
            )
            for feature in result.features
        ),
    )


def _parse_commands(  # noqa: C901 - command dispatch remains readable
    *,
    code: str,
    text: str,
    source: Path | None,
    include_resolver: Callable[[dict[str, str]], ShadowConnectionResult] | None,
) -> ShadowConnectionResult:
    features: list[ConnectionFeature] = []
    diagnostics: list[Diagnostic] = []
    clear_all = False
    clear_ids: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _SHADOW_LINE_RE.match(line)
        if match is None:
            continue
        command = match.group(1).upper()
        options = _parse_options(match.group(2) or "")
        try:
            if command == "SNAP_CLEAR":
                if identifier := options.get("id"):
                    clear_ids.append(identifier)
                    features = [
                        feature
                        for feature in features
                        if feature.feature_id != identifier
                    ]
                else:
                    clear_all = True
                    features.clear()
            elif command == "SNAP_INCL":
                included = _resolve_include(include_resolver, options)
                features.extend(included.features)
                diagnostics.extend(included.diagnostics)
            elif command == "SNAP_CYL":
                features.append(_cylinder_feature(code=code, options=options))
            elif command == "SNAP_CLP":
                features.append(_clip_feature(code=code, options=options))
            elif command == "SNAP_FGR":
                features.append(_finger_feature(code=code, options=options))
            elif command == "SNAP_GEN":
                features.append(_generic_feature(code=code, options=options))
        except (IndexError, KeyError, TypeError, ValueError) as error:
            diagnostics.append(
                Diagnostic(
                    line_number=line_number,
                    message=f"invalid LDCad {command} metadata: {error}",
                    severity=Severity.WARNING,
                    code=DiagnosticCode.CONNECTION_METADATA_INVALID,
                    path=source,
                    offending_value=line.strip(),
                    cause=error,
                ),
            )
    return ShadowConnectionResult(
        features=tuple(features),
        clear_all=clear_all,
        clear_ids=tuple(clear_ids),
        diagnostics=tuple(diagnostics),
    )


def _resolve_include(
    resolver: Callable[[dict[str, str]], ShadowConnectionResult] | None,
    options: dict[str, str],
) -> ShadowConnectionResult:
    if resolver is None:
        message = "SNAP_INCL requires a configured shadow library"
        raise ValueError(message)
    return resolver(options)


def _cylinder_feature(
    *,
    code: str,
    options: dict[str, str],
) -> ConnectionFeature:
    sections = _sections(options.get("secs", "R 6 1"))
    role = _role(options.get("gender"))
    identifier = options.get("id")
    group = options.get("group")
    kind = _cylinder_kind(
        role=role,
        sections=sections,
        label=" ".join(value for value in (identifier, group) if value),
        slide=_boolean(options.get("slide"), default=False),
    )
    freedoms = {ConnectionFreedom.ROTATE}
    if _boolean(options.get("slide"), default=False):
        freedoms.add(ConnectionFreedom.SLIDE)
    return ConnectionFeature(
        kind=kind,
        role=role,
        position=_vector(options.get("pos"), default=Vector(0, 0, 0)),
        frame=_matrix(options.get("ori"), default=Identity()),
        profile=CylindricalProfile(
            sections=sections,
            centered=_boolean(options.get("center"), default=False),
            friction=not _boolean(options.get("slide"), default=False),
        ),
        name=identifier or group or "LDCad cylinder",
        feature_id=identifier,
        group=group,
        freedoms=frozenset(freedoms),
        source=ConnectionSource.LDCAD_SHADOW,
        owner_code=code,
        provenance=("LDCad SNAP_CYL",),
    )


def _clip_feature(*, code: str, options: dict[str, str]) -> ConnectionFeature:
    identifier = options.get("id")
    freedoms = {ConnectionFreedom.ROTATE}
    if _boolean(options.get("slide"), default=False):
        freedoms.add(ConnectionFreedom.SLIDE)
    return ConnectionFeature(
        kind=ConnectionKind.CLIP,
        role=ConnectionRole.FEMALE,
        position=_vector(options.get("pos"), default=Vector(0, 0, 0)),
        frame=_matrix(options.get("ori"), default=Identity()),
        profile=CylindricalProfile(
            sections=(
                CylindricalSection(
                    SectionShape.ROUND,
                    float(options.get("radius", "4")),
                    float(options.get("length", "8")),
                ),
            ),
            centered=_boolean(options.get("center"), default=False),
        ),
        name=identifier or "LDCad clip",
        feature_id=identifier,
        freedoms=frozenset(freedoms),
        source=ConnectionSource.LDCAD_SHADOW,
        owner_code=code,
        provenance=("LDCad SNAP_CLP",),
    )


def _finger_feature(*, code: str, options: dict[str, str]) -> ConnectionFeature:
    first_role = _role(options.get("genderofs"))
    identifier = options.get("id")
    group = options.get("group")
    return ConnectionFeature(
        kind=ConnectionKind.HINGE,
        role=ConnectionRole.NEUTRAL,
        position=_vector(options.get("pos"), default=Vector(0, 0, 0)),
        frame=_matrix(options.get("ori"), default=Identity()),
        profile=FingerProfile(
            sequence=_float_tuple(options.get("seq", "")),
            radius=float(options.get("radius", "6")),
            first_role=first_role,
        ),
        name=identifier or group or "LDCad fingers",
        feature_id=identifier,
        group=group,
        freedoms=frozenset((ConnectionFreedom.ROTATE,)),
        source=ConnectionSource.LDCAD_SHADOW,
        owner_code=code,
        provenance=("LDCad SNAP_FGR",),
    )


def _generic_feature(*, code: str, options: dict[str, str]) -> ConnectionFeature:
    identifier = options.get("id")
    group = options.get("group")
    return ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=_role(options.get("gender")),
        position=_vector(options.get("pos"), default=Vector(0, 0, 0)),
        frame=_matrix(options.get("ori"), default=Identity()),
        profile=GenericProfile(name=group or identifier or "generic"),
        name=identifier or group or "LDCad generic",
        feature_id=identifier,
        group=group,
        source=ConnectionSource.LDCAD_SHADOW,
        owner_code=code,
        provenance=("LDCad SNAP_GEN",),
    )


def _sections(value: str) -> tuple[CylindricalSection, ...]:
    tokens = value.split()
    if len(tokens) % 3:
        message = "secs must contain shape/radius/length triples"
        raise ValueError(message)
    raw = [
        (
            tokens[index].upper(),
            float(tokens[index + 1]),
            float(tokens[index + 2]),
        )
        for index in range(0, len(tokens), 3)
    ]
    sections: list[CylindricalSection] = []
    for index, (shape_code, radius, length) in enumerate(raw):
        flexible = shape_code in {"_L", "L_"}
        resolved_shape = shape_code
        if flexible:
            neighbour = index - 1 if shape_code.startswith("_") else index + 1
            if not 0 <= neighbour < len(raw):
                message = "flexible section needs an adjacent rigid section"
                raise ValueError(message)
            resolved_shape = raw[neighbour][0]
        shape = {
            "R": SectionShape.ROUND,
            "A": SectionShape.AXLE,
            "S": SectionShape.SQUARE,
        }[resolved_shape]
        sections.append(
            CylindricalSection(
                shape=shape,
                radius=radius,
                length=length,
                flexible=flexible,
            ),
        )
    return tuple(sections)


def _cylinder_kind(
    *,
    role: ConnectionRole,
    sections: tuple[CylindricalSection, ...],
    label: str,
    slide: bool,
) -> ConnectionKind:
    shapes = {section.shape for section in sections}
    if SectionShape.AXLE in shapes:
        return (
            ConnectionKind.AXLE
            if role is ConnectionRole.MALE
            else ConnectionKind.AXLE_HOLE
        )
    lowered = label.casefold()
    if "stud" in lowered:
        return (
            ConnectionKind.STUD
            if role is ConnectionRole.MALE
            else ConnectionKind.STUD_RECEPTACLE
        )
    radius = min((section.radius for section in sections), default=0.0)
    if role is ConnectionRole.MALE and slide and abs(radius - 4.0) <= 0.25:
        return ConnectionKind.BAR
    return (
        ConnectionKind.PIN if role is ConnectionRole.MALE else ConnectionKind.PIN_HOLE
    )


def _parse_options(value: str) -> dict[str, str]:
    return {
        key.strip().casefold(): item.strip() for key, item in _OPTION_RE.findall(value)
    }


def _normalized_code(value: str) -> str:
    normalized = value.replace("\\", "/").casefold()
    return normalized.removesuffix(".dat")


def _shadow_candidates(code: str) -> tuple[str, ...]:
    if code.startswith("p/"):
        return (f"p/{code.removeprefix('p/')}.dat",)
    value = f"{code}.dat"
    if code.startswith(("s/", "48/", "8/")):
        prefix = "parts" if code.startswith("s/") else "p"
        return (f"{prefix}/{value}",)
    return (f"parts/{value}", f"p/{value}")


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
        message = "orientation must contain nine numbers"
        raise ValueError(message)
    return Matrix([list(numbers[0:3]), list(numbers[3:6]), list(numbers[6:9])])


def _float_tuple(value: str) -> tuple[float, ...]:
    return tuple(float(token) for token in value.split())


def _role(value: str | None) -> ConnectionRole:
    return (
        ConnectionRole.FEMALE
        if value is not None and value.casefold().startswith("f")
        else ConnectionRole.MALE
    )


def _boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    lowered = value.casefold()
    if lowered not in {"true", "false"}:
        message = f"expected true or false, got {value!r}"
        raise ValueError(message)
    return lowered == "true"


def _grid_offsets(value: str | None) -> tuple[Vector, ...]:
    if not value:
        return (Vector(0, 0, 0),)
    tokens = value.split()
    index = 0
    x_centered = tokens[index].casefold() == "c"
    index += int(x_centered)
    x_count = int(tokens[index])
    index += 1
    z_centered = tokens[index].casefold() == "c"
    index += int(z_centered)
    z_count = int(tokens[index])
    index += 1
    x_step, z_step = map(float, tokens[index : index + 2])
    if index + 2 != len(tokens):
        message = "grid must contain X/Z counts and steps"
        raise ValueError(message)
    return tuple(
        Vector(
            (x_index - (x_count - 1) / 2 if x_centered else x_index) * x_step,
            0,
            (z_index - (z_count - 1) / 2 if z_centered else z_index) * z_step,
        )
        for x_index in range(x_count)
        for z_index in range(z_count)
    )


__all__ = [
    "LDCadShadowLibrary",
    "ShadowConnectionResult",
    "parse_ldcad_commands",
]
