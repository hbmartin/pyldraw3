"""Benchmark tests for geometry operations."""

import pytest
from ldraw.geometry import Matrix, Vector, Identity


@pytest.fixture
def matrix():
    """Create test matrix."""
    return Matrix([
        [1, 0, 0, 10],
        [0, 0.707, -0.707, 0],
        [0, 0.707, 0.707, 0],
        [0, 0, 0, 1]
    ])


@pytest.fixture
def vector():
    """Create test vector."""
    return Vector(1, 2, 3)


def test_matrix_multiplication(benchmark, matrix):
    """Benchmark matrix multiplication."""
    other = Matrix([
        [0.707, 0.707, 0, 0],
        [-0.707, 0.707, 0, 0],
        [0, 0, 1, 5],
        [0, 0, 0, 1]
    ])
    benchmark(matrix.__mul__, other)


def test_matrix_vector_transform(benchmark, matrix, vector):
    """Benchmark matrix-vector transformation."""
    benchmark(matrix.transform_vector, vector)


def test_matrix_inversion(benchmark, matrix):
    """Benchmark matrix inversion."""
    benchmark(matrix.invert)


def test_vector_operations(benchmark, vector):
    """Benchmark vector arithmetic operations."""
    other = Vector(4, 5, 6)
    
    def vector_ops():
        return vector + other, vector - other, vector.dot(other)
    
    benchmark(vector_ops)


def test_identity_matrix_creation(benchmark):
    """Benchmark Identity matrix creation."""
    benchmark(Identity)


def test_matrix_determinant(benchmark, matrix):
    """Benchmark matrix determinant calculation."""
    benchmark(matrix.determinant)