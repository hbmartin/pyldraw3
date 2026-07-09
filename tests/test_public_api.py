"""Tests for the curated top-level public API."""

import subprocess
import sys

import ldraw
from ldraw import (
    bom,
    colour,
    figure,
    geometry,
    model,
    part_geometry,
    part_geometry_types,
    parts,
    pieces,
    validation,
)

EXPECTED_ALL = [
    "BomRow",
    "BoundingBox",
    "CatalogEntry",
    "Colour",
    "Group",
    "Identity",
    "Matrix",
    "MinifigSection",
    "Model",
    "PartCategory",
    "Parts",
    "Person",
    "Piece",
    "Severity",
    "StudReference",
    "ValidationIssue",
    "Vector",
    "XAxis",
    "YAxis",
    "ZAxis",
    "bill_of_materials",
    "download",
    "generate",
    "iter_ldr_issues",
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
    assert ldraw.BomRow is bom.BomRow
    assert ldraw.bill_of_materials is bom.bill_of_materials
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
        subprocess.run(
            [sys.executable, "-c", command],
            capture_output=True,
            check=True,
            text=True,
        )
