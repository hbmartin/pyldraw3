"""Memory profiling script for pyldraw operations."""

from pathlib import Path

from ldraw.geometry import Identity, Vector, YAxis
from ldraw.parts import Parts
from ldraw.pieces import Piece

PARTS_LST = (
    Path(__file__).resolve().parents[1] / "tests" / "test_ldraw" / "ldraw" / "parts.lst"
)


@profile
def test_parts_loading() -> list[object]:  # type: ignore[name-defined]
    """Profile memory usage during parts loading."""
    parts = Parts(PARTS_LST)
    part_numbers = ["3001", "box5", "stud", "stud4"]
    return [parts.part(code=part_num) for part_num in part_numbers]


@profile
def test_piece_creation() -> list[Piece]:  # type: ignore[name-defined]
    """Profile memory usage during piece creation."""
    pieces = []

    for index in range(100):
        piece = Piece(4, Vector(index, 0, 0), Identity(), "3001")
        pieces.append(piece)

    return pieces


@profile
def test_geometry_operations() -> tuple[list[object], list[Vector]]:  # type: ignore[name-defined]
    """Profile memory usage during geometry operations."""
    matrices = []
    vectors = []

    for index in range(1_000):
        matrix = Identity().rotate(index * 0.1, YAxis)
        vector = Vector(index, index * 2, index * 3)

        transformed = matrix * vector

        matrices.append(matrix.transpose())
        vectors.append(transformed)

    return matrices, vectors


if __name__ == "__main__":
    print("Starting memory profiling...")

    print("\nProfiling parts loading...")
    parts_result = test_parts_loading()

    print("\nProfiling piece creation...")
    pieces_result = test_piece_creation()

    print("\nProfiling geometry operations...")
    geometry_result = test_geometry_operations()

    print("\nMemory profiling complete!")
