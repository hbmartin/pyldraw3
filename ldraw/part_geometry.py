"""Geometry queries over resolved part files: bounding boxes and studs.

LDraw part files place their geometry around a conventional origin (for
bricks: the plane under the studs, with the body extending towards +Y and
studs towards -Y). These helpers resolve a part's subfile tree and answer
the two questions a placement tool needs — how big is the part, and where
are its studs — without the caller reading ``.dat`` files by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from weakref import WeakKeyDictionary

from ldraw.connection_inference import (
    StudSocketEvidence,
    derive_stud_socket_evidence,
    infer_part_connections,
    mark_internal_fit_occupied,
    normalize_connections,
    primitive_connections,
    same_interface,
)
from ldraw.connection_metadata import (
    ConnectionMetadataCoverage,
    ShadowConnectionResult,
    metadata_report,
    parse_ldcad_text,
)
from ldraw.connection_types import ConnectionSource
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError, PartError
from ldraw.geometry import Vector
from ldraw.lines import Line, OptionalLine, Quadrilateral, Triangle
from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from ldraw.connection_metadata import (
        ConnectionMetadataReport,
        LDCadShadowLibrary,
    )
    from ldraw.connection_types import ConnectionFeature
    from ldraw.part import Part

logger = logging.getLogger("ldraw")

_STUD_PREFIX = "stud"
_INFERRED_SOURCES: frozenset[ConnectionSource] = frozenset(
    {
        ConnectionSource.HEURISTIC,
        ConnectionSource.PRIMITIVE,
        ConnectionSource.SHORTCUT,
    },
)
_METADATA_SOURCES: frozenset[ConnectionSource] = frozenset(
    {
        ConnectionSource.LDCAD_INLINE,
        ConnectionSource.LDCAD_SHADOW,
        ConnectionSource.STUDIO,
        ConnectionSource.OVERRIDE,
    },
)

__all__ = [
    "BoundingBox",
    "PartGeometry",
    "StudReference",
    "clear_part_geometry_cache",
    "part_bounding_box",
    "part_connections",
    "part_geometry",
    "part_studs",
]


class _PartGeometryLibrary(Protocol):
    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part: ...


@runtime_checkable
class _CatalogDescriptionSource(Protocol):
    def description_for(self, code: str) -> str | None: ...


@runtime_checkable
class _CompatibleTyresSource(Protocol):
    def compatible_tyres(self, rim_code: str) -> tuple[str, ...]: ...


@runtime_checkable
class _CompatibleRimsSource(Protocol):
    def compatible_rims(self, tyre_code: str) -> tuple[str, ...]: ...


@runtime_checkable
class _ConnectionMetadataSource(Protocol):
    def _connection_shadows_for_inline(self) -> tuple[LDCadShadowLibrary, ...]: ...

    def _connection_metadata_for(
        self,
        code: str,
    ) -> tuple[ShadowConnectionResult, ...]: ...


@runtime_checkable
class _ConnectionDocumentResultSource(Protocol):
    def _connection_document_results(
        self,
        codes: frozenset[str],
    ) -> tuple[ShadowConnectionResult, ...]: ...


@runtime_checkable
class _ConnectionOverrideSource(Protocol):
    def _connection_overrides_for(
        self,
        code: str,
    ) -> tuple[tuple[ConnectionFeature, ...], bool]: ...


@dataclass(frozen=True, slots=True)
class _LocalGeometry:
    """Memoized per-file geometry, in the file's own coordinates."""

    description: str
    box: BoundingBox | None
    points: tuple[Vector, ...]
    studs: tuple[StudReference, ...]
    connections: tuple[ConnectionFeature, ...]
    deferred_socket_evidence: tuple[StudSocketEvidence, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    connection_metadata: ConnectionMetadataReport | None = None
    metadata_result: ShadowConnectionResult = field(
        default_factory=ShadowConnectionResult,
    )
    resolved_codes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _CombinedConnectionMetadata:
    """Document-level metadata shared by repeated geometry queries."""

    diagnostics: tuple[Diagnostic, ...]
    report: ConnectionMetadataReport | None


_caches: WeakKeyDictionary[_PartGeometryLibrary, dict[str, _LocalGeometry | None]] = (
    WeakKeyDictionary()
)
_metadata_caches: WeakKeyDictionary[
    _PartGeometryLibrary,
    dict[str, _CombinedConnectionMetadata],
] = WeakKeyDictionary()


def part_bounding_box(parts: _PartGeometryLibrary, code: str) -> BoundingBox:
    """Axis-aligned bounding box of a part's geometry, in LDU.

    Subfiles are resolved recursively and the expanded drawable points are
    transformed before the box is folded, including under oblique transforms.
    Unresolvable subfiles are skipped with a warning.

    Raises ``PartNotFoundError`` for an unknown code and
    ``NoGeometryError`` when the part draws nothing. Read failures
    (``OSError``/``UnicodeError``) on the part's own file are tolerated
    the same way as unresolvable subfiles: the file contributes no
    geometry, so the query raises ``NoGeometryError`` rather than the
    underlying IO error.
    """
    local = _require_local(parts, code)
    if local.box is None:
        raise NoGeometryError(code)
    return local.box


def part_geometry(parts: _PartGeometryLibrary, code: str) -> PartGeometry:
    """Return exact expanded points, bounds, connectors, and diagnostics."""
    local = _require_local(parts, code)
    combined_metadata = _combined_connection_metadata(parts, code, local)
    return PartGeometry(
        code=code,
        description=local.description,
        bounds=local.box,
        points=local.points,
        studs=local.studs,
        connections=local.connections,
        diagnostics=(*local.diagnostics, *combined_metadata.diagnostics),
        connection_metadata=combined_metadata.report,
    )


def _combined_connection_metadata(
    parts: _PartGeometryLibrary,
    code: str,
    local: _LocalGeometry,
) -> _CombinedConnectionMetadata:
    """Combine and cache document-level metadata for one normalized code."""
    cache = _metadata_cache_for(parts)
    key = _local_key(code)
    if (cached := cache.get(key)) is not None:
        return _metadata_as_requested(combined=cached, code=code)

    metadata_result = local.metadata_result
    document_diagnostics: list[Diagnostic] = []
    has_document_result = False
    if isinstance(parts, _ConnectionDocumentResultSource):
        for result in parts._connection_document_results(  # noqa: SLF001
            local.resolved_codes,
        ):
            if not (
                result.source_count
                or result.recognized_record_count
                or result.unsupported_record_count
                or result.invalid_record_count
                or result.diagnostics
            ):
                continue
            has_document_result = True
            previous_diagnostic_count = len(metadata_result.diagnostics)
            metadata_result = metadata_result.combined(result)
            document_diagnostics.extend(
                metadata_result.diagnostics[previous_diagnostic_count:],
            )
    connection_metadata = local.connection_metadata
    if has_document_result:
        connection_metadata = metadata_report(
            code,
            features=local.connections,
            result=metadata_result,
            authoritative=(
                connection_metadata is not None
                and connection_metadata.coverage is ConnectionMetadataCoverage.COMPLETE
            ),
        )
    combined = _CombinedConnectionMetadata(
        diagnostics=tuple(document_diagnostics),
        report=connection_metadata,
    )
    cache[key] = combined
    return _metadata_as_requested(combined=combined, code=code)


def _metadata_as_requested(
    *,
    combined: _CombinedConnectionMetadata,
    code: str,
) -> _CombinedConnectionMetadata:
    """Restate a cached report under the caller's part-code spelling.

    The caches merge case and slash variants of one part code, so a stored
    report carries whichever spelling populated it first; the report handed
    back must instead match the ``PartGeometry.code`` of the current call.
    """
    report = combined.report
    if report is None or report.part_code == code:
        return combined
    return replace(combined, report=replace(report, part_code=code))


def part_studs(parts: _PartGeometryLibrary, code: str) -> tuple[StudReference, ...]:
    """All stud primitives a part places, in the part's own coordinates.

    Stud groups and subparts are expanded down to individual ``stud*``
    primitives; recursion stops at each stud so nothing is counted twice.
    Filter with ``StudReference.is_top_stud`` (or use
    ``Parts.stud_positions``) to keep only upward connectors.
    """
    return _require_local(parts, code).studs


def part_connections(
    parts: _PartGeometryLibrary,
    code: str,
) -> tuple[ConnectionFeature, ...]:
    """Return all detected physical connection features for a part."""
    return _require_local(parts, code).connections


def clear_part_geometry_cache(parts: _PartGeometryLibrary | None = None) -> None:
    """Clear derived geometry for one parts library or for all libraries."""
    if parts is None:
        _caches.clear()
        _metadata_caches.clear()
    else:
        _caches.pop(parts, None)
        _metadata_caches.pop(parts, None)


def _require_local(parts: _PartGeometryLibrary, code: str) -> _LocalGeometry:
    cached = _cache_for(parts).get(_local_key(code))
    if cached is not None and cached.box is not None:
        # Cache hit with drawable geometry: skip re-resolving the file path.
        return cached
    parts.part(code=code)  # raises the precise PartError for this code
    local = _local_geometry(parts, code, frozenset())
    if local is None:
        raise NoGeometryError(code)  # pragma: no cover - cache raced with disk
    return local


def _cache_for(parts: _PartGeometryLibrary) -> dict[str, _LocalGeometry | None]:
    return _caches.setdefault(parts, {})


def _metadata_cache_for(
    parts: _PartGeometryLibrary,
) -> dict[str, _CombinedConnectionMetadata]:
    return _metadata_caches.setdefault(parts, {})


def _local_key(code: str) -> str:
    return code.replace("\\", "/").casefold()


def _local_geometry(
    parts: _PartGeometryLibrary,
    code: str,
    visiting: frozenset[str],
) -> _LocalGeometry | None:
    key = _local_key(code)
    if key in visiting:
        return _reference_cycle_geometry(code)
    cache = _cache_for(parts)
    if key in cache:
        return cache[key]

    source = _load_geometry_source(parts, code)
    if isinstance(source, _LocalGeometry):
        cache[key] = source
        return source
    part, objects = source
    (
        box,
        points,
        studs,
        connections,
        inherited_socket_evidence,
        diagnostics,
        inherited_metadata,
        resolved_codes,
    ) = _fold_objects(
        parts,
        code=code,
        description=part.description,
        objects=objects,
        visiting=visiting | {key},
    )
    (
        connections,
        deferred_socket_evidence,
        connection_report,
        metadata_result,
    ) = _resolve_connections(
        parts,
        code=code,
        description=part.description,
        path=part.path,
        box=box,
        connections=connections,
        inherited_socket_evidence=inherited_socket_evidence,
        diagnostics=diagnostics,
        inherited_metadata=inherited_metadata,
    )
    local = _LocalGeometry(
        description=part.description,
        box=box.box(),
        points=tuple(points),
        studs=tuple(studs),
        connections=tuple(connections),
        deferred_socket_evidence=deferred_socket_evidence,
        diagnostics=tuple(diagnostics),
        connection_metadata=connection_report,
        metadata_result=metadata_result,
        resolved_codes=frozenset((*resolved_codes, key)),
    )
    cache[key] = local
    return local


def _reference_cycle_geometry(code: str) -> _LocalGeometry:
    error_message = f"subfile reference cycle at {code!r}"
    logger.warning("%s; skipping", error_message)
    return _LocalGeometry(
        description=code,
        box=None,
        points=(),
        studs=(),
        connections=(),
        connection_metadata=metadata_report(
            code,
            features=(),
            result=ShadowConnectionResult(),
        ),
        diagnostics=(
            Diagnostic(
                message=error_message,
                severity=Severity.WARNING,
                code=DiagnosticCode.PART_REFERENCE_CYCLE,
                offending_value=code,
            ),
        ),
    )


def _load_geometry_source(
    parts: _PartGeometryLibrary,
    code: str,
) -> tuple[Part, list[object]] | _LocalGeometry:
    part: Part | None = None
    try:
        part = parts.part(code=code)
        return part, list(part.objects)
    except (OSError, PartError, UnicodeError) as error:
        message = error.message if isinstance(error, PartError) else str(error)
        logger.warning("skipping unresolvable subfile %r: %s", code, message)
        return _LocalGeometry(
            description=code,
            box=None,
            points=(),
            studs=(),
            connections=(),
            connection_metadata=metadata_report(
                code,
                features=(),
                result=ShadowConnectionResult(),
            ),
            diagnostics=(
                Diagnostic(
                    line_number=(
                        error.line_number if isinstance(error, PartError) else None
                    ),
                    message=message,
                    severity=Severity.WARNING,
                    code=DiagnosticCode.PART_REFERENCE_UNRESOLVED,
                    path=(
                        Path(error.source)
                        if isinstance(error, PartError) and error.source is not None
                        else part.path
                        if part is not None
                        else None
                    ),
                    offending_value=code,
                    cause=error,
                ),
            ),
        )


def _fold_objects(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    objects: list[object],
    visiting: frozenset[str],
) -> tuple[
    _BoxAccumulator,
    list[Vector],
    list[StudReference],
    list[ConnectionFeature],
    list[StudSocketEvidence],
    list[Diagnostic],
    ShadowConnectionResult,
    set[str],
]:
    box = _BoxAccumulator()
    points: list[Vector] = []
    studs: list[StudReference] = []
    connections: list[ConnectionFeature] = []
    socket_evidence: list[StudSocketEvidence] = []
    diagnostics: list[Diagnostic] = []
    metadata_results: list[ShadowConnectionResult] = []
    resolved_codes: set[str] = set()
    piece_instance = 0
    for obj in objects:
        match obj:
            case Line() | Triangle() | Quadrilateral():
                for point in obj.points:
                    box.add(point)
                    points.append(point.copy())
            case OptionalLine():
                # Points 3 and 4 only control visibility; they can sit far
                # off the surface and must not stretch the box.
                box.add(obj.point1)
                box.add(obj.point2)
                points.extend((obj.point1.copy(), obj.point2.copy()))
            case Piece():
                _fold_child(
                    parts=parts,
                    piece=obj,
                    box=box,
                    points=points,
                    studs=studs,
                    connections=connections,
                    socket_evidence=socket_evidence,
                    diagnostics=diagnostics,
                    visiting=visiting,
                    parent_code=code,
                    parent_description=description,
                    traversal_marker=(f"{_local_key(obj.part)}@R{piece_instance}"),
                    metadata_results=metadata_results,
                    resolved_codes=resolved_codes,
                )
                piece_instance += 1
    return (
        box,
        points,
        studs,
        connections,
        socket_evidence,
        diagnostics,
        _metadata_statistics(metadata_results),
        resolved_codes,
    )


def _resolve_connections(  # noqa: PLR0913 - resolution inputs are explicit
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    path: Path,
    box: _BoxAccumulator,
    connections: list[ConnectionFeature],
    inherited_socket_evidence: list[StudSocketEvidence],
    diagnostics: list[Diagnostic],
    inherited_metadata: ShadowConnectionResult,
) -> tuple[
    list[ConnectionFeature],
    tuple[StudSocketEvidence, ...],
    ConnectionMetadataReport,
    ShadowConnectionResult,
]:
    connections = list(normalize_connections(connections))
    catalog_part = _is_catalog_part(parts, code)
    socket_derivation = derive_stud_socket_evidence(
        features=connections,
        inherited=inherited_socket_evidence,
        bounds=box.box(),
        bounds_fallback=catalog_part,
    )
    connections = list(socket_derivation.features)
    connections = _infer_catalog_connections(
        parts,
        code=code,
        description=description,
        bounds=box.box(),
        connections=connections,
    )
    inline_result = parse_ldcad_text(
        code,
        path.read_text(encoding="utf-8-sig"),
        source=path,
        connection_shadows=(
            parts._connection_shadows_for_inline()  # noqa: SLF001
            if isinstance(parts, _ConnectionMetadataSource)
            else ()
        ),
    )
    clear_socket_evidence = inline_result.clear_all
    metadata_results = [inherited_metadata, inline_result]
    connections, conflict_diagnostics = _apply_connection_metadata_result(
        connections=connections,
        result=inline_result,
    )
    metadata_diagnostics = [*inline_result.diagnostics, *conflict_diagnostics]
    report_extra_diagnostics = [*conflict_diagnostics]
    if isinstance(parts, _ConnectionMetadataSource):
        for contribution in parts._connection_metadata_for(code):  # noqa: SLF001
            clear_socket_evidence = clear_socket_evidence or contribution.clear_all
            connections, conflicts = _apply_connection_metadata_result(
                connections=connections,
                result=contribution,
            )
            metadata_results.append(contribution)
            metadata_diagnostics.extend((*contribution.diagnostics, *conflicts))
            report_extra_diagnostics.extend(conflicts)
    (
        connections,
        override_diagnostics,
        has_authoritative_override,
        override_replaced_existing,
    ) = _apply_connection_overrides(
        parts=parts,
        code=code,
        connections=connections,
    )
    clear_socket_evidence = clear_socket_evidence or override_replaced_existing
    metadata_diagnostics.extend(override_diagnostics)
    report_extra_diagnostics.extend(override_diagnostics)
    connections = _supersede_inferred_interfaces(connections)
    connections, deferred_socket_evidence = _resolve_socket_evidence(
        connections=connections,
        evidence=socket_derivation.evidence,
        cleared=clear_socket_evidence,
    )
    if catalog_part and " with tyre " in description.casefold():
        connections = list(
            mark_internal_fit_occupied(connections, assembly_code=code),
        )
    connections = _stable_feature_ids(connections)
    diagnostics.extend(metadata_diagnostics)
    statistics = _metadata_statistics(metadata_results)
    report_result = replace(
        statistics,
        diagnostics=(*statistics.diagnostics, *report_extra_diagnostics),
    )
    return (
        connections,
        deferred_socket_evidence,
        metadata_report(
            code,
            features=connections,
            result=report_result,
            authoritative=has_authoritative_override,
        ),
        report_result,
    )


def _fold_child(  # noqa: PLR0913 - traversal outputs are explicit
    *,
    parts: _PartGeometryLibrary,
    piece: Piece,
    box: _BoxAccumulator,
    points: list[Vector],
    studs: list[StudReference],
    connections: list[ConnectionFeature],
    socket_evidence: list[StudSocketEvidence],
    diagnostics: list[Diagnostic],
    visiting: frozenset[str],
    parent_code: str,
    parent_description: str,
    traversal_marker: str,
    metadata_results: list[ShadowConnectionResult],
    resolved_codes: set[str],
) -> None:
    local = _local_geometry(parts, piece.part, visiting)
    if local is None:
        return
    diagnostics.extend(local.diagnostics)
    metadata_results.append(local.metadata_result)
    resolved_codes.update(local.resolved_codes)
    for point in local.points:
        transformed = piece.position + piece.matrix * point
        box.add(transformed)
        points.append(transformed)
    stem = _local_key(piece.part).rpartition("/")[2]
    inferred = primitive_connections(
        parent_code=parent_code,
        parent_description=parent_description,
        stem=stem,
        description=local.description,
        bounds=local.box,
        position=piece.position,
        matrix=piece.matrix,
    )
    connections.extend(
        replace(
            feature,
            feature_id=f"{traversal_marker}/{feature.feature_id or stem}",
        )
        for feature in inferred
    )
    invalid_records: dict[tuple[str, int | None], Diagnostic] = {}
    for feature in local.connections:
        diagnostic_count = len(diagnostics)
        transformed = _transformed_child_connection(
            parts=parts,
            feature=feature,
            piece=piece,
            parent_code=parent_code,
            traversal_marker=traversal_marker,
            diagnostics=diagnostics,
        )
        if transformed is not None:
            connections.append(transformed)
            continue
        provenance = feature.connection_provenance
        key = (
            _connection_origin(feature),
            provenance.line_number if provenance is not None else None,
        )
        if len(diagnostics) > diagnostic_count:
            invalid_records.setdefault(key, diagnostics[-1])
    if invalid_records:
        metadata_results.append(
            ShadowConnectionResult(
                invalid_record_count=len(invalid_records),
                diagnostics=tuple(invalid_records.values()),
            ),
        )
    socket_evidence.extend(
        _transformed_socket_evidence(
            parts=parts,
            evidence=evidence,
            piece=piece,
            parent_code=parent_code,
            traversal_marker=traversal_marker,
            diagnostics=diagnostics,
        )
        for evidence in local.deferred_socket_evidence
    )
    if stem.startswith(_STUD_PREFIX):
        studs.append(
            StudReference(
                name=stem,
                description=local.description,
                position=piece.position.copy(),
                up=piece.matrix * Vector(0, -1, 0),
            ),
        )
        return
    studs.extend(
        StudReference(
            name=stud.name,
            description=stud.description,
            position=piece.position + piece.matrix * stud.position,
            up=piece.matrix * stud.up,
        )
        for stud in local.studs
    )


def _transformed_child_connection(  # noqa: PLR0913 - transform context is explicit
    *,
    parts: _PartGeometryLibrary,
    feature: ConnectionFeature,
    piece: Piece,
    parent_code: str,
    traversal_marker: str,
    diagnostics: list[Diagnostic],
) -> ConnectionFeature | None:
    transformed = feature.transformed(position=piece.position, matrix=piece.matrix)
    if (
        feature.confidence > 0
        and transformed.confidence <= 0
        and feature.source
        in {
            ConnectionSource.LDCAD_INLINE,
            ConnectionSource.LDCAD_SHADOW,
            ConnectionSource.STUDIO,
        }
    ):
        provenance = feature.connection_provenance
        diagnostics.append(
            Diagnostic(
                message=(
                    f"connection feature {feature.feature_id!r} from "
                    f"{_connection_origin(feature)} rejected under invalid "
                    "scale or reflection"
                ),
                severity=Severity.WARNING,
                code=DiagnosticCode.CONNECTION_INVALID_TRANSFORM,
                path=provenance.path if provenance is not None else None,
                line_number=(
                    provenance.line_number if provenance is not None else None
                ),
                offending_value=feature.feature_id,
            ),
        )
        return None
    transformed = replace(
        transformed,
        feature_id=(
            f"{traversal_marker}/"
            f"{feature.feature_id or feature.metadata_id or feature.kind.value}"
        ),
    )
    return (
        transformed
        if _is_catalog_part(parts, piece.part)
        else replace(transformed, owner_code=parent_code)
    )


def _transformed_socket_evidence(  # noqa: PLR0913 - transform context is explicit
    *,
    parts: _PartGeometryLibrary,
    evidence: StudSocketEvidence,
    piece: Piece,
    parent_code: str,
    traversal_marker: str,
    diagnostics: list[Diagnostic],
) -> StudSocketEvidence:
    return StudSocketEvidence(
        visible=(),
        deferred=_transformed_socket_features(
            parts=parts,
            features=evidence.deferred,
            piece=piece,
            parent_code=parent_code,
            traversal_marker=traversal_marker,
            diagnostics=diagnostics,
        ),
        interfaces=_transformed_socket_features(
            parts=parts,
            features=evidence.interfaces,
            piece=piece,
            parent_code=parent_code,
            traversal_marker=traversal_marker,
            diagnostics=diagnostics,
        ),
    )


def _transformed_socket_features(  # noqa: PLR0913 - transform context is explicit
    *,
    parts: _PartGeometryLibrary,
    features: tuple[ConnectionFeature, ...],
    piece: Piece,
    parent_code: str,
    traversal_marker: str,
    diagnostics: list[Diagnostic],
) -> tuple[ConnectionFeature, ...]:
    transformed: list[ConnectionFeature] = []
    for feature in features:
        result = _transformed_child_connection(
            parts=parts,
            feature=feature,
            piece=piece,
            parent_code=parent_code,
            traversal_marker=traversal_marker,
            diagnostics=diagnostics,
        )
        if result is not None:
            transformed.append(result)
    return tuple(transformed)


def _compatible_parts(
    parts: _PartGeometryLibrary,
    code: str,
    description: str,
) -> tuple[str, ...]:
    normalized = description.strip(" ~=_|-").casefold()
    if normalized.startswith("wheel rim ") and isinstance(
        parts,
        _CompatibleTyresSource,
    ):
        return tuple(parts.compatible_tyres(code))
    if normalized.startswith("tyre ") and isinstance(
        parts,
        _CompatibleRimsSource,
    ):
        return tuple(parts.compatible_rims(code))
    return ()


def _infer_catalog_connections(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    description: str,
    bounds: BoundingBox | None,
    connections: list[ConnectionFeature],
) -> list[ConnectionFeature]:
    if not _is_catalog_part(parts, code):
        return connections
    return list(
        infer_part_connections(
            code=code,
            description=description,
            bounds=bounds,
            existing=connections,
            compatible_parts=_compatible_parts(parts, code, description),
        ),
    )


def _is_catalog_part(parts: _PartGeometryLibrary, code: str) -> bool:
    if not isinstance(parts, _CatalogDescriptionSource):
        return True
    return parts.description_for(code) is not None


def _apply_connection_metadata_result(
    *,
    connections: list[ConnectionFeature],
    result: ShadowConnectionResult,
) -> tuple[list[ConnectionFeature], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    if result.clear_all:
        connections.clear()
    elif result.clear_ids:
        cleared = {identifier.casefold() for identifier in result.clear_ids}
        connections = [
            feature
            for feature in connections
            if (feature.metadata_id or "").casefold() not in cleared
        ]
    for feature in result.features:
        feature_key = (feature.feature_id or "").casefold()
        replacement = next(
            (
                index
                for index, previous in enumerate(connections)
                if feature.feature_id is not None
                and (previous.feature_id or "").casefold() == feature_key
            ),
            None,
        )
        if replacement is None:
            connections.append(feature)
            continue
        previous = connections[replacement]
        connections[replacement] = feature
        diagnostics.append(_feature_conflict(previous, feature))
    return list(normalize_connections(connections)), tuple(diagnostics)


def _supersede_inferred_interfaces(
    connections: list[ConnectionFeature],
) -> list[ConnectionFeature]:
    """Drop inferred features whose interface authoritative metadata covers.

    Metadata attached to primitives (offLibShadow style) arrives through
    subfile inheritance rather than part-level overlay, so colocated
    primitive- and heuristic-derived duplicates are removed here after every
    source has been applied.
    """
    authoritative = [
        feature
        for feature in connections
        if feature.source in _METADATA_SOURCES and feature.confidence > 0
    ]
    if not authoritative:
        return connections
    return [
        feature
        for feature in connections
        if feature.source not in _INFERRED_SOURCES
        or not any(same_interface(feature, other) for other in authoritative)
    ]


def _resolve_socket_evidence(
    *,
    connections: list[ConnectionFeature],
    evidence: tuple[StudSocketEvidence, ...],
    cleared: bool,
) -> tuple[list[ConnectionFeature], tuple[StudSocketEvidence, ...]]:
    authoritative = tuple(
        feature
        for feature in connections
        if feature.source in _METADATA_SOURCES and feature.confidence > 0
    )
    rejected_visible: list[ConnectionFeature] = []
    deferred: list[StudSocketEvidence] = []
    for item in evidence:
        covered = cleared or any(
            _metadata_covers_socket_evidence(
                evidence=item,
                authoritative=feature,
            )
            for feature in authoritative
        )
        if covered:
            rejected_visible.extend(item.visible)
        elif item.deferred:
            deferred.append(
                StudSocketEvidence(
                    visible=(),
                    deferred=item.deferred,
                    interfaces=item.interfaces,
                ),
            )
    if rejected_visible:
        connections = [
            feature
            for feature in connections
            if feature.source not in _INFERRED_SOURCES
            or not any(feature == rejected for rejected in rejected_visible)
        ]
    return connections, tuple(deferred)


def _metadata_covers_socket_evidence(
    *,
    evidence: StudSocketEvidence,
    authoritative: ConnectionFeature,
) -> bool:
    return any(
        _same_owned_interface(inferred=interface, authoritative=authoritative)
        for interface in evidence.interfaces
    )


def _same_owned_interface(
    *,
    inferred: ConnectionFeature,
    authoritative: ConnectionFeature,
) -> bool:
    if (
        inferred.owner_code is not None
        and authoritative.owner_code is not None
        and inferred.owner_code.casefold() != authoritative.owner_code.casefold()
    ):
        return False
    return same_interface(inferred, authoritative)


def _metadata_statistics(
    results: list[ShadowConnectionResult],
) -> ShadowConnectionResult:
    """Aggregate metadata evidence once per canonical source document."""
    seen_documents: set[str] = set()
    diagnostics: list[Diagnostic] = []
    source_count = 0
    recognized_record_count = 0
    unsupported_record_count = 0
    invalid_record_count = 0
    for result in results:
        documents = tuple(dict.fromkeys(result.document_ids))
        if documents:
            new_documents = tuple(
                document for document in documents if document not in seen_documents
            )
            if not new_documents:
                continue
            seen_documents.update(new_documents)
            source_count += len(new_documents)
        else:
            source_count += result.source_count
        diagnostics.extend(result.diagnostics)
        recognized_record_count += result.recognized_record_count
        unsupported_record_count += result.unsupported_record_count
        invalid_record_count += result.invalid_record_count
    return ShadowConnectionResult(
        diagnostics=tuple(diagnostics),
        source_count=source_count,
        recognized_record_count=recognized_record_count,
        unsupported_record_count=unsupported_record_count,
        invalid_record_count=invalid_record_count,
        document_ids=tuple(sorted(seen_documents)),
    )


def _apply_connection_overrides(
    parts: _PartGeometryLibrary,
    *,
    code: str,
    connections: list[ConnectionFeature],
) -> tuple[list[ConnectionFeature], tuple[Diagnostic, ...], bool, bool]:
    if not isinstance(parts, _ConnectionOverrideSource):
        return connections, (), False, False
    features, replace_existing = parts._connection_overrides_for(code)  # noqa: SLF001
    if replace_existing:
        connections = []
    resolved, diagnostics = _apply_connection_metadata_result(
        connections=connections,
        result=ShadowConnectionResult(features=features),
    )
    return resolved, diagnostics, bool(features or replace_existing), replace_existing


def _stable_feature_ids(
    features: list[ConnectionFeature],
) -> list[ConnectionFeature]:
    bases = [
        feature.feature_id or f"{feature.source.value}:{feature.kind.value}"
        for feature in features
    ]
    totals = {base: bases.count(base) for base in dict.fromkeys(bases)}
    seen: dict[str, int] = {}
    values: list[ConnectionFeature] = []
    for feature, base in zip(features, bases, strict=True):
        instance = seen.get(base, 0)
        seen[base] = instance + 1
        identifier = base if totals[base] == 1 else f"{base}@I{instance}"
        values.append(replace(feature, feature_id=identifier))
    return values


def _feature_conflict(
    losing: ConnectionFeature,
    winning: ConnectionFeature,
) -> Diagnostic:
    return Diagnostic(
        message=(
            f"connection feature {winning.feature_id!r} from "
            f"{_connection_origin(winning)} overrides {_connection_origin(losing)}"
        ),
        severity=Severity.WARNING,
        code=DiagnosticCode.CONNECTION_FEATURE_CONFLICT,
        path=(
            winning.connection_provenance.path
            if winning.connection_provenance is not None
            else None
        ),
        line_number=(
            winning.connection_provenance.line_number
            if winning.connection_provenance is not None
            else None
        ),
        offending_value=winning.feature_id,
    )


def _connection_origin(feature: ConnectionFeature) -> str:
    provenance = feature.connection_provenance
    if provenance is None:
        return ", ".join(feature.provenance) or feature.source.value
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


class _BoxAccumulator:
    """Folds points into an axis-aligned min/max pair."""

    def __init__(self) -> None:
        self._min: Vector | None = None
        self._max: Vector | None = None

    def add(self, point: Vector) -> None:
        if self._min is None or self._max is None:
            self._min = point.copy()
            self._max = point.copy()
            return
        self._min.x = min(self._min.x, point.x)
        self._min.y = min(self._min.y, point.y)
        self._min.z = min(self._min.z, point.z)
        self._max.x = max(self._max.x, point.x)
        self._max.y = max(self._max.y, point.y)
        self._max.z = max(self._max.z, point.z)

    def box(self) -> BoundingBox | None:
        if self._min is None or self._max is None:
            return None
        return BoundingBox(min=self._min.copy(), max=self._max.copy())
