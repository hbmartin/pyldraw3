"""Shared connection metadata results, independent of parser and source services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ldraw._connection_common import _overlay_features

if TYPE_CHECKING:
    from ldraw.connection_types import ConnectionFeature
    from ldraw.diagnostics import Diagnostic


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
