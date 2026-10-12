"""LDCad sources implementation."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from ldraw._connection_common import (
    _canonical_cycle,
    _diagnostic,
    _normalized_code,
    _ParsedCommand,
)
from ldraw.connection_types import ConnectionSource
from ldraw.diagnostics import Diagnostic, DiagnosticCode


class ShadowLibrarySources:
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
        siblings: tuple[ShadowLibrarySources, ...] = (),
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
        siblings: tuple[ShadowLibrarySources, ...] = (),
    ) -> ShadowConnectionResult:
        from ldraw._connection_features import (  # noqa: PLC0415 - deferred command/parser services
            _transform_include,
        )
        from ldraw._connection_parser import (  # noqa: PLC0415 - deferred command/parser services
            _parse_commands,
        )

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
    libraries: tuple[ShadowLibrarySources, ...],
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


@dataclass(frozen=True, slots=True)
class _SourceText:
    text: str
    path: Path
    archive_member: str | None
    logical_name: str


# Resolve the public result type after the source class is available to the façade.
from ldraw.connection_metadata import ShadowConnectionResult  # noqa: E402
