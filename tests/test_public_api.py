"""Tests for the curated top-level public API."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import ldraw
from ldraw import (
    diagnostics,
    part_geometry,
    part_geometry_types,
    parts,
    validation,
)

EXPECTED_ALL = [
    "ALL_CATALOG_SEARCH_FIELDS",
    "BfcCertification",
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
    "Colour",
    "Diagnostic",
    "DiagnosticCode",
    "DownloadPlan",
    "Group",
    "Identity",
    "InstructionBuilder",
    "InstructionDocument",
    "InstructionIssue",
    "InstructionSection",
    "InstructionStep",
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
    "PartFileKind",
    "PartGeometry",
    "PartHistoryEntry",
    "PartInspection",
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
    "RenderBackend",
    "RenderCapability",
    "RenderResult",
    "RenderView",
    "RotationMode",
    "RotationStep",
    "Severity",
    "SkippedGeometry",
    "SkippedOccurrenceGeometry",
    "StudContact",
    "StudReference",
    "ValidationIssue",
    "Vector",
    "XAxis",
    "YAxis",
    "ZAxis",
    "analyze_model",
    "bill_of_materials",
    "bounds_gap",
    "discover_libraries",
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
    "plan_download",
    "prepare_catalog",
    "read_model",
    "render_capabilities",
    "render_preview",
]


def test_all_is_the_expected_sorted_list() -> None:
    assert ldraw.__all__ == EXPECTED_ALL
    assert ldraw.__all__ == sorted(ldraw.__all__)


def test_every_exported_name_resolves() -> None:
    for name in ldraw.__all__:
        assert getattr(ldraw, name) is not None


EXPORT_ORIGINS: dict[str, str] = {
    "ALL_CATALOG_SEARCH_FIELDS": "parts",
    "BfcCertification": "part_metadata",
    "BomRow": "bom",
    "BoundingBox": "part_geometry_types",
    "BoundsGap": "inspection",
    "CameraState": "instructions",
    "CancellationToken": "operations",
    "CatalogBuildOutcome": "session",
    "CatalogBuildReport": "session",
    "CatalogEntry": "parts",
    "CatalogPreparationResult": "session",
    "CatalogSearchField": "parts",
    "Colour": "colour",
    "Diagnostic": "diagnostics",
    "DiagnosticCode": "diagnostics",
    "DownloadPlan": "library_setup",
    "Group": "pieces",
    "Identity": "geometry",
    "InstructionBuilder": "instructions",
    "InstructionDocument": "instructions",
    "InstructionIssue": "instructions",
    "InstructionSection": "instructions",
    "InstructionStep": "instructions",
    "LDrawCapability": "session",
    "LDrawPaths": "session",
    "LDrawSession": "session",
    "LDrawState": "session",
    "LDrawStateReason": "session",
    "LibraryComponent": "library_setup",
    "LibraryInspection": "library_setup",
    "LibraryOrigin": "part_metadata",
    "Matrix": "geometry",
    "MinifigSection": "parts",
    "Model": "model",
    "ModelAnalysis": "analysis",
    "ModelInspection": "inspection",
    "ModelLoadResult": "model",
    "ModelOccurrence": "model",
    "ModelSummary": "model_summary",
    "OccurrenceAttribution": "inspection",
    "OccurrenceContact": "inspection",
    "OccurrenceGeometry": "inspection",
    "OccurrencePathItem": "model",
    "OperationCancelled": "operations",
    "PartCategory": "parts",
    "PartFileKind": "part_metadata",
    "PartGeometry": "part_geometry_types",
    "PartHistoryEntry": "part_metadata",
    "PartInspection": "parts",
    "PartMetadata": "part_metadata",
    "PartReference": "parts",
    "PartReferenceKind": "parts",
    "PartStatus": "part_metadata",
    "Parts": "parts",
    "PartsCatalog": "parts",
    "Person": "figure",
    "Piece": "pieces",
    "PreviewTransform": "part_metadata",
    "ProgressEvent": "progress",
    "ProgressStage": "progress",
    "ProgressUnit": "progress",
    "RenderBackend": "rendering",
    "RenderCapability": "rendering",
    "RenderResult": "rendering",
    "RenderView": "rendering",
    "RotationMode": "instructions",
    "RotationStep": "instructions",
    "Severity": "diagnostics",
    "SkippedGeometry": "model_summary",
    "SkippedOccurrenceGeometry": "inspection",
    "StudContact": "inspection",
    "StudReference": "part_geometry_types",
    "ValidationIssue": "validation",
    "Vector": "geometry",
    "XAxis": "geometry",
    "YAxis": "geometry",
    "ZAxis": "geometry",
    "analyze_model": "analysis",
    "bill_of_materials": "bom",
    "bounds_gap": "inspection",
    "discover_libraries": "library_setup",
    "download": "downloads",
    "ensure_library": "session",
    "generate": "generation",
    "inspect_library": "library_setup",
    "inspect_model": "inspection",
    "iter_instruction_issues": "instructions",
    "iter_ldr_issues": "validation",
    "load_model": "model",
    "model_bounds": "model_summary",
    "parse_model": "model",
    "parse_model_result": "model",
    "plan_download": "library_setup",
    "prepare_catalog": "session",
    "read_model": "model",
    "render_capabilities": "rendering",
    "render_preview": "rendering",
}


def test_every_export_has_a_pinned_origin_module() -> None:
    assert sorted(EXPORT_ORIGINS) == EXPECTED_ALL


def test_top_level_names_are_the_submodule_objects() -> None:
    for name, module_name in EXPORT_ORIGINS.items():
        origin = getattr(ldraw, module_name)
        assert getattr(ldraw, name) is getattr(origin, name), name
    assert ldraw.Severity is validation.Severity
    assert ldraw.ValidationIssue is diagnostics.Diagnostic
    assert part_geometry.BoundingBox is part_geometry_types.BoundingBox
    assert part_geometry.StudReference is part_geometry_types.StudReference


def test_part_geometry_modules_import_in_either_order() -> None:
    for command in (
        "import ldraw.parts; import ldraw.part_geometry",
        "import ldraw.part_geometry; import ldraw.parts",
    ):
        try:
            subprocess.run(
                [sys.executable, "-c", command],
                capture_output=True,
                check=True,
                text=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as error:
            message = (
                f"Import check failed for command: {command}\n"
                f"STDOUT:\n{error.stdout}\n"
                f"STDERR:\n{error.stderr}"
            )
            pytest.fail(message)


def test_parts_module_does_not_import_snippets() -> None:
    tree = ast.parse(Path(parts.__file__).read_text())

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ldraw.snippets":
            pytest.fail("ldraw.parts must not import ldraw.snippets")
        if isinstance(node, ast.Import) and any(
            alias.name == "ldraw.snippets" for alias in node.names
        ):
            pytest.fail("ldraw.parts must not import ldraw.snippets")
