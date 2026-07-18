"""Tests for geometry functionality."""

import math
import random

import pytest

from ldraw.geometry import (
    Axis,
    CoordinateSystem,
    Identity,
    Matrix,
    MatrixError,
    Radians,
    Vector,
    Vector2D,
    XAxis,
    YAxis,
    ZAxis,
)


def test_matrix_rmul() -> None:
    m = Identity().scale(1, 2, 3)
    v = Vector(3, 2, 1)

    mul = m * v
    assert mul == Vector(3, 4, 3)


def test_mulothers() -> None:
    m = Identity()
    with pytest.raises(TypeError):
        m * 2
    with pytest.raises(TypeError):
        2 * m


@pytest.fixture
def random_matrix() -> Matrix:
    rng = random.Random(12345)
    return Matrix(rows=[[rng.random() for _ in range(3)] for _ in range(3)])


def test_copy(random_matrix: Matrix) -> None:
    assert random_matrix.copy() == random_matrix


@pytest.mark.parametrize("axis", [XAxis, YAxis, ZAxis])
def test_rotate_radians(random_matrix: Matrix, axis: type[Axis]) -> None:
    original = random_matrix.copy()
    rotated = original.rotate(90, axis=axis)

    rotated = rotated.rotate(3 * math.pi / 2, axis=axis, units=Radians)
    assert rotated.flatten() == pytest.approx(original.flatten())


def test_rotate_wrong_axis(random_matrix: Matrix) -> None:
    with pytest.raises(MatrixError):
        random_matrix.rotate(444, axis=None)


def test_rotate_90_maps_axes_cyclically() -> None:
    cases = [
        (XAxis, Vector(0, 1, 0), (0, 0, 1)),
        (YAxis, Vector(0, 0, 1), (1, 0, 0)),
        (ZAxis, Vector(1, 0, 0), (0, 1, 0)),
    ]
    for axis, source, expected in cases:
        rotated = Identity().rotate(90, axis) * source
        assert (rotated.x, rotated.y, rotated.z) == pytest.approx(expected, abs=1e-12)


def test_rotate_and_scale_post_multiply(random_matrix: Matrix) -> None:
    rotated = random_matrix.rotate(30, axis=YAxis)
    assert rotated.flatten() == pytest.approx(
        (random_matrix * Identity().rotate(30, YAxis)).flatten(),
    )

    scaled = random_matrix.scale(2, 3, 4)
    assert scaled.flatten() == pytest.approx(
        (random_matrix * Identity().scale(2, 3, 4)).flatten(),
    )


def test_scale_applies_in_the_local_frame() -> None:
    m = Identity().rotate(90, ZAxis).scale(2, 1, 1)
    v = m * Vector(1, 0, 0)
    assert (v.x, v.y, v.z) == pytest.approx((0, 2, 0), abs=1e-12)


def test_mul_matrix() -> None:
    m1 = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    m2 = Matrix([[10, 11, 12], [13, 14, 15], [16, 17, 18]])
    m12 = m1 * m2
    assert m12.rows == [[84, 90, 96], [201, 216, 231], [318, 342, 366]]


def test_mul_matrix_vector() -> None:
    m = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    v = Vector(42, 1, 0)
    v2 = m * v
    assert v2 == Vector(44, 173, 302)


def test_is_singular() -> None:
    assert Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 0]]).is_singular()
    assert not Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]]).is_singular()
    assert Matrix([[1e-9, 0, 0], [0, 1, 0], [0, 0, 1]]).is_singular()
    assert not Matrix([[1e-9, 0, 0], [0, 1, 0], [0, 0, 1]]).is_singular(
        tolerance=1e-12,
    )


def test_is_orthonormal() -> None:
    identity = Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert identity.is_orthonormal()
    assert identity.rotate(37, axis=YAxis).is_orthonormal()
    assert not identity.scale(2, 1, 1).is_orthonormal()
    assert identity.scale(1.0000001, 1, 1).is_orthonormal(tolerance=1e-3)


def test_det() -> None:
    assert Identity().det() == pytest.approx(1.0)
    assert Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 10]]).det() == pytest.approx(-3.0)
    assert Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]]).det() == pytest.approx(0.0)


def test_transpose() -> None:
    m = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    transposed = m.transpose()
    assert transposed.rows == [[1, 4, 7], [2, 5, 8], [3, 6, 9]]
    assert transposed.transpose() == m

    transposed.rows = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    assert m.rows == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def test_fix_diagonal() -> None:
    m = Matrix([[0, 1, 0], [1, 0, 0], [0, 0, 1]])
    assert m.fix_diagonal() is True
    assert m.rows[0][0] == 0.001
    assert m.rows[1][1] == 0.001
    assert m.fix_diagonal() is False


def test_init_rejects_non_3x3() -> None:
    with pytest.raises(ValueError, match="3x3"):
        Matrix([[1, 2], [3, 4]])


def test_rows_setter_rejects_non_3x3() -> None:
    m = Identity()
    with pytest.raises(ValueError, match="3x3"):
        m.rows = [[1, 2], [3, 4]]


def test_vector_scalar_multiplication(random_matrix: Matrix) -> None:
    assert Vector(1, 2, 3) * 2 == Vector(2, 4, 6)
    assert 2 * Vector(1, 2, 3) == Vector(2, 4, 6)

    row_multiplied = Vector(1, 0, 0) * random_matrix
    first_row = random_matrix.rows[0]
    assert (row_multiplied.x, row_multiplied.y, row_multiplied.z) == pytest.approx(
        tuple(first_row),
    )


def test_vector_operator_errors() -> None:
    with pytest.raises(TypeError):
        "x" * Vector(1, 2, 3)
    with pytest.raises(ValueError, match="Cannot divide"):
        Vector(1, 2, 3) / "x"


def test_vector_cross_dot() -> None:
    assert Vector(1, 0, 0).cross(Vector(0, 1, 0)) == Vector(0, 0, 1)
    assert Vector(1, 0, 0).dot(Vector(0, 1, 0)) == 0
    assert Vector(1, 2, 3).dot(Vector(4, 5, 6)) == 32


def test_vector_add_sub_div_copy() -> None:
    assert Vector(1, 2, 3) + Vector(4, 5, 6) == Vector(5, 7, 9)
    assert Vector(4, 5, 6) - Vector(1, 2, 3) == Vector(3, 3, 3)
    assert Vector(2, 4, 6) / 2 == Vector(1, 2, 3)
    original = Vector(1, 2, 3)
    duplicate = original.copy()
    assert duplicate == original
    assert duplicate is not original


def test_normalized_returns_unit_copy_and_rejects_zero() -> None:
    v = Vector(3, 0, 4)
    unit = v.normalized()
    assert unit == Vector(0.6, 0.0, 0.8)
    assert v == Vector(3, 0, 4)
    with pytest.raises(ValueError, match="zero-length"):
        Vector(0, 0, 0).normalized()


def test_mutable_geometry_is_unhashable() -> None:
    assert Matrix.__hash__ is None
    assert Vector.__hash__ is None
    assert Vector2D.__hash__ is None


def test_vector2d() -> None:
    assert Vector2D(1, 2) + Vector2D(3, 4) == Vector2D(4, 6)
    assert Vector2D(3, 4) - Vector2D(1, 2) == Vector2D(2, 2)
    assert abs(Vector2D(3, 4)) == pytest.approx(5.0)
    assert 2 * Vector2D(1, 2) == Vector2D(2, 4)
    assert Vector2D(1, 2) * 2 == Vector2D(2, 4)
    assert Vector2D(2, 4) / 2 == Vector2D(1, 2)
    assert Vector2D(1, 0).dot(Vector2D(0, 1)) == 0
    duplicate = Vector2D(1, 2).copy()
    assert duplicate == Vector2D(1, 2)
    assert "1" in repr(Vector2D(1, 2))
    with pytest.raises(TypeError):
        "x" * Vector2D(1, 2)
    with pytest.raises(ValueError, match="Cannot divide"):
        Vector2D(1, 2) / "x"


def test_coordinate_system_project() -> None:
    assert CoordinateSystem().project(Vector(1, 2, 3)) == Vector(1, 2, 3)

    swapped = CoordinateSystem(x=Vector(0, 1, 0), y=Vector(1, 0, 0))
    assert swapped.project(Vector(1, 2, 3)) == Vector(2, 1, 3)
