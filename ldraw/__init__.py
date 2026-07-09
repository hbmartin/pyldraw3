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

from ldraw.bom import BomRow, bill_of_materials
from ldraw.colour import Colour
from ldraw.downloads import download
from ldraw.figure import Person
from ldraw.generation import generate
from ldraw.geometry import Identity, Matrix, Vector, XAxis, YAxis, ZAxis
from ldraw.imports import LibraryImporter
from ldraw.model import Model, ModelOccurrence, parse_model, read_model
from ldraw.model_summary import ModelSummary, SkippedGeometry, model_bounds
from ldraw.part_geometry_types import BoundingBox, StudReference
from ldraw.parts import (
    CatalogEntry,
    MinifigSection,
    PartCategory,
    PartReference,
    PartReferenceKind,
    Parts,
)
from ldraw.pieces import Group, Piece
from ldraw.progress import ProgressEvent, ProgressStage
from ldraw.session import (
    LDrawPaths,
    LDrawSession,
    LDrawState,
    LDrawStateReason,
    ensure_library,
)
from ldraw.validation import Severity, ValidationIssue, iter_ldr_issues

__all__ = [
    "BomRow",
    "BoundingBox",
    "CatalogEntry",
    "Colour",
    "Group",
    "Identity",
    "LDrawPaths",
    "LDrawSession",
    "LDrawState",
    "LDrawStateReason",
    "Matrix",
    "MinifigSection",
    "Model",
    "ModelOccurrence",
    "ModelSummary",
    "PartCategory",
    "PartReference",
    "PartReferenceKind",
    "Parts",
    "Person",
    "Piece",
    "ProgressEvent",
    "ProgressStage",
    "Severity",
    "SkippedGeometry",
    "StudReference",
    "ValidationIssue",
    "Vector",
    "XAxis",
    "YAxis",
    "ZAxis",
    "bill_of_materials",
    "download",
    "ensure_library",
    "generate",
    "iter_ldr_issues",
    "model_bounds",
    "parse_model",
    "read_model",
]

# Modern import hook registration: use an instance, not the class
library_importer_instance = LibraryImporter()
if not any(isinstance(hook, LibraryImporter) for hook in sys.meta_path):
    sys.meta_path.insert(0, library_importer_instance)

if __name__ == "__main__":
    from ldraw import cli

    cli.main()
