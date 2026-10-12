"""__init__.py - Package file for the ldraw Python package.

Copyright (C) 2008 David Boddie <david@boddie.org.uk>

This file is part of the ldraw Python package.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING, Any

from ldraw.imports import LibraryImporter

if TYPE_CHECKING:
    from ldraw.analysis import ModelAnalysis, analyze_model
    from ldraw.api import ApiEntry, ApiInventory, api_inventory
    from ldraw.bom import (
        BomRow,
        InventoryComparison,
        InventoryDifference,
        bill_of_materials,
        compare_inventory,
        read_inventory,
    )
    from ldraw.catalog_search import CatalogSearchResult
    from ldraw.colour import Colour
    from ldraw.connection_metadata import (
        ConnectionMetadataCoverage,
        ConnectionMetadataReport,
        LDCadShadowLibrary,
    )
    from ldraw.connection_studio import StudioConnectionLibrary
    from ldraw.connection_types import (
        AnnularProfile,
        ConnectionFeature,
        ConnectionFreedom,
        ConnectionKind,
        ConnectionProvenance,
        ConnectionResidual,
        ConnectionRole,
        ConnectionSource,
        ConnectionStatus,
        CylindricalCaps,
        CylindricalProfile,
        CylindricalSection,
        FingerProfile,
        GenericBounds,
        GenericBoundsKind,
        GenericMatch,
        GenericPlacement,
        GenericProfile,
        PartCompatibility,
        SectionShape,
        SnapTransform,
        angular_alignment_within,
        connection_residual,
        connections_compatible,
        snap_transform,
    )
    from ldraw.coverage import Coverage
    from ldraw.diagnosis import DoctorReport, doctor
    from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
    from ldraw.document_io import ExtractionAttribution, ExtractionResult
    from ldraw.downloads import download
    from ldraw.figure import Person
    from ldraw.generation import generate
    from ldraw.geometry import Identity, Matrix, Vector, XAxis, YAxis, ZAxis
    from ldraw.inspection import (
        BoundsGap,
        ConnectionContact,
        ConnectionGraphEdge,
        ConnectionGraphs,
        ConnectionMultigraph,
        ModelInspection,
        OccurrenceAttribution,
        OccurrenceContact,
        OccurrenceGeometry,
        SkippedOccurrenceGeometry,
        SnapCandidate,
        StudContact,
        bounds_gap,
        inspect_model,
    )
    from ldraw.inspection_limits import ContactReport, SnapReport
    from ldraw.instructions import (
        CameraState,
        InstructionBuilder,
        InstructionDocument,
        InstructionIssue,
        InstructionSection,
        InstructionStep,
        RotationMode,
        RotationStep,
        iter_instruction_issues,
    )
    from ldraw.library_setup import (
        DownloadPlan,
        LibraryComponent,
        LibraryInspection,
        discover_libraries,
        inspect_library,
        plan_download,
    )
    from ldraw.measurements import PartMeasurements, part_measurements
    from ldraw.model import (
        Model,
        ModelLoadResult,
        ModelOccurrence,
        OccurrencePathItem,
        load_model,
        parse_model,
        parse_model_result,
        read_model,
    )
    from ldraw.model_summary import ModelSummary, SkippedGeometry, model_bounds
    from ldraw.operations import CancellationToken, OperationCancelled
    from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
    from ldraw.part_metadata import (
        BfcCertification,
        LibraryOrigin,
        PartFileKind,
        PartHistoryEntry,
        PartMetadata,
        PartStatus,
        PreviewTransform,
    )
    from ldraw.parts import (
        ALL_CATALOG_SEARCH_FIELDS,
        CatalogEntry,
        CatalogSearchField,
        MinifigSection,
        PartCategory,
        PartInspection,
        PartReference,
        PartReferenceKind,
        Parts,
        PartsCatalog,
    )
    from ldraw.physical_bom import BomReport, bom_report
    from ldraw.pieces import Group, Piece
    from ldraw.progress import ProgressEvent, ProgressStage, ProgressUnit
    from ldraw.rendering import (
        RenderBackend,
        RenderCapability,
        RenderResult,
        RenderView,
        render_capabilities,
        render_preview,
    )
    from ldraw.resolution import RawGeometry
    from ldraw.session import (
        CatalogBuildOutcome,
        CatalogBuildReport,
        CatalogPreparationResult,
        LDrawCapability,
        LDrawPaths,
        LDrawSession,
        LDrawState,
        LDrawStateReason,
        ensure_library,
        prepare_catalog,
    )
    from ldraw.validation import ValidationIssue, iter_ldr_issues

__all__ = [
    "ALL_CATALOG_SEARCH_FIELDS",
    "AnnularProfile",
    "ApiEntry",
    "ApiInventory",
    "BfcCertification",
    "BomReport",
    "BomRow",
    "BoundingBox",
    "BoundsGap",
    "CameraState",
    "CancellationToken",
    "CatalogBuildOutcome",
    "CatalogBuildReport",
    "CatalogEntry",
    "CatalogPreparationResult",
    "CatalogSearchField",
    "CatalogSearchResult",
    "Colour",
    "ConnectionContact",
    "ConnectionFeature",
    "ConnectionFreedom",
    "ConnectionGraphEdge",
    "ConnectionGraphs",
    "ConnectionKind",
    "ConnectionMetadataCoverage",
    "ConnectionMetadataReport",
    "ConnectionMultigraph",
    "ConnectionProvenance",
    "ConnectionResidual",
    "ConnectionRole",
    "ConnectionSource",
    "ConnectionStatus",
    "ContactReport",
    "Coverage",
    "CylindricalCaps",
    "CylindricalProfile",
    "CylindricalSection",
    "Diagnostic",
    "DiagnosticCode",
    "DoctorReport",
    "DownloadPlan",
    "ExtractionAttribution",
    "ExtractionResult",
    "FingerProfile",
    "GenericBounds",
    "GenericBoundsKind",
    "GenericMatch",
    "GenericPlacement",
    "GenericProfile",
    "Group",
    "Identity",
    "InstructionBuilder",
    "InstructionDocument",
    "InstructionIssue",
    "InstructionSection",
    "InstructionStep",
    "InventoryComparison",
    "InventoryDifference",
    "LDCadShadowLibrary",
    "LDrawCapability",
    "LDrawPaths",
    "LDrawSession",
    "LDrawState",
    "LDrawStateReason",
    "LibraryComponent",
    "LibraryInspection",
    "LibraryOrigin",
    "Matrix",
    "MinifigSection",
    "Model",
    "ModelAnalysis",
    "ModelInspection",
    "ModelLoadResult",
    "ModelOccurrence",
    "ModelSummary",
    "OccurrenceAttribution",
    "OccurrenceContact",
    "OccurrenceGeometry",
    "OccurrencePathItem",
    "OperationCancelled",
    "PartCategory",
    "PartCompatibility",
    "PartFileKind",
    "PartGeometry",
    "PartHistoryEntry",
    "PartInspection",
    "PartMeasurements",
    "PartMetadata",
    "PartReference",
    "PartReferenceKind",
    "PartStatus",
    "Parts",
    "PartsCatalog",
    "Person",
    "Piece",
    "PreviewTransform",
    "ProgressEvent",
    "ProgressStage",
    "ProgressUnit",
    "RawGeometry",
    "RenderBackend",
    "RenderCapability",
    "RenderResult",
    "RenderView",
    "RotationMode",
    "RotationStep",
    "SectionShape",
    "Severity",
    "SkippedGeometry",
    "SkippedOccurrenceGeometry",
    "SnapCandidate",
    "SnapReport",
    "SnapTransform",
    "StudContact",
    "StudReference",
    "StudioConnectionLibrary",
    "ValidationIssue",
    "Vector",
    "XAxis",
    "YAxis",
    "ZAxis",
    "analyze_model",
    "angular_alignment_within",
    "api_inventory",
    "bill_of_materials",
    "bom_report",
    "bounds_gap",
    "compare_inventory",
    "connection_residual",
    "connections_compatible",
    "discover_libraries",
    "doctor",
    "download",
    "ensure_library",
    "generate",
    "inspect_library",
    "inspect_model",
    "iter_instruction_issues",
    "iter_ldr_issues",
    "load_model",
    "model_bounds",
    "parse_model",
    "parse_model_result",
    "part_measurements",
    "plan_download",
    "prepare_catalog",
    "read_inventory",
    "read_model",
    "render_capabilities",
    "render_preview",
    "snap_transform",
]

_EXPORTS = {
    "ModelAnalysis": ("ldraw.analysis", "ModelAnalysis"),
    "analyze_model": ("ldraw.analysis", "analyze_model"),
    "BomRow": ("ldraw.bom", "BomRow"),
    "bill_of_materials": ("ldraw.bom", "bill_of_materials"),
    "Colour": ("ldraw.colour", "Colour"),
    "ConnectionMetadataCoverage": (
        "ldraw.connection_metadata",
        "ConnectionMetadataCoverage",
    ),
    "ConnectionMetadataReport": (
        "ldraw.connection_metadata",
        "ConnectionMetadataReport",
    ),
    "LDCadShadowLibrary": ("ldraw.connection_metadata", "LDCadShadowLibrary"),
    "StudioConnectionLibrary": ("ldraw.connection_studio", "StudioConnectionLibrary"),
    "AnnularProfile": ("ldraw.connection_types", "AnnularProfile"),
    "ConnectionFeature": ("ldraw.connection_types", "ConnectionFeature"),
    "ConnectionFreedom": ("ldraw.connection_types", "ConnectionFreedom"),
    "ConnectionKind": ("ldraw.connection_types", "ConnectionKind"),
    "ConnectionProvenance": ("ldraw.connection_types", "ConnectionProvenance"),
    "ConnectionResidual": ("ldraw.connection_types", "ConnectionResidual"),
    "ConnectionRole": ("ldraw.connection_types", "ConnectionRole"),
    "ConnectionSource": ("ldraw.connection_types", "ConnectionSource"),
    "ConnectionStatus": ("ldraw.connection_types", "ConnectionStatus"),
    "CylindricalCaps": ("ldraw.connection_types", "CylindricalCaps"),
    "CylindricalProfile": ("ldraw.connection_types", "CylindricalProfile"),
    "CylindricalSection": ("ldraw.connection_types", "CylindricalSection"),
    "FingerProfile": ("ldraw.connection_types", "FingerProfile"),
    "GenericBounds": ("ldraw.connection_types", "GenericBounds"),
    "GenericBoundsKind": ("ldraw.connection_types", "GenericBoundsKind"),
    "GenericMatch": ("ldraw.connection_types", "GenericMatch"),
    "GenericPlacement": ("ldraw.connection_types", "GenericPlacement"),
    "GenericProfile": ("ldraw.connection_types", "GenericProfile"),
    "PartCompatibility": ("ldraw.connection_types", "PartCompatibility"),
    "SectionShape": ("ldraw.connection_types", "SectionShape"),
    "SnapTransform": ("ldraw.connection_types", "SnapTransform"),
    "angular_alignment_within": ("ldraw.connection_types", "angular_alignment_within"),
    "connection_residual": ("ldraw.connection_types", "connection_residual"),
    "connections_compatible": ("ldraw.connection_types", "connections_compatible"),
    "snap_transform": ("ldraw.connection_types", "snap_transform"),
    "Diagnostic": ("ldraw.diagnostics", "Diagnostic"),
    "DiagnosticCode": ("ldraw.diagnostics", "DiagnosticCode"),
    "Severity": ("ldraw.diagnostics", "Severity"),
    "download": ("ldraw.downloads", "download"),
    "Person": ("ldraw.figure", "Person"),
    "generate": ("ldraw.generation", "generate"),
    "Identity": ("ldraw.geometry", "Identity"),
    "Matrix": ("ldraw.geometry", "Matrix"),
    "Vector": ("ldraw.geometry", "Vector"),
    "XAxis": ("ldraw.geometry", "XAxis"),
    "YAxis": ("ldraw.geometry", "YAxis"),
    "ZAxis": ("ldraw.geometry", "ZAxis"),
    "BoundsGap": ("ldraw.inspection", "BoundsGap"),
    "ConnectionContact": ("ldraw.inspection", "ConnectionContact"),
    "ConnectionGraphEdge": ("ldraw.inspection", "ConnectionGraphEdge"),
    "ConnectionGraphs": ("ldraw.inspection", "ConnectionGraphs"),
    "ConnectionMultigraph": ("ldraw.inspection", "ConnectionMultigraph"),
    "ModelInspection": ("ldraw.inspection", "ModelInspection"),
    "OccurrenceAttribution": ("ldraw.inspection", "OccurrenceAttribution"),
    "OccurrenceContact": ("ldraw.inspection", "OccurrenceContact"),
    "OccurrenceGeometry": ("ldraw.inspection", "OccurrenceGeometry"),
    "SkippedOccurrenceGeometry": ("ldraw.inspection", "SkippedOccurrenceGeometry"),
    "SnapCandidate": ("ldraw.inspection", "SnapCandidate"),
    "StudContact": ("ldraw.inspection", "StudContact"),
    "bounds_gap": ("ldraw.inspection", "bounds_gap"),
    "inspect_model": ("ldraw.inspection", "inspect_model"),
    "CameraState": ("ldraw.instructions", "CameraState"),
    "InstructionBuilder": ("ldraw.instructions", "InstructionBuilder"),
    "InstructionDocument": ("ldraw.instructions", "InstructionDocument"),
    "InstructionIssue": ("ldraw.instructions", "InstructionIssue"),
    "InstructionSection": ("ldraw.instructions", "InstructionSection"),
    "InstructionStep": ("ldraw.instructions", "InstructionStep"),
    "RotationMode": ("ldraw.instructions", "RotationMode"),
    "RotationStep": ("ldraw.instructions", "RotationStep"),
    "iter_instruction_issues": ("ldraw.instructions", "iter_instruction_issues"),
    "DownloadPlan": ("ldraw.library_setup", "DownloadPlan"),
    "LibraryComponent": ("ldraw.library_setup", "LibraryComponent"),
    "LibraryInspection": ("ldraw.library_setup", "LibraryInspection"),
    "discover_libraries": ("ldraw.library_setup", "discover_libraries"),
    "inspect_library": ("ldraw.library_setup", "inspect_library"),
    "plan_download": ("ldraw.library_setup", "plan_download"),
    "Model": ("ldraw.model", "Model"),
    "ModelLoadResult": ("ldraw.model", "ModelLoadResult"),
    "ModelOccurrence": ("ldraw.model", "ModelOccurrence"),
    "OccurrencePathItem": ("ldraw.model", "OccurrencePathItem"),
    "load_model": ("ldraw.model", "load_model"),
    "parse_model": ("ldraw.model", "parse_model"),
    "parse_model_result": ("ldraw.model", "parse_model_result"),
    "read_model": ("ldraw.model", "read_model"),
    "ModelSummary": ("ldraw.model_summary", "ModelSummary"),
    "SkippedGeometry": ("ldraw.model_summary", "SkippedGeometry"),
    "model_bounds": ("ldraw.model_summary", "model_bounds"),
    "CancellationToken": ("ldraw.operations", "CancellationToken"),
    "OperationCancelled": ("ldraw.operations", "OperationCancelled"),
    "BoundingBox": ("ldraw.part_geometry_types", "BoundingBox"),
    "PartGeometry": ("ldraw.part_geometry_types", "PartGeometry"),
    "StudReference": ("ldraw.part_geometry_types", "StudReference"),
    "BfcCertification": ("ldraw.part_metadata", "BfcCertification"),
    "LibraryOrigin": ("ldraw.part_metadata", "LibraryOrigin"),
    "PartFileKind": ("ldraw.part_metadata", "PartFileKind"),
    "PartHistoryEntry": ("ldraw.part_metadata", "PartHistoryEntry"),
    "PartMetadata": ("ldraw.part_metadata", "PartMetadata"),
    "PartStatus": ("ldraw.part_metadata", "PartStatus"),
    "PreviewTransform": ("ldraw.part_metadata", "PreviewTransform"),
    "ALL_CATALOG_SEARCH_FIELDS": ("ldraw.parts", "ALL_CATALOG_SEARCH_FIELDS"),
    "CatalogEntry": ("ldraw.parts", "CatalogEntry"),
    "CatalogSearchField": ("ldraw.parts", "CatalogSearchField"),
    "MinifigSection": ("ldraw.parts", "MinifigSection"),
    "PartCategory": ("ldraw.parts", "PartCategory"),
    "PartInspection": ("ldraw.parts", "PartInspection"),
    "PartReference": ("ldraw.parts", "PartReference"),
    "PartReferenceKind": ("ldraw.parts", "PartReferenceKind"),
    "Parts": ("ldraw.parts", "Parts"),
    "PartsCatalog": ("ldraw.parts", "PartsCatalog"),
    "Group": ("ldraw.pieces", "Group"),
    "Piece": ("ldraw.pieces", "Piece"),
    "ProgressEvent": ("ldraw.progress", "ProgressEvent"),
    "ProgressStage": ("ldraw.progress", "ProgressStage"),
    "ProgressUnit": ("ldraw.progress", "ProgressUnit"),
    "RenderBackend": ("ldraw.rendering", "RenderBackend"),
    "RenderCapability": ("ldraw.rendering", "RenderCapability"),
    "RenderResult": ("ldraw.rendering", "RenderResult"),
    "RenderView": ("ldraw.rendering", "RenderView"),
    "render_capabilities": ("ldraw.rendering", "render_capabilities"),
    "render_preview": ("ldraw.rendering", "render_preview"),
    "CatalogBuildOutcome": ("ldraw.session", "CatalogBuildOutcome"),
    "CatalogBuildReport": ("ldraw.session", "CatalogBuildReport"),
    "CatalogPreparationResult": ("ldraw.session", "CatalogPreparationResult"),
    "LDrawCapability": ("ldraw.session", "LDrawCapability"),
    "LDrawPaths": ("ldraw.session", "LDrawPaths"),
    "LDrawSession": ("ldraw.session", "LDrawSession"),
    "LDrawState": ("ldraw.session", "LDrawState"),
    "LDrawStateReason": ("ldraw.session", "LDrawStateReason"),
    "ensure_library": ("ldraw.session", "ensure_library"),
    "prepare_catalog": ("ldraw.session", "prepare_catalog"),
    "ValidationIssue": ("ldraw.validation", "ValidationIssue"),
    "iter_ldr_issues": ("ldraw.validation", "iter_ldr_issues"),
    "InventoryComparison": ("ldraw.bom", "InventoryComparison"),
    "InventoryDifference": ("ldraw.bom", "InventoryDifference"),
    "compare_inventory": ("ldraw.bom", "compare_inventory"),
    "read_inventory": ("ldraw.bom", "read_inventory"),
}

_EXPORTS.update(
    {
        "api_inventory": ("ldraw.api", "api_inventory"),
        "ApiEntry": ("ldraw.api", "ApiEntry"),
        "ApiInventory": ("ldraw.api", "ApiInventory"),
        "CatalogSearchResult": ("ldraw.catalog_search", "CatalogSearchResult"),
        "doctor": ("ldraw.diagnosis", "doctor"),
        "DoctorReport": ("ldraw.diagnosis", "DoctorReport"),
    }
)


_EXPORTS.update(
    {
        "BomReport": ("ldraw.physical_bom", "BomReport"),
        "bom_report": ("ldraw.physical_bom", "bom_report"),
        "Coverage": ("ldraw.coverage", "Coverage"),
        "ExtractionResult": ("ldraw.document_io", "ExtractionResult"),
        "ExtractionAttribution": ("ldraw.document_io", "ExtractionAttribution"),
        "SnapReport": ("ldraw.inspection_limits", "SnapReport"),
        "ContactReport": ("ldraw.inspection_limits", "ContactReport"),
        "RawGeometry": ("ldraw.resolution", "RawGeometry"),
        "PartMeasurements": ("ldraw.measurements", "PartMeasurements"),
        "part_measurements": ("ldraw.measurements", "part_measurements"),
    }
)

# Cache the lightweight legacy module before exporting the generation function.
# Later imports of ldraw.generate reuse sys.modules and cannot shadow the export.
_legacy_generate = import_module("ldraw.generate")
globals().pop("generate", None)


def __getattr__(name: str) -> Any:  # noqa: ANN401 - heterogeneous public exports
    """Resolve and cache public exports on first access."""
    if name not in _EXPORTS:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include deferred public exports in introspection."""
    return sorted(set(globals()) | set(__all__))


library_importer_instance = LibraryImporter()
if not any(isinstance(hook, LibraryImporter) for hook in sys.meta_path):
    sys.meta_path.insert(0, library_importer_instance)
