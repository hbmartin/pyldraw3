"""Benchmark tests for geometry operations."""

from collections.abc import Callable
from typing import Any

import pytest

from ldraw.geometry import Identity, Matrix, Vector


@pytest.fixture
def matrix() -> Matrix:
    """Create test matrix."""
    return Matrix(
        [
            [1, 0, 0],
            [0, 0.707, -0.707],
            [0, 0.707, 0.707],
        ],
    )


@pytest.fixture
def vector() -> Vector:
    """Create test vector."""
    return Vector(1, 2, 3)


def test_matrix_multiplication(
    benchmark: Callable[..., Any],
    matrix: Matrix,
) -> None:
    """Benchmark matrix multiplication."""
    other = Matrix(
        [
            [0.707, 0.707, 0],
            [-0.707, 0.707, 0],
            [0, 0, 1],
        ],
    )
    benchmark(matrix.__mul__, other)


def test_matrix_vector_transform(
    benchmark: Callable[..., Any],
    matrix: Matrix,
    vector: Vector,
) -> None:
    """Benchmark matrix-vector transformation."""
    benchmark(matrix.__mul__, vector)


def test_matrix_transpose(benchmark: Callable[..., Any], matrix: Matrix) -> None:
    """Benchmark matrix transposition."""
    benchmark(matrix.transpose)


def test_vector_operations(
    benchmark: Callable[..., Any],
    vector: Vector,
) -> None:
    """Benchmark vector arithmetic operations."""
    other = Vector(4, 5, 6)

    def vector_ops() -> tuple[Vector, Vector, float]:
        return vector + other, vector - other, vector.dot(other)

    benchmark(vector_ops)


def test_identity_matrix_creation(benchmark: Callable[..., Any]) -> None:
    """Benchmark Identity matrix creation."""
    benchmark(Identity)


def test_matrix_determinant(benchmark: Callable[..., Any], matrix: Matrix) -> None:
    """Benchmark matrix determinant calculation."""
    benchmark(matrix.det)
