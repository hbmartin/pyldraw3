"""Stable public interface for LDCad parsing, sources, and reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ldraw._connection_results import (
    ConnectionMetadataCoverage,
    ConnectionMetadataReport,
    ShadowConnectionResult,
)
from ldraw._connection_sources import ShadowLibrarySources

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from ldraw.connection_types import ConnectionFeature


class LDCadShadowLibrary(ShadowLibrarySources):
    """Read unpacked, ZIP, or CSL LDCad shadow metadata."""


def parse_ldcad_commands(
    code: str,
    commands: Iterable[str],
    *,
    source: str | Path | None = None,
    connection_shadows: Iterable[LDCadShadowLibrary | str | Path] = (),
) -> ShadowConnectionResult:
    """Parse inline SNAP commands without aborting geometry."""
    from ldraw._connection_parser import parse_ldcad_commands as parse  # noqa: PLC0415

    return parse(code, commands, source=source, connection_shadows=connection_shadows)


def parse_ldcad_text(
    code: str,
    text: str,
    *,
    source: str | Path | None = None,
    connection_shadows: Iterable[LDCadShadowLibrary | str | Path] = (),
) -> ShadowConnectionResult:
    """Parse document SNAP commands, retaining source line numbers."""
    from ldraw._connection_parser import parse_ldcad_text as parse  # noqa: PLC0415

    return parse(code, text, source=source, connection_shadows=connection_shadows)


def metadata_report(
    code: str,
    *,
    features: Iterable[ConnectionFeature],
    result: ShadowConnectionResult,
    authoritative: bool = False,
) -> ConnectionMetadataReport:
    """Report coverage of normalized part-local connection features."""
    from ldraw._connection_reporting import metadata_report as report  # noqa: PLC0415

    return report(code, features=features, result=result, authoritative=authoritative)


__all__ = [
    "ConnectionMetadataCoverage",
    "ConnectionMetadataReport",
    "LDCadShadowLibrary",
    "ShadowConnectionResult",
    "metadata_report",
    "parse_ldcad_commands",
    "parse_ldcad_text",
]
