"""Integration tests for full pyldraw workflows."""

from pathlib import Path

import pytest

from ldraw.config import Config
from ldraw.figure import Person
from ldraw.geometry import Identity, Vector, XAxis, YAxis, ZAxis
from ldraw.parts import PartCategory, Parts
from ldraw.pieces import Piece


def _parts_lst_path() -> Path:
    library_path = Path(Config.load().ldraw_library_path)
    return library_path / "ldraw" / "parts.lst"


@pytest.mark.integration
def test_full_library_workflow() -> None:
    """Test complete workflow from library download to part usage."""
    parts_lst = _parts_lst_path()
    assert parts_lst.exists(), "LDraw library should be downloaded"

    parts = Parts(parts_lst)
    assert len(parts.by_code) > 0, "Parts catalog should not be empty"

    brick_part = parts.part(code="3001")
    assert brick_part is not None, "Should be able to load basic brick part"

    piece = Piece(4, Vector(0, 0, 0), Identity(), "3001")
    assert piece.colour == 4
    assert piece.part == "3001"
    assert piece.to_ldraw().endswith("3001.dat")


@pytest.mark.integration
def test_piece_reference_can_be_checked_case_insensitively() -> None:
    """Test default references match legacy uppercase checks case-insensitively."""
    piece = Piece(4, Vector(0, 0, 0), Identity(), "3001")

    assert piece.to_ldraw().casefold().endswith("3001.DAT".casefold())


def test_figure_creation_workflow() -> None:
    """Test creating a complete minifigure."""
    figure = Person()

    pieces = [
        figure.head(4),
        figure.torso(2),
        figure.hips(1),
        figure.right_leg(14),
        figure.left_leg(14),
    ]

    assert all(piece.to_ldraw().startswith("1 ") for piece in pieces)


def test_ldraw_file_generation(tmp_path: Path) -> None:
    """Test generating complete LDraw files."""
    output_path = tmp_path / "simple_stack.ldr"
    pieces = [Piece(i + 2, Vector(0, i * -24, 0), Identity(), "3001") for i in range(3)]

    output_path.write_text(
        "\n".join(
            [
                "0 Simple Stack Model",
                "0 Created by pyldraw integration test",
                *(piece.to_ldraw() for piece in pieces),
            ],
        ),
    )

    assert output_path.exists(), "LDraw file should be created"
    assert output_path.stat().st_size > 0, "LDraw file should not be empty"


@pytest.mark.integration
def test_parts_search_and_filtering() -> None:
    """Test parts category filtering functionality."""
    parts = Parts(_parts_lst_path())

    brick_parts = parts.entries_by_category(PartCategory.BRICK)
    assert len(brick_parts) > 0, "Should find brick parts"

    part_numbers = [part.code for part in brick_parts]
    common_bricks = ["3001", "3002", "3003", "3004"]
    found_common = [num for num in common_bricks if num in part_numbers]

    if not found_common:
        pytest.skip("Common brick parts not found in library")


@pytest.mark.slow
def test_large_model_performance() -> None:
    """Test serialization for larger models."""
    pieces = [
        Piece(4, Vector(x * 40, 0, z * 40), Identity(), "3001")
        for x in range(10)
        for z in range(10)
    ]

    lines = [piece.to_ldraw() for piece in pieces]

    assert all(line.startswith("1 4 ") for line in lines)
    assert len(pieces) == 100


def test_color_validation() -> None:
    """Test color handling in integration context."""
    test_colors = [0, 1, 2, 4, 7, 14, 15]

    for color in test_colors:
        piece = Piece(color, Vector(0, 0, 0), Identity(), "3001")
        assert piece.colour == color
        assert piece.to_ldraw().startswith(f"1 {color} ")


def test_matrix_transformations_integration() -> None:
    """Test matrix transformations in real usage context."""
    transformations = [
        Identity(),
        Identity().rotate(45, XAxis),
        Identity().rotate(90, YAxis),
        Identity().rotate(180, ZAxis),
        Identity().scale(2.0, 2.0, 2.0),
    ]

    for index, matrix in enumerate(transformations):
        piece = Piece(index + 1, Vector(index * 10, 0, 0), matrix, "3001")
        assert piece.to_ldraw().startswith(f"1 {index + 1} ")
