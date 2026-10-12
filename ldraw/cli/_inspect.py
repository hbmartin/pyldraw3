"""Runtime services for the inspect commands."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING
from zipfile import BadZipFile

from ldraw.cli._common import (
    _diagnostic_text,
    _invalid_connection_source,
    _load_parts_with_connection_sources,
    _print_diagnostics,
    _report_connection_source_error,
    _write_report,
)
from ldraw.connection_types import (
    AnnularProfile,
    ConnectionFeature,
    CylindricalProfile,
    FingerProfile,
    GenericProfile,
)
from ldraw.errors import PartError
from ldraw.inspection import (
    ConnectionContact,
    ModelInspection,
    OccurrenceContact,
    StudContact,
    inspect_model,
)
from ldraw.model import load_model
from ldraw.validation import Severity

if TYPE_CHECKING:
    from pathlib import Path

    from ldraw.connection_metadata import ConnectionMetadataReport
    from ldraw.diagnostics import Diagnostic
    from ldraw.geometry import Vector
    from ldraw.part_geometry_types import BoundingBox


def inspect_command(  # noqa: PLR0911, PLR0913 - mirrors explicit CLI controls
    *,
    file: Path,
    output_format: str,
    gap_threshold: float,
    chronological: bool,
    page_marker_prefix: str,
    out: Path | None,
    connection_shadows: tuple[Path, ...] = (),
    studio_metadata: tuple[Path, ...] = (),
) -> int:
    """Inspect exact occurrence geometry, provenance, contacts, and gaps."""
    if gap_threshold < 0:
        print("--gap-threshold must be non-negative", file=sys.stderr)
        return 1
    if (
        error := _invalid_connection_source(
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    ) is not None:
        print(error, file=sys.stderr)
        return 1
    if (
        parts := _load_parts_with_connection_sources(
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    ) is None:
        return 1

    loaded = load_model(file, parts=parts)
    if loaded.model is None:
        _print_diagnostics(loaded.diagnostics, fallback_path=file)
        return 1
    try:
        inspection = inspect_model(
            loaded.model,
            parts=parts,
            page_marker_prefix=page_marker_prefix,
        )
        contacts = inspection.contact_gaps(
            minimum_gap=gap_threshold,
            chronological=chronological,
        )
    except (BadZipFile, OSError) as error:
        _report_connection_source_error(error)
        return 1
    except PartError as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1

    diagnostics = (*loaded.diagnostics, *inspection.diagnostics)
    complete = loaded.complete and inspection.complete
    if output_format == "json":
        text = json.dumps(
            _inspection_data(
                file=file,
                inspection=inspection,
                contacts=contacts,
                diagnostics=diagnostics,
                complete=complete,
                gap_threshold=gap_threshold,
                chronological=chronological,
            ),
            indent=2,
            sort_keys=True,
        )
    else:
        text = _format_inspection_table(
            file=file,
            inspection=inspection,
            contacts=contacts,
            diagnostics=diagnostics,
            complete=complete,
            gap_threshold=gap_threshold,
            chronological=chronological,
        )
    if not _write_report(text, out=out, description="inspection"):
        return 1
    return int(any(item.severity is Severity.ERROR for item in diagnostics))


def _inspection_data(  # noqa: PLR0913 - report inputs are explicit
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
    diagnostics: tuple[Diagnostic, ...],
    complete: bool,
    gap_threshold: float,
    chronological: bool,
) -> dict[str, object]:
    graphs = inspection.connection_graphs()
    return {
        "bounds": _box_data(inspection.bounds),
        "chronological": chronological,
        "complete": complete,
        "connection_contacts": [
            _connection_contact_data(contact)
            for contact in inspection.connection_contacts()
        ],
        "connection_graphs": {
            "confirmed": [_graph_edge_data(edge) for edge in graphs.confirmed.edges],
            "nodes": list(graphs.optimistic.nodes),
            "optimistic": [_graph_edge_data(edge) for edge in graphs.optimistic.edges],
        },
        "diagnostics": [item.to_dict() for item in diagnostics],
        "disconnected": [
            {
                "axis_gaps": _vector_data(contact.gap.axes),
                "gap": contact.gap.distance,
                "nearest_index": contact.nearest.index,
                "nearest_installation_page": (
                    contact.nearest.attribution.installation_page
                ),
                "nearest_part": contact.nearest.occurrence.part_code,
                "occurrence_index": contact.subject.index,
                "occurrence_installation_page": (
                    contact.subject.attribution.installation_page
                ),
                "occurrence_part": contact.subject.occurrence.part_code,
            }
            for contact in contacts
        ],
        "gap_threshold": gap_threshold,
        "geometry_count": len(inspection.occurrences),
        "model": str(file),
        "occurrence_count": inspection.occurrence_count,
        "occurrences": [
            {
                "bounds": _box_data(item.bounds),
                "colour": (
                    item.occurrence.colour.code
                    if item.occurrence.colour.code is not None
                    else item.occurrence.colour.rgb
                ),
                "connection_count": len(item.connections),
                "connections": [
                    _connection_data(connection) for connection in item.connections
                ],
                "connection_metadata": _connection_metadata_data(
                    item.local.connection_metadata,
                ),
                "effective_step_path": list(item.attribution.effective_step_path),
                "index": item.index,
                "installation_page": item.attribution.installation_page,
                "local_point_count": len(item.local.points),
                "local_step_path": list(item.attribution.local_step_path),
                "model_path": list(item.attribution.model_path),
                "page_path": list(item.attribution.page_path),
                "part": item.occurrence.part_code,
                "position": _vector_data(item.occurrence.position),
                "reference_path": list(item.attribution.reference_path),
                "source_line": item.occurrence.source_line,
                "source_line_path": list(item.attribution.source_line_path),
                "source_model": item.occurrence.source_model.name,
                "source_page": item.attribution.source_page,
                "source_step": item.occurrence.source_step,
                "step": item.occurrence.step,
                "step_path": list(item.attribution.step_path),
                "stud_count": len(item.studs),
            }
            for item in inspection.occurrences
        ],
        "skipped_geometry": [
            {
                "diagnostic": skipped.diagnostic.to_dict(),
                "index": skipped.attribution.index,
                "model_path": list(skipped.attribution.model_path),
                "page_path": list(skipped.attribution.page_path),
                "part": skipped.attribution.occurrence.part_code,
                "reason": skipped.reason,
            }
            for skipped in inspection.skipped_geometry
        ],
        "stud_contacts": [
            _stud_contact_data(contact) for contact in inspection.stud_contacts()
        ],
    }


def _format_inspection_table(  # noqa: PLR0913 - report inputs are explicit
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
    diagnostics: tuple[Diagnostic, ...],
    complete: bool,
    gap_threshold: float,
    chronological: bool,
) -> str:
    bounds = (
        "none"
        if inspection.bounds is None
        else (
            f"{_format_vector(inspection.bounds.min)} .. "
            f"{_format_vector(inspection.bounds.max)}"
        )
    )
    lines = [
        f"model: {file}",
        f"complete: {'yes' if complete else 'no'}",
        (
            f"occurrences: {inspection.occurrence_count} "
            f"geometry: {len(inspection.occurrences)} "
            f"skipped: {len(inspection.skipped_geometry)}"
        ),
        f"world bounds: {bounds}",
        f"stud/part contacts: {len(inspection.stud_contacts())}",
        f"connection contacts: {len(inspection.connection_contacts())}",
        "",
        " index  install source part         world origin             model path",
    ]
    for item in inspection.occurrences:
        attribution = item.attribution
        lines.append(
            f"{item.index:6d}  {_page(attribution.installation_page):>7} "
            f"{_page(attribution.source_page):>6} "
            f"{item.occurrence.part_code:<12} "
            f"{_format_vector(item.occurrence.position):<24} "
            f"{' > '.join(attribution.model_path)}"
        )
    lines.extend(
        (
            f"{skipped.attribution.index:6d}  "
            f"{_page(skipped.attribution.installation_page):>7} "
            f"{_page(skipped.attribution.source_page):>6} "
            f"{skipped.attribution.occurrence.part_code:<12} "
            f"SKIPPED: {skipped.reason}"
        )
        for skipped in inspection.skipped_geometry
    )

    mode = "chronological" if chronological else "all occurrences"
    lines.extend(
        (
            "",
            f"nearest AABB gaps > {gap_threshold:g} LDU ({mode}): {len(contacts)}",
        )
    )
    lines.extend(
        (
            f"gap={contact.gap.distance:8.3f} "
            f"#{contact.subject.index}/{contact.subject.occurrence.part_code} "
            f"p{_page(contact.subject.attribution.installation_page)} -> "
            f"#{contact.nearest.index}/{contact.nearest.occurrence.part_code} "
            f"p{_page(contact.nearest.attribution.installation_page)} "
            f"axes={_format_vector(contact.gap.axes)}"
        )
        for contact in contacts
    )
    if diagnostics:
        lines.extend(("", f"diagnostics: {len(diagnostics)}"))
        lines.extend(_diagnostic_text(item) for item in diagnostics)
    return "\n".join(lines)


def _page(page: int | None) -> str:
    return "-" if page is None else str(page)


def _stud_contact_data(contact: StudContact) -> dict[str, object]:
    return {
        "position": _vector_data(contact.position),
        "stud_index": contact.stud_occurrence.index,
        "stud_name": contact.stud.name,
        "stud_part": contact.stud_occurrence.occurrence.part_code,
        "supported_index": contact.supported_occurrence.index,
        "supported_part": contact.supported_occurrence.occurrence.part_code,
        "stud_feature": (
            contact.stud_feature.feature_id
            if contact.stud_feature is not None
            else None
        ),
        "receptacle_feature": (
            contact.receptacle_feature.feature_id
            if contact.receptacle_feature is not None
            else None
        ),
        "residual": (
            _residual_data(contact.residual) if contact.residual is not None else None
        ),
    }


def _connection_contact_data(contact: ConnectionContact) -> dict[str, object]:
    return {
        "first_feature": contact.first.feature_id,
        "first_index": contact.first_occurrence.index,
        "first_kind": contact.first.kind.value,
        "second_feature": contact.second.feature_id,
        "second_index": contact.second_occurrence.index,
        "second_kind": contact.second.kind.value,
        "status": contact.status.value,
        "residual": _residual_data(contact.residual),
    }


def _connection_data(connection: ConnectionFeature) -> dict[str, object]:
    return {
        "axis": _vector_data(connection.axis),
        "compatible_parts": list(connection.compatible_parts),
        "confidence": connection.confidence,
        "feature_id": connection.feature_id,
        "frame": list(connection.frame.flatten()),
        "metadata_id": connection.metadata_id,
        "mirror_inheritance": connection.mirror_inheritance,
        "freedoms": sorted(freedom.value for freedom in connection.freedoms),
        "group": connection.group,
        "kind": connection.kind.value,
        "length": connection.length,
        "name": connection.name,
        "occupied": connection.occupied,
        "occupied_by": connection.occupied_by,
        "owner_code": connection.owner_code,
        "position": _vector_data(connection.position),
        "profile": _connection_profile_data(connection),
        "provenance": list(connection.provenance),
        "connection_provenance": (
            {
                "archive_member": connection.connection_provenance.archive_member,
                "command": connection.connection_provenance.command,
                "include_chain": list(
                    connection.connection_provenance.include_chain,
                ),
                "line_number": connection.connection_provenance.line_number,
                "path": (
                    str(connection.connection_provenance.path)
                    if connection.connection_provenance.path is not None
                    else None
                ),
                "source": connection.connection_provenance.source.value,
            }
            if connection.connection_provenance is not None
            else None
        ),
        "radial": _vector_data(connection.radial),
        "role": connection.role.value,
        "scale_inheritance": connection.scale_inheritance,
        "source": connection.source.value,
    }


def _connection_profile_data(connection: ConnectionFeature) -> dict[str, object]:
    match connection.profile:
        case CylindricalProfile() as profile:
            return {
                "centered": profile.centered,
                "caps": profile.caps.value,
                "friction": profile.friction,
                "sections": [
                    {
                        "flexible": section.flexible,
                        "length": section.length,
                        "radius": section.radius,
                        "shape": section.shape.value,
                    }
                    for section in profile.sections
                ],
                "type": "cylindrical",
            }
        case FingerProfile() as profile:
            return {
                "detents": list(profile.detents),
                "first_role": profile.first_role.value,
                "centered": profile.centered,
                "radius": profile.radius,
                "sequence": list(profile.sequence),
                "type": "finger",
            }
        case AnnularProfile() as profile:
            return {
                "offset": profile.offset,
                "radius": profile.radius,
                "type": "annular",
                "width": profile.width,
            }
        case GenericProfile() as profile:
            return {
                "bounds": (
                    {
                        "dimensions": list(profile.bounds.dimensions),
                        "kind": profile.bounds.kind.value,
                    }
                    if profile.bounds is not None
                    else None
                ),
                "length": profile.length,
                "match": profile.match.value,
                "name": profile.name,
                "placement": profile.placement.value,
                "type": "generic",
            }


def _connection_metadata_data(
    report: ConnectionMetadataReport | None,
) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "coverage": report.coverage.value,
        "diagnostics": [diagnostic.to_dict() for diagnostic in report.diagnostics],
        "invalid_record_count": report.invalid_record_count,
        "part_code": report.part_code,
        "recognized_record_count": report.recognized_record_count,
        "source_count": report.source_count,
        "unsupported_record_count": report.unsupported_record_count,
    }


def _residual_data(residual: object) -> dict[str, object]:
    from ldraw.connection_types import ConnectionResidual  # noqa: PLC0415

    if not isinstance(residual, ConnectionResidual):  # pragma: no cover - typed callers
        message = "expected a ConnectionResidual"
        raise TypeError(message)
    return {
        "alignment": residual.alignment,
        "axial_gap": residual.axial_gap,
        "distance": residual.distance,
        "entry_face_gap": residual.entry_face_gap,
        "penetration": residual.penetration,
        "roll_alignment": residual.roll_alignment,
    }


def _graph_edge_data(edge: object) -> dict[str, object]:
    from ldraw.inspection import ConnectionGraphEdge  # noqa: PLC0415

    if not isinstance(edge, ConnectionGraphEdge):  # pragma: no cover - typed callers
        message = "expected a ConnectionGraphEdge"
        raise TypeError(message)
    return {
        "first": edge.first,
        "first_feature": edge.first_feature_id,
        "residual": _residual_data(edge.residual),
        "second": edge.second,
        "second_feature": edge.second_feature_id,
        "status": edge.status.value,
    }


def _box_data(box: BoundingBox | None) -> dict[str, object] | None:
    if box is None:
        return None
    return {
        "max": _vector_data(box.max),
        "min": _vector_data(box.min),
        "size": _vector_data(box.size),
    }


def _vector_data(vector: Vector) -> list[float]:
    return [float(vector.x), float(vector.y), float(vector.z)]


def _format_vector(vector: Vector) -> str:
    return f"({float(vector.x):g}, {float(vector.y):g}, {float(vector.z):g})"
