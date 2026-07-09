"""Tests for the curated top-level public API."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import ldraw
from ldraw import (
    bom,
    colour,
    figure,
    geometry,
    model,
    model_summary,
    part_geometry,
    part_geometry_types,
    parts,
    pieces,
    progress,
    session,
    validation,
)

EXPECTED_ALL = [
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


def test_all_is_the_expected_sorted_list() -> None:
    assert ldraw.__all__ == EXPECTED_ALL
    assert ldraw.__all__ == sorted(ldraw.__all__)


def test_every_exported_name_resolves() -> None:
    for name in ldraw.__all__:
        assert getattr(ldraw, name) is not None


def test_top_level_names_are_the_submodule_objects() -> None:
    assert ldraw.Model is model.Model
    assert ldraw.Piece is pieces.Piece
    assert ldraw.Group is pieces.Group
    assert ldraw.Person is figure.Person
    assert ldraw.Colour is colour.Colour
    assert ldraw.Vector is geometry.Vector
    assert ldraw.Matrix is geometry.Matrix
    assert ldraw.Parts is parts.Parts
    assert ldraw.PartReference is parts.PartReference
    assert ldraw.PartReferenceKind is parts.PartReferenceKind
    assert ldraw.BomRow is bom.BomRow
    assert ldraw.bill_of_materials is bom.bill_of_materials
    assert ldraw.LDrawSession is session.LDrawSession
    assert ldraw.LDrawPaths is session.LDrawPaths
    assert ldraw.LDrawState is session.LDrawState
    assert ldraw.LDrawStateReason is session.LDrawStateReason
    assert ldraw.ensure_library is session.ensure_library
    assert ldraw.ProgressEvent is progress.ProgressEvent
    assert ldraw.ProgressStage is progress.ProgressStage
    assert ldraw.ModelOccurrence is model.ModelOccurrence
    assert ldraw.ModelSummary is model_summary.ModelSummary
    assert ldraw.SkippedGeometry is model_summary.SkippedGeometry
    assert ldraw.model_bounds is model_summary.model_bounds
    assert ldraw.ValidationIssue is validation.ValidationIssue
    assert ldraw.Severity is validation.Severity
    assert ldraw.iter_ldr_issues is validation.iter_ldr_issues
    assert ldraw.BoundingBox is part_geometry_types.BoundingBox
    assert ldraw.StudReference is part_geometry_types.StudReference
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
