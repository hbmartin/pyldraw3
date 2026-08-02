"""LDCad and report-oriented connection metadata support."""

from __future__ import annotations

import math
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

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
    frame_for_axis,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.geometry import Identity, Matrix, Vector

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_SHADOW_LINE_RE = re.compile(
    r"^\s*0\s+!LDCAD\s+(SNAP_\w+)\b(.*)$",
    re.IGNORECASE,
)
_SUSPECT_SNAP_RE = re.compile(r"^\s*0?\s*!LDCAD\s+SNAP", re.IGNORECASE)
_VALID_OPTION_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


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


class ConnectionMetadataCoverage(StrEnum):
    """Completeness of normalized connection metadata for one part."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ConnectionMetadataReport:
    """Immutable report for all connection metadata applied to one part."""

    part_code: str
    coverage: ConnectionMetadataCoverage
    features: tuple[ConnectionFeature, ...]
    source_count: int
    recognized_record_count: int
    unsupported_record_count: int
    invalid_record_count: int
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class ShadowConnectionResult:
    """Connections and inheritance controls read from one metadata source."""

    features: tuple[ConnectionFeature, ...] = ()
    clear_all: bool = False
    clear_ids: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    source_count: int = 0
    recognized_record_count: int = 0
    unsupported_record_count: int = 0
    invalid_record_count: int = 0
    document_ids: tuple[str, ...] = ()

    def combined(self, other: ShadowConnectionResult) -> ShadowConnectionResult:
        """Fold another contribution after this one."""
        features = list(self.features)
        clear_all = self.clear_all
        clear_ids = list(self.clear_ids)
        if other.clear_all:
            clear_all = True
            clear_ids.clear()
            features.clear()
        elif other.clear_ids:
            identifiers = {value.casefold() for value in other.clear_ids}
            clear_ids.extend(other.clear_ids)
            features = [
                feature
                for feature in features
                if (feature.metadata_id or "").casefold() not in identifiers
            ]
        overlay_diagnostics: list[Diagnostic] = []
        features = _overlay_features(
            features,
            other.features,
            diagnostics=overlay_diagnostics,
        )
        document_ids = tuple(
            dict.fromkeys((*self.document_ids, *other.document_ids)),
        )
        return ShadowConnectionResult(
            features=tuple(features),
            clear_all=clear_all,
            clear_ids=tuple(dict.fromkeys(clear_ids)),
            diagnostics=(
                *self.diagnostics,
                *other.diagnostics,
                *overlay_diagnostics,
            ),
            source_count=(
                len(document_ids)
                if document_ids
                else self.source_count + other.source_count
            ),
            recognized_record_count=(
                self.recognized_record_count + other.recognized_record_count
            ),
            unsupported_record_count=(
                self.unsupported_record_count + other.unsupported_record_count
            ),
            invalid_record_count=self.invalid_record_count + other.invalid_record_count,
            document_ids=document_ids,
        )


@dataclass(frozen=True, slots=True)
class _SourceText:
    text: str
    path: Path
    archive_member: str | None
    logical_name: str


@dataclass(frozen=True, slots=True)
class _ParsedCommand:
    kind: str
    options: dict[str, str]
    line_number: int
    raw: str


IncludeResolver = Callable[[_ParsedCommand, tuple[str, ...]], ShadowConnectionResult]


class LDCadShadowLibrary:
    """Read unpacked, ZIP, or CSL LDCad shadow metadata."""

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source).expanduser()
        if not self.source.exists():
            message = f"shadow library not found: {self.source}"
            raise FileNotFoundError(message)
        self._archive_text: dict[str, tuple[str, str]] | None = None
        self._text_cache: dict[str, _SourceText | None] = {}
        self._read_diagnostics: dict[str, Diagnostic] = {}
        if self.source.is_file():
            archive_text: dict[str, tuple[str, str]] = {}
            with zipfile.ZipFile(self.source) as archive:
                for member in archive.namelist():
                    if not member.casefold().endswith(".dat"):
                        continue
                    logical = _archive_logical_name(member)
                    if logical is None:
                        continue
                    try:
                        text = archive.read(member).decode("utf-8-sig")
                    except UnicodeError as error:
                        self._read_diagnostics[logical.casefold()] = _diagnostic(
                            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                            f"could not decode shadow metadata {member!r}: {error}",
                            path=self.source,
                            offending_value=member,
                            cause=error,
                        )
                        continue
                    archive_text.setdefault(
                        logical.casefold(),
                        (member, text),
                    )
            self._archive_text = archive_text

    def connections_for(
        self,
        code: str,
        *,
        siblings: tuple[LDCadShadowLibrary, ...] = (),
    ) -> ShadowConnectionResult:
        """Return resolved shadow features for a part or primitive code.

        ``siblings`` is the full ordered registry of shadow libraries used to
        resolve ``SNAP_INCL`` references across the merged shadow namespace.
        """
        return self._connections_for(
            _normalized_code(code),
            visiting=(),
            include_chain=(),
            siblings=siblings,
        )

    def _connections_for(
        self,
        code: str,
        *,
        visiting: tuple[str, ...],
        include_chain: tuple[str, ...],
        siblings: tuple[LDCadShadowLibrary, ...] = (),
    ) -> ShadowConnectionResult:
        if code in visiting:
            cycle = (*visiting[visiting.index(code) :], code)
            canonical_cycle = _canonical_cycle(cycle)
            return ShadowConnectionResult(
                diagnostics=(
                    _diagnostic(
                        DiagnosticCode.CONNECTION_INCLUDE_CYCLE,
                        (
                            "LDCad SNAP_INCL cycle: "
                            f"{' -> '.join((*canonical_cycle, canonical_cycle[0]))}"
                        ),
                        path=self.source,
                        offending_value=canonical_cycle,
                    ),
                ),
                invalid_record_count=1,
            )
        source = self._read_shadow_text(code)
        if source is None:
            if (read_diagnostic := self._read_diagnostic_for(code)) is not None:
                document_id = f"{self.source.resolve()}::{_shadow_candidates(code)[0]}"
                return ShadowConnectionResult(
                    diagnostics=(read_diagnostic,),
                    source_count=1,
                    invalid_record_count=1,
                    document_ids=(document_id,),
                )
            return ShadowConnectionResult()

        def resolve(
            command: _ParsedCommand,
            chain: tuple[str, ...],
        ) -> ShadowConnectionResult:
            reference = _normalized_code(command.options["ref"])
            included = _resolve_across_libraries(
                siblings or (self,),
                reference,
                visiting=(*visiting, code),
                include_chain=chain,
            )
            if included is None:
                return ShadowConnectionResult(
                    diagnostics=(
                        _diagnostic(
                            DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND,
                            f"LDCad SNAP_INCL reference not found: {reference!r}",
                            line_number=command.line_number,
                            path=self.source,
                            offending_value=reference,
                        ),
                    ),
                    invalid_record_count=1,
                )
            return _transform_include(
                included,
                command=command,
                owner_code=code,
                reference=reference,
                effective_source=ConnectionSource.LDCAD_SHADOW,
                marker=chain[-1] if chain else None,
            )

        return _parse_commands(
            code=code,
            text=source.text,
            path=source.path,
            archive_member=source.archive_member,
            effective_source=ConnectionSource.LDCAD_SHADOW,
            include_chain=include_chain,
            include_resolver=resolve,
            source_count=1,
            document_ids=(
                f"{self.source.resolve()}::{source.logical_name.casefold()}",
            ),
        )

    def _read_shadow_text(self, code: str) -> _SourceText | None:
        if code in self._text_cache:
            return self._text_cache[code]
        result: _SourceText | None = None
        for candidate in _shadow_candidates(code):
            if self.source.is_dir():
                path = _case_insensitive_path(self.source, candidate)
                if path is not None and path.is_file():
                    try:
                        text = path.read_text(encoding="utf-8-sig")
                    except (OSError, UnicodeError) as error:
                        self._read_diagnostics[candidate.casefold()] = _diagnostic(
                            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                            f"could not read shadow metadata {path}: {error}",
                            path=path,
                            offending_value=candidate,
                            cause=error,
                        )
                    else:
                        result = _SourceText(
                            text=text,
                            path=path,
                            archive_member=None,
                            logical_name=candidate,
                        )
                    break
            elif (
                self._archive_text is not None
                and (stored := self._archive_text.get(candidate.casefold())) is not None
            ):
                member, text = stored
                result = _SourceText(
                    text=text,
                    path=self.source,
                    archive_member=member,
                    logical_name=candidate,
                )
                break
        self._text_cache[code] = result
        return result

    def _read_diagnostic_for(self, code: str) -> Diagnostic | None:
        return next(
            (
                self._read_diagnostics[candidate.casefold()]
                for candidate in _shadow_candidates(code)
                if candidate.casefold() in self._read_diagnostics
            ),
            None,
        )


def _resolve_across_libraries(
    libraries: tuple[LDCadShadowLibrary, ...],
    reference: str,
    *,
    visiting: tuple[str, ...],
    include_chain: tuple[str, ...],
) -> ShadowConnectionResult | None:
    """Resolve a SNAP_INCL reference against the merged shadow namespace."""
    combined = ShadowConnectionResult()
    found = False
    for library in libraries:
        candidate = library._connections_for(  # noqa: SLF001 - composite resolver
            reference,
            visiting=visiting,
            include_chain=include_chain,
            siblings=libraries,
        )
        if (
            candidate.source_count
            or candidate.diagnostics
            or candidate.invalid_record_count
        ):
            found = True
            combined = combined.combined(candidate)
    return combined if found else None


def parse_ldcad_commands(
    code: str,
    commands: Iterable[str],
    *,
    source: str | Path | None = None,
    connection_shadows: Iterable[LDCadShadowLibrary | str | Path] = (),
) -> ShadowConnectionResult:
    """Parse inline ``!LDCAD SNAP_*`` commands without aborting geometry.

    Every entry is expected to be an LDCad command; entries that cannot be
    recognized are reported as invalid records instead of being dropped.
    """
    lines = tuple(
        command if _SHADOW_LINE_RE.match(command) else _wrapped_command(command)
        for command in commands
    )
    return _parse_inline_text(
        code=code,
        text="\n".join(lines),
        source=source,
        connection_shadows=connection_shadows,
        source_count=int(bool(lines)),
        strict_lines=True,
    )


def _wrapped_command(command: str) -> str:
    body = re.sub(r"^(?:0\s+)?!LDCAD\s+", "", command.strip(), flags=re.IGNORECASE)
    return f"0 !LDCAD {body}"


def parse_ldcad_text(
    code: str,
    text: str,
    *,
    source: str | Path | None = None,
    connection_shadows: Iterable[LDCadShadowLibrary | str | Path] = (),
) -> ShadowConnectionResult:
    """Parse LDCad commands from a complete document, retaining line numbers."""
    has_metadata = any(_SHADOW_LINE_RE.match(line) for line in text.splitlines())
    return _parse_inline_text(
        code=code,
        text=text,
        source=source,
        connection_shadows=connection_shadows,
        source_count=int(has_metadata),
    )


def _parse_inline_text(  # noqa: PLR0913 - explicit source controls
    *,
    code: str,
    text: str,
    source: str | Path | None,
    connection_shadows: Iterable[LDCadShadowLibrary | str | Path],
    source_count: int,
    strict_lines: bool = False,
) -> ShadowConnectionResult:
    libraries = tuple(
        item if isinstance(item, LDCadShadowLibrary) else LDCadShadowLibrary(item)
        for item in connection_shadows
    )

    def resolve(
        command: _ParsedCommand,
        chain: tuple[str, ...],
    ) -> ShadowConnectionResult:
        reference = _normalized_code(command.options["ref"])
        if not libraries:
            return ShadowConnectionResult(
                diagnostics=(
                    _diagnostic(
                        DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND,
                        "SNAP_INCL requires a configured shadow library",
                        line_number=command.line_number,
                        path=Path(source) if source is not None else None,
                        offending_value=command.raw,
                    ),
                ),
                invalid_record_count=1,
            )
        combined = _resolve_across_libraries(
            libraries,
            reference,
            visiting=(),
            include_chain=chain,
        )
        if combined is None:
            return ShadowConnectionResult(
                diagnostics=(
                    _diagnostic(
                        DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND,
                        f"LDCad SNAP_INCL reference not found: {reference!r}",
                        line_number=command.line_number,
                        path=Path(source) if source is not None else None,
                        offending_value=command.raw,
                    ),
                ),
                invalid_record_count=1,
            )
        return _transform_include(
            combined,
            command=command,
            owner_code=_normalized_code(code),
            reference=reference,
            effective_source=ConnectionSource.LDCAD_INLINE,
            marker=chain[-1] if chain else None,
        )

    return _parse_commands(
        code=_normalized_code(code),
        text=text,
        path=Path(source) if source is not None else None,
        archive_member=None,
        effective_source=ConnectionSource.LDCAD_INLINE,
        include_chain=(),
        include_resolver=resolve,
        source_count=source_count,
        document_ids=(
            (f"{Path(source).resolve()}::inline" if source is not None else "inline"),
        )
        if source_count
        else (),
        strict_lines=strict_lines,
    )


def metadata_report(
    code: str,
    *,
    features: Iterable[ConnectionFeature],
    result: ShadowConnectionResult,
    authoritative: bool = False,
) -> ConnectionMetadataReport:
    """Create the public coverage report for normalized part-local features."""
    values = tuple(features)
    has_authoritative = result.source_count > 0 or authoritative
    incomplete = bool(result.unsupported_record_count or result.invalid_record_count)
    if has_authoritative and not incomplete:
        coverage = ConnectionMetadataCoverage.COMPLETE
    elif has_authoritative or values or incomplete:
        coverage = ConnectionMetadataCoverage.PARTIAL
    else:
        coverage = ConnectionMetadataCoverage.NONE
    return ConnectionMetadataReport(
        part_code=code,
        coverage=coverage,
        features=values,
        source_count=result.source_count,
        recognized_record_count=result.recognized_record_count,
        unsupported_record_count=result.unsupported_record_count,
        invalid_record_count=result.invalid_record_count,
        diagnostics=result.diagnostics,
    )


def _parse_commands(  # noqa: C901, PLR0912, PLR0913, PLR0915
    *,
    code: str,
    text: str,
    path: Path | None,
    archive_member: str | None,
    effective_source: ConnectionSource,
    include_chain: tuple[str, ...],
    include_resolver: IncludeResolver,
    source_count: int,
    document_ids: tuple[str, ...],
    strict_lines: bool = False,
) -> ShadowConnectionResult:
    features: list[ConnectionFeature] = []
    diagnostics: list[Diagnostic] = []
    clear_all = False
    clear_ids: list[str] = []
    recognized = 0
    unsupported = 0
    invalid = 0
    seen_ids: dict[str, int] = {}
    processed_documents = list(document_ids)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if (match := _SHADOW_LINE_RE.match(line)) is None:
            stripped = line.strip()
            suspect = (
                bool(stripped)
                if strict_lines
                else _SUSPECT_SNAP_RE.match(line) is not None
            )
            if suspect:
                invalid += 1
                diagnostics.append(
                    _diagnostic(
                        DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                        f"unrecognized LDCad metadata line: {stripped!r}",
                        line_number=line_number,
                        path=path,
                        offending_value=stripped,
                    ),
                )
            continue
        kind = match.group(1).upper()
        raw = line.strip()
        try:
            options = _tokenize_options(match.group(2))
        except ValueError as error:
            invalid += 1
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                    f"invalid LDCad {kind} record: {error}",
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                    cause=error,
                ),
            )
            continue
        if (allowed := _SUPPORTED_OPTIONS.get(kind)) is None:
            unsupported += 1
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_UNSUPPORTED_RECORD,
                    f"unsupported LDCad connection record {kind}",
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                ),
            )
            continue
        unknown = tuple(key for key in options if key not in allowed)
        if unknown:
            unsupported += 1
            diagnostics.extend(
                _diagnostic(
                    DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
                    f"unsupported {kind} option {key!r}",
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                )
                for key in unknown
            )
            options = {key: value for key, value in options.items() if key in allowed}
        missing = tuple(
            key for key in _REQUIRED_OPTIONS.get(kind, ()) if not options.get(key)
        )
        if missing:
            invalid += 1
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_MISSING_REQUIRED_OPTION,
                    f"{kind} is missing required option(s): {', '.join(missing)}",
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                ),
            )
            continue
        command = _ParsedCommand(kind, options, line_number, raw)
        provenance = ConnectionProvenance(
            source=effective_source,
            path=path,
            archive_member=archive_member,
            line_number=line_number,
            command=raw,
            include_chain=include_chain,
        )
        try:
            _validate_common_options(kind, options)
            match kind:
                case "SNAP_CLEAR":
                    if identifier := options.get("id"):
                        clear_ids.append(identifier)
                        features = [
                            feature
                            for feature in features
                            if (feature.metadata_id or "").casefold()
                            != identifier.casefold()
                        ]
                    else:
                        clear_all = True
                        clear_ids.clear()
                        features.clear()
                case "SNAP_INCL":
                    raw_marker = options.get("id")
                    marker_occurrence = (
                        seen_ids.get(raw_marker.casefold(), 0) if raw_marker else 0
                    )
                    if raw_marker is None:
                        marker = f"snap_incl@L{line_number}"
                    elif marker_occurrence:
                        marker = f"{raw_marker}@L{line_number}"
                    else:
                        marker = raw_marker
                    included = include_resolver(
                        command,
                        (*include_chain, marker),
                    )
                    if raw_marker is not None:
                        seen_ids[raw_marker.casefold()] = marker_occurrence + 1
                    features = _overlay_features(
                        features,
                        included.features,
                        diagnostics=diagnostics,
                    )
                    diagnostics.extend(included.diagnostics)
                    source_count += included.source_count
                    processed_documents.extend(included.document_ids)
                    recognized += included.recognized_record_count
                    unsupported += included.unsupported_record_count
                    invalid += included.invalid_record_count
                case _:
                    raw_id = options.get("id")
                    repeated = raw_id is not None and bool(
                        seen_ids.get(raw_id.casefold(), 0),
                    )
                    created = _feature_instances(
                        code=code,
                        command=command,
                        source=effective_source,
                        provenance=provenance,
                        seen_ids=seen_ids,
                    )
                    if repeated and raw_id is not None:
                        features = [
                            _suffix_first_repeated_id(feature, raw_id=raw_id)
                            for feature in features
                        ]
                    features = _overlay_features(
                        features,
                        created,
                        diagnostics=diagnostics,
                    )
        except FileNotFoundError as error:
            invalid += 1
            diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND,
                    str(error),
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                    cause=error,
                ),
            )
            continue
        except (IndexError, KeyError, TypeError, ValueError) as error:
            invalid += 1
            code_value = (
                error.code
                if isinstance(error, _MetadataValueError)
                else DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE
            )
            diagnostics.append(
                _diagnostic(
                    code_value,
                    f"invalid LDCad {kind} metadata: {error}",
                    line_number=line_number,
                    path=path,
                    offending_value=raw,
                    cause=error,
                ),
            )
            continue
        recognized += 1
    return ShadowConnectionResult(
        features=tuple(features),
        clear_all=clear_all,
        clear_ids=tuple(clear_ids),
        diagnostics=_deduplicate_cycle_diagnostics(diagnostics),
        source_count=(
            len(dict.fromkeys(processed_documents))
            if processed_documents
            else source_count
        ),
        recognized_record_count=recognized,
        unsupported_record_count=unsupported,
        invalid_record_count=invalid,
        document_ids=tuple(dict.fromkeys(processed_documents)),
    )


def _tokenize_options(value: str) -> dict[str, str]:
    options: dict[str, str] = {}
    index = 0
    while index < len(value):
        while index < len(value) and value[index].isspace():
            index += 1
        if index == len(value):
            break
        if value[index] != "[":
            message = f"unparsed trailing text {value[index:]!r}"
            raise ValueError(message)
        end = value.find("]", index + 1)
        if end < 0:
            message = "option has an unclosed '[' bracket"
            raise ValueError(message)
        body = value[index + 1 : end]
        if "[" in body:
            message = "option contains a nested '[' bracket"
            raise ValueError(message)
        if "=" not in body:
            message = f"option {body!r} has no '='"
            raise ValueError(message)
        key, item = body.split("=", 1)
        key = key.strip().casefold()
        if _VALID_OPTION_KEY.fullmatch(key) is None:
            message = f"invalid option key {key!r}"
            raise ValueError(message)
        if key in options:
            message = f"duplicate option key {key!r}"
            raise ValueError(message)
        options[key] = item.strip()
        index = end + 1
    return options


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
            # public ConnectionFeature contract (+Y is the feature axis) by
            # folding that convention into the normalized feature frame.
            frame=orientation * _NEGATIVE_Y_FRAME,
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
        features.append(projected)
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
    options = command.options
    identifier = options.get("id")
    group = options.get("group")
    match command.kind:
        case "SNAP_CYL":
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
                    friction=not slide,
                    caps=_caps(options.get("caps")),
                ),
                name=identifier or group or "LDCad cylinder",
                group=group,
                freedoms=frozenset(freedoms),
                owner_code=code,
            )
        case "SNAP_CLP":
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
                ),
                name=identifier or group or "LDCad clip",
                group=group,
                freedoms=frozenset(freedoms),
                owner_code=code,
            )
        case "SNAP_FGR":
            freedoms = {ConnectionFreedom.ROTATE}
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
                freedoms=frozenset(freedoms),
                owner_code=code,
            )
        case "SNAP_GEN":
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
        case _:
            message = f"unsupported feature command {command.kind}"
            raise ValueError(message)


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


def _validate_common_options(  # noqa: C901 - shared option validation table
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
    shapes = {section.shape for section in sections}
    if SectionShape.AXLE in shapes:
        return (
            ConnectionKind.AXLE
            if role is ConnectionRole.MALE
            else ConnectionKind.AXLE_HOLE
        )
    lowered = label.casefold()
    rigid = tuple(section for section in sections if not section.flexible)
    radius = min((section.radius for section in rigid), default=0.0)
    length = sum(section.length for section in sections)
    stud_shape = (
        len(rigid) == 1
        and abs(radius - 6.0) <= 0.25
        and abs(length - 4.0) <= 0.5
        and caps is not CylindricalCaps.NONE
    )
    if "stud" in lowered or stud_shape:
        return (
            ConnectionKind.STUD
            if role is ConnectionRole.MALE
            else ConnectionKind.STUD_RECEPTACLE
        )
    if (
        role is ConnectionRole.MALE
        and abs(radius - 4.0) <= 0.35
        and (slide or caps is CylindricalCaps.TWO)
    ):
        return ConnectionKind.BAR
    return (
        ConnectionKind.PIN if role is ConnectionRole.MALE else ConnectionKind.PIN_HOLE
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


def _shadow_candidates(code: str) -> tuple[str, ...]:
    code = _normalized_code(code)
    if any(component in {"", ".", ".."} for component in code.split("/")):
        return ()
    if code.startswith("parts/"):
        return (f"{code}.dat",)
    if code.startswith("p/"):
        return (f"{code}.dat",)
    if code.startswith("s/"):
        return (f"parts/{code}.dat",)
    if code.startswith(("8/", "48/")):
        return (f"p/{code}.dat",)
    return (f"parts/{code}.dat", f"p/{code}.dat")


def _archive_logical_name(member: str) -> str | None:
    normalized = member.replace("\\", "/").strip("/")
    lowered = normalized.casefold()
    for marker in ("parts/", "p/"):
        index = lowered.find(marker)
        while index >= 0:
            if index == 0 or lowered[index - 1] == "/":
                return normalized[index:]
            index = lowered.find(marker, index + 1)
    return None


def _case_insensitive_path(root: Path, relative: str) -> Path | None:
    current = root
    for component in relative.split("/"):
        if component in {"", ".", ".."}:
            return None
        direct = current / component
        if direct.exists():
            current = direct
            continue
        if not current.is_dir():
            return None
        match = next(
            (
                item
                for item in current.iterdir()
                if item.name.casefold() == component.casefold()
            ),
            None,
        )
        if match is None:
            return None
        current = match
    return current


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


def _grid_offsets(value: str | None) -> tuple[Vector, ...]:
    if not value:
        return (Vector(0, 0, 0),)
    tokens = value.split()
    numeric_count = sum(token.casefold() != "c" for token in tokens)
    dimensions = 2 if numeric_count == 4 else 3 if numeric_count == 6 else 0
    if not dimensions:
        message = "grid must contain X/Z or X/Y/Z counts and steps"
        raise _MetadataValueError(message, code=DiagnosticCode.CONNECTION_INVALID_GRID)
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


def _grid_coordinate(
    index: int,
    count: int,
    *,
    centered: bool,
    step: float,
) -> float:
    return (index - (count - 1) / 2 if centered else index) * step


def _provenance_text(provenance: ConnectionProvenance) -> str:
    location = provenance.archive_member or (
        str(provenance.path)
        if provenance.path is not None
        else provenance.command or provenance.source.value
    )
    if provenance.line_number is not None:
        location = f"{location}:{provenance.line_number}"
    if provenance.include_chain:
        location = f"{location} via {' > '.join(provenance.include_chain)}"
    return location


def _feature_origin(feature: ConnectionFeature) -> str:
    if feature.connection_provenance is not None:
        return _provenance_text(feature.connection_provenance)
    return ", ".join(feature.provenance) or feature.source.value


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


__all__ = [
    "ConnectionMetadataCoverage",
    "ConnectionMetadataReport",
    "LDCadShadowLibrary",
    "ShadowConnectionResult",
    "metadata_report",
    "parse_ldcad_commands",
    "parse_ldcad_text",
]
