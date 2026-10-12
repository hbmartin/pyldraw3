"""LDCad parser implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ldraw._connection_common import (
    _REQUIRED_OPTIONS,
    _SHADOW_LINE_RE,
    _SUPPORTED_OPTIONS,
    _SUSPECT_SNAP_RE,
    _VALID_OPTION_KEY,
    IncludeResolver,
    _deduplicate_cycle_diagnostics,
    _diagnostic,
    _MetadataValueError,
    _normalized_code,
    _overlay_features,
    _ParsedCommand,
)
from ldraw._connection_features import (
    _feature_instances,
    _suffix_first_repeated_id,
    _transform_include,
    _validate_common_options,
)
from ldraw._connection_results import ShadowConnectionResult
from ldraw._connection_sources import _resolve_across_libraries
from ldraw.connection_metadata import LDCadShadowLibrary
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionProvenance,
    ConnectionSource,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode

if TYPE_CHECKING:
    from collections.abc import Iterable


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


@dataclass(slots=True)
class _CommandParser:
    """One metadata document parse: fixed context plus running totals."""

    code: str
    path: Path | None
    archive_member: str | None
    effective_source: ConnectionSource
    include_chain: tuple[str, ...]
    include_resolver: IncludeResolver
    strict_lines: bool
    source_count: int
    processed_documents: list[str]
    features: list[ConnectionFeature] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    clear_all: bool = False
    clear_ids: list[str] = field(default_factory=list)
    recognized: int = 0
    unsupported: int = 0
    invalid: int = 0
    seen_ids: dict[str, int] = field(default_factory=dict)

    def parse(self, text: str) -> ShadowConnectionResult:
        """Fold every metadata line into one combined result."""
        for line_number, line in enumerate(text.splitlines(), start=1):
            self._parse_line(line, line_number)
        return ShadowConnectionResult(
            features=tuple(self.features),
            clear_all=self.clear_all,
            clear_ids=tuple(self.clear_ids),
            diagnostics=_deduplicate_cycle_diagnostics(self.diagnostics),
            source_count=(
                len(dict.fromkeys(self.processed_documents))
                if self.processed_documents
                else self.source_count
            ),
            recognized_record_count=self.recognized,
            unsupported_record_count=self.unsupported,
            invalid_record_count=self.invalid,
            document_ids=tuple(dict.fromkeys(self.processed_documents)),
        )

    def _parse_line(self, line: str, line_number: int) -> None:
        if (match := _SHADOW_LINE_RE.match(line)) is None:
            self._flag_suspect_line(line, line_number)
            return
        kind = match.group(1).upper()
        raw = line.strip()
        options = self._screened_options(
            kind,
            match.group(2),
            line_number=line_number,
            raw=raw,
        )
        if options is None:
            return
        if self._apply_command(_ParsedCommand(kind, options, line_number, raw)):
            self.recognized += 1

    def _flag_suspect_line(self, line: str, line_number: int) -> None:
        stripped = line.strip()
        suspect = (
            bool(stripped)
            if self.strict_lines
            else _SUSPECT_SNAP_RE.match(line) is not None
        )
        if not suspect:
            return
        self._record_invalid(
            DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
            f"unrecognized LDCad metadata line: {stripped!r}",
            line_number=line_number,
            offending_value=stripped,
        )

    def _screened_options(
        self,
        kind: str,
        raw_options: str,
        *,
        line_number: int,
        raw: str,
    ) -> dict[str, str] | None:
        """Tokenize and screen one record's options; None consumes the line."""
        try:
            options = _tokenize_options(raw_options)
        except ValueError as error:
            self._record_invalid(
                DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                f"invalid LDCad {kind} record: {error}",
                line_number=line_number,
                offending_value=raw,
                cause=error,
            )
            return None
        if (allowed := _SUPPORTED_OPTIONS.get(kind)) is None:
            self.unsupported += 1
            self.diagnostics.append(
                _diagnostic(
                    DiagnosticCode.CONNECTION_UNSUPPORTED_RECORD,
                    f"unsupported LDCad connection record {kind}",
                    line_number=line_number,
                    path=self.path,
                    offending_value=raw,
                ),
            )
            return None
        if unknown := tuple(key for key in options if key not in allowed):
            self.unsupported += 1
            self.diagnostics.extend(
                _diagnostic(
                    DiagnosticCode.CONNECTION_UNSUPPORTED_OPTION,
                    f"unsupported {kind} option {key!r}",
                    line_number=line_number,
                    path=self.path,
                    offending_value=raw,
                )
                for key in unknown
            )
            options = {key: value for key, value in options.items() if key in allowed}
        if missing := tuple(
            key for key in _REQUIRED_OPTIONS.get(kind, ()) if not options.get(key)
        ):
            self._record_invalid(
                DiagnosticCode.CONNECTION_MISSING_REQUIRED_OPTION,
                f"{kind} is missing required option(s): {', '.join(missing)}",
                line_number=line_number,
                offending_value=raw,
            )
            return None
        return options

    def _apply_command(self, command: _ParsedCommand) -> bool:
        """Validate and apply one recognized command; False when it fails."""
        try:
            _validate_common_options(command.kind, command.options)
            match command.kind:
                case "SNAP_CLEAR":
                    self._apply_clear(command.options)
                case "SNAP_INCL":
                    self._apply_include(command)
                case _:
                    self._apply_feature(command)
        except FileNotFoundError as error:
            self._record_invalid(
                DiagnosticCode.CONNECTION_INCLUDE_NOT_FOUND,
                str(error),
                line_number=command.line_number,
                offending_value=command.raw,
                cause=error,
            )
            return False
        except (IndexError, KeyError, TypeError, ValueError) as error:
            self._record_invalid(
                error.code
                if isinstance(error, _MetadataValueError)
                else DiagnosticCode.CONNECTION_INVALID_OPTION_VALUE,
                f"invalid LDCad {command.kind} metadata: {error}",
                line_number=command.line_number,
                offending_value=command.raw,
                cause=error,
            )
            return False
        return True

    def _apply_clear(self, options: dict[str, str]) -> None:
        if identifier := options.get("id"):
            self.clear_ids.append(identifier)
            self.features = [
                feature
                for feature in self.features
                if (feature.metadata_id or "").casefold() != identifier.casefold()
            ]
        else:
            self.clear_all = True
            self.clear_ids.clear()
            self.features.clear()

    def _apply_include(self, command: _ParsedCommand) -> None:
        raw_marker = command.options.get("id")
        marker_occurrence = (
            self.seen_ids.get(raw_marker.casefold(), 0) if raw_marker else 0
        )
        if raw_marker is None:
            marker = f"snap_incl@L{command.line_number}"
        elif marker_occurrence:
            marker = f"{raw_marker}@L{command.line_number}"
        else:
            marker = raw_marker
        included = self.include_resolver(command, (*self.include_chain, marker))
        if raw_marker is not None:
            self.seen_ids[raw_marker.casefold()] = marker_occurrence + 1
        self.features = _overlay_features(
            self.features,
            included.features,
            diagnostics=self.diagnostics,
        )
        self.diagnostics.extend(included.diagnostics)
        self.source_count += included.source_count
        self.processed_documents.extend(included.document_ids)
        self.recognized += included.recognized_record_count
        self.unsupported += included.unsupported_record_count
        self.invalid += included.invalid_record_count

    def _apply_feature(self, command: _ParsedCommand) -> None:
        provenance = ConnectionProvenance(
            source=self.effective_source,
            path=self.path,
            archive_member=self.archive_member,
            line_number=command.line_number,
            command=command.raw,
            include_chain=self.include_chain,
        )
        raw_id = command.options.get("id")
        repeated = raw_id is not None and bool(
            self.seen_ids.get(raw_id.casefold(), 0),
        )
        created = _feature_instances(
            code=self.code,
            command=command,
            source=self.effective_source,
            provenance=provenance,
            seen_ids=self.seen_ids,
        )
        if repeated and raw_id is not None:
            self.features = [
                _suffix_first_repeated_id(feature, raw_id=raw_id)
                for feature in self.features
            ]
        self.features = _overlay_features(
            self.features,
            created,
            diagnostics=self.diagnostics,
        )

    def _record_invalid(
        self,
        diagnostic_code: DiagnosticCode,
        message: str,
        *,
        line_number: int,
        offending_value: object,
        cause: Exception | None = None,
    ) -> None:
        self.invalid += 1
        self.diagnostics.append(
            _diagnostic(
                diagnostic_code,
                message,
                line_number=line_number,
                path=self.path,
                offending_value=offending_value,
                cause=cause,
            ),
        )


def _parse_commands(  # noqa: PLR0913
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
    return _CommandParser(
        code=code,
        path=path,
        archive_member=archive_member,
        effective_source=effective_source,
        include_chain=include_chain,
        include_resolver=include_resolver,
        strict_lines=strict_lines,
        source_count=source_count,
        processed_documents=list(document_ids),
    ).parse(text)


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
