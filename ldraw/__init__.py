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

import sys

from ldraw.analysis import ModelAnalysis, analyze_model
from ldraw.bom import BomRow, bill_of_materials
from ldraw.colour import Colour
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.downloads import download
from ldraw.figure import Person
from ldraw.generation import generate
from ldraw.geometry import Identity, Matrix, Vector, XAxis, YAxis, ZAxis
from ldraw.imports import LibraryImporter
from ldraw.inspection import (
    BoundsGap,
    ModelInspection,
    OccurrenceAttribution,
    OccurrenceContact,
    OccurrenceGeometry,
    SkippedOccurrenceGeometry,
    StudContact,
    bounds_gap,
    inspect_model,
)
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

# Modern import hook registration: use an instance, not the class
library_importer_instance = LibraryImporter()
if not any(isinstance(hook, LibraryImporter) for hook in sys.meta_path):
    sys.meta_path.insert(0, library_importer_instance)
