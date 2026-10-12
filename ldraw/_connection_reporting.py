"""LDCad reporting implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ldraw._connection_results import (
    ConnectionMetadataCoverage,
    ConnectionMetadataReport,
    ShadowConnectionResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.connection_types import ConnectionFeature


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
