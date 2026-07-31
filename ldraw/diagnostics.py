"""Shared machine-readable diagnostics for report-oriented public APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class Severity(StrEnum):
    """How serious a diagnostic is."""

    ERROR = "error"
    WARNING = "warning"


class DiagnosticCode(StrEnum):
    """Stable codes emitted by PyLDraw report-oriented operations."""

    GENERIC = "generic"
    CATALOG_LIBRARY_MISSING = "catalog.library_missing"
    CATALOG_INDEX_MISSING = "catalog.index_missing"
    CATALOG_INDEX_STALE = "catalog.index_stale"
    CATALOG_INDEX_UNREADABLE = "catalog.index_unreadable"
    CATALOG_PERSIST_FAILED = "catalog.persist_failed"
    GENERATION_FAILED = "generation.failed"
    IO_READ_FAILED = "io.read_failed"
    IO_DECODE_FAILED = "io.decode_failed"
    PARSE_INVALID_LINE = "parse.invalid_line"
    PARSE_INVALID_NUMERIC = "parse.invalid_numeric"
    PARSE_INVALID_COLOUR = "parse.invalid_colour"
    MPD_MISPLACED_NOFILE = "mpd.misplaced_nofile"
    MPD_CONTENT_AFTER_NOFILE = "mpd.content_after_nofile"
    MPD_DUPLICATE_SECTION = "mpd.duplicate_section"
    MPD_UNRESOLVED_SUBMODEL = "mpd.unresolved_submodel"
    MPD_CYCLE = "mpd.cycle"
    MODEL_UNKNOWN_PART = "model.unknown_part"
    MODEL_UNKNOWN_COLOUR = "model.unknown_colour"
    PART_NOT_FOUND = "part.not_found"
    PART_HEADER_INVALID = "part.header_invalid"
    PART_REFERENCE_UNRESOLVED = "part.reference_unresolved"
    PART_REFERENCE_CYCLE = "part.reference_cycle"
    GEOMETRY_INCOMPLETE = "geometry.incomplete"
    DISCOVERY_INVALID_LIBRARY = "discovery.invalid_library"
    DOWNLOAD_PLAN_FAILED = "download.plan_failed"
    DOWNLOAD_INTEGRITY_FAILED = "download.integrity_failed"
    RENDER_UNAVAILABLE = "render.unavailable"
    RENDER_FAILED = "render.failed"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One structured problem, warning, or recovery made by an operation.

    ``line_number`` remains the first field so the historical
    ``ValidationIssue(line_number, message, severity)`` constructor stays
    source compatible. New callers should prefer keyword arguments.
    """

    line_number: int | None = None
    message: str = ""
    severity: Severity = Severity.ERROR
    code: DiagnosticCode | str = field(
        default=DiagnosticCode.GENERIC,
        compare=False,
    )
    path: Path | None = field(default=None, compare=False)
    section: str | None = field(default=None, compare=False)
    offending_value: object | None = field(default=None, compare=False)
    suggestions: tuple[str, ...] = field(default=(), compare=False)
    cause: BaseException | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation, including safe cause details."""
        result: dict[str, Any] = {
            "code": str(self.code),
            "message": self.message,
            "severity": str(self.severity),
            "path": str(self.path) if self.path is not None else None,
            "section": self.section,
            "line_number": self.line_number,
            "offending_value": self.offending_value,
            "suggestions": list(self.suggestions),
            "cause": None,
        }
        if self.cause is not None:
            result["cause"] = {
                "type": type(self.cause).__name__,
                "message": str(self.cause),
            }
        return result


__all__ = ["Diagnostic", "DiagnosticCode", "Severity"]
