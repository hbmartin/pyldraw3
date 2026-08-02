"""Geometry classes for the ldraw Python package."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, overload

import numpy as np

from ldraw.serialization import format_ldraw_number

if TYPE_CHECKING:
    from numpy.typing import NDArray

Number = int | float
MatrixRows = list[list[Number]]


class MatrixError(Exception):
    """Exception raised for matrix operation errors."""

    def __init__(self) -> None:
        super().__init__("Invalid axis specified.")


class Axis:
    """Base class for axis representations."""


class XAxis(Axis):
    """X-axis representation."""


class YAxis(Axis):
    """Y-axis representation."""


class ZAxis(Axis):
    """Z-axis representation."""


class AngleUnits:
    """Base class for angle unit representations."""


class Radians(AngleUnits):
    """Radian angle units."""


class Degrees(AngleUnits):
    """Degree angle units."""


@dataclass(slots=True, init=False)
class Matrix:  # noqa: PLW1641 - mutable, deliberately unhashable like list
    """A 3x3 transformation matrix."""

    _array: NDArray[np.float64]

    def __init__(self, rows: MatrixRows) -> None:
        array = np.asarray(rows, dtype=float)
        if array.shape != (3, 3):
            message = f"Matrix rows must be 3x3, got {array.shape}"
            raise ValueError(message)
        self._array: NDArray[np.float64] = array.copy()

    @classmethod
    def _from_array(cls, array: NDArray[np.float64]) -> Self:
        """Wrap a freshly computed 3x3 float array; the caller yields ownership."""
        matrix = cls.__new__(cls)
        matrix._array = array  # noqa: SLF001
        return matrix

    @property
    def rows(self) -> MatrixRows:
        """Return matrix rows as plain Python lists."""
        return self._array.tolist()

    @rows.setter
    def rows(self, value: MatrixRows) -> None:
        array = np.asarray(value, dtype=float)
        if array.shape != (3, 3):
            message = f"Matrix rows must be 3x3, got {array.shape}"
            raise ValueError(message)
        self._array = array.copy()

    def __repr__(self) -> str:
        rows = [
            ", ".join(format_ldraw_number(value) for value in row) for row in self.rows
        ]
        return f"(({rows[0]}),\n ({rows[1]}),\n ({rows[2]}))"

    @overload
    def __mul__(self, other: Matrix) -> Matrix: ...

    @overload
    def __mul__(self, other: Vector) -> Vector: ...

    def __mul__(self, other: object) -> Matrix | Vector:
        if isinstance(other, Matrix):
            return Matrix._from_array(self._array @ other._array)
        if isinstance(other, Vector):
            x, y, z = self._array @ np.array([other.x, other.y, other.z])
            return Vector(float(x), float(y), float(z))
        return NotImplemented

    @overload
    def __rmul__(self, other: Matrix) -> Matrix: ...

    @overload
    def __rmul__(self, other: Vector) -> Vector: ...

    def __rmul__(self, other: object) -> Matrix | Vector:
        if isinstance(other, Matrix):
            return Matrix._from_array(other._array @ self._array)
        if isinstance(other, Vector):
            x, y, z = np.array([other.x, other.y, other.z]) @ self._array
            return Vector(float(x), float(y), float(z))
        return NotImplemented

    def copy(self) -> Self:
        """Make a copy of this matrix."""
        return type(self)(self.rows)

    def rotate(
        self,
        angle: Number,
        axis: type[Axis],
        units: type[AngleUnits] = Degrees,
    ) -> Matrix:
        """Rotate the matrix by an angle around an axis."""
        radians = math.radians(float(angle)) if units == Degrees else float(angle)
        c = math.cos(radians)
        s = math.sin(radians)

        if axis == XAxis:
            rotation = [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
        elif axis == YAxis:
            rotation = [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
        elif axis == ZAxis:
            rotation = [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]
        else:
            raise MatrixError
        return Matrix._from_array(self._array @ np.asarray(rotation, dtype=float))

    def scale(self, sx: Number, sy: Number, sz: Number) -> Matrix:
        """Scale the matrix on each axis, applied in the local frame like rotate."""
        scaling = np.asarray([[sx, 0, 0], [0, sy, 0], [0, 0, sz]], dtype=float)
        return Matrix._from_array(self._array @ scaling)

    def transpose(self) -> Matrix:
        """Return the transposed matrix."""
        return Matrix._from_array(self._array.T.copy())

    def inverse(self) -> Matrix:
        """Return the inverse transform, raising for a singular matrix."""
        return Matrix._from_array(np.linalg.inv(self._array))

    def det(self) -> float:
        """Return the determinant of the matrix."""
        return float(np.linalg.det(self._array))

    def is_singular(self, *, tolerance: float = 1e-6) -> bool:
        """Return whether the matrix flattens geometry (determinant near zero)."""
        return abs(self.det()) < tolerance

    def is_orthonormal(self, *, tolerance: float = 1e-6) -> bool:
        """Return whether the matrix is a pure rotation or reflection."""
        product = self._array @ self._array.T
        return bool(np.allclose(product, np.eye(3), atol=tolerance))

    def flatten(self) -> tuple[float, ...]:
        """Flatten the matrix in row-major order."""
        return tuple(float(value) for value in self._array.reshape(9))

    def fix_diagonal(self) -> bool:
        """POV-Ray does not like matrices with zero diagonal elements."""
        corrected = False
        for index in range(3):
            if self._array[index, index] == 0.0:
                self._array[index, index] = 0.001
                corrected = True
        return corrected

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Matrix):
            return False
        return self.rows == other.rows


def Identity() -> Matrix:  # noqa: N802
    """Return a transformation matrix representing Identity."""
    return Matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])


@dataclass(slots=True)
class Vector:
    """A vector in 3D."""

    x: Number
    y: Number
    z: Number

    @property
    def repr(self) -> str:
        """Return string representation of vector coordinates."""
        return (
            f"{format_ldraw_number(self.x)}, "
            f"{format_ldraw_number(self.y)}, "
            f"{format_ldraw_number(self.z)}"
        )

    def __repr__(self) -> str:
        return f"<Vector: ({self.repr})>"

    def __add__(self, other: Vector) -> Vector:
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)

    __radd__ = __add__

    def __sub__(self, other: Vector) -> Vector:
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __abs__(self) -> float:
        return float(np.linalg.norm([self.x, self.y, self.z]))

    def __mul__(self, other: object) -> Vector:
        if isinstance(other, int | float):
            return Vector(self.x * other, self.y * other, self.z * other)
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, other: Number) -> Vector:
        if isinstance(other, int | float):
            return Vector(self.x / other, self.y / other, self.z / other)
        message = f"Cannot divide {self.__class__} with {type(other)}"
        raise ValueError(message)

    __div__ = __truediv__

    def copy(self) -> Self:
        """Copy the vector to a new vector containing the same values."""
        return type(self)(self.x, self.y, self.z)

    def cross(self, other: Vector) -> Vector:
        """Cross product."""
        x, y, z = np.cross(
            np.array([self.x, self.y, self.z]),
            np.array([other.x, other.y, other.z]),
        )
        return Vector(float(x), float(y), float(z))

    def dot(self, other: Vector) -> float:
        """Dot product."""
        return float(
            np.dot(
                np.array([self.x, self.y, self.z]),
                np.array([other.x, other.y, other.z]),
            ),
        )

    def normalized(self) -> Vector:
        """Return a unit-length copy of this vector."""
        if (length := abs(self)) == 0:
            message = "Cannot normalize a zero-length vector"
            raise ValueError(message)
        return self / length


@dataclass(slots=True)
class Vector2D:
    """A vector in 2D."""

    x: Number
    y: Number

    def __repr__(self) -> str:
        return (
            f"<Vector2D: ({format_ldraw_number(self.x)}, "
            f"{format_ldraw_number(self.y)}) >"
        )

    def __add__(self, other: Vector2D) -> Vector2D:
        return Vector2D(self.x + other.x, self.y + other.y)

    __radd__ = __add__

    def __sub__(self, other: Vector2D) -> Vector2D:
        return Vector2D(self.x - other.x, self.y - other.y)

    def __abs__(self) -> float:
        return float(np.linalg.norm([self.x, self.y]))

    def __mul__(self, other: object) -> Vector2D:
        if isinstance(other, int | float):
            return Vector2D(self.x * other, self.y * other)
        return NotImplemented

    __rmul__ = __mul__

    def __truediv__(self, other: Number) -> Vector2D:
        if isinstance(other, int | float):
            return Vector2D(self.x / other, self.y / other)
        message = f"Cannot divide {self.__class__} with {type(other)}"
        raise ValueError(message)

    __div__ = __truediv__

    def copy(self) -> Self:
        """Copy the vector to a new vector containing the same values."""
        return type(self)(self.x, self.y)

    def dot(self, other: Vector2D) -> float:
        """Dot product."""
        return float(np.dot(np.array([self.x, self.y]), np.array([other.x, other.y])))


@dataclass(slots=True)
class CoordinateSystem:
    """3D coordinate system representation."""

    x: Vector = field(default_factory=lambda: Vector(1.0, 0.0, 0.0))
    y: Vector = field(default_factory=lambda: Vector(0.0, 1.0, 0.0))
    z: Vector = field(default_factory=lambda: Vector(0.0, 0.0, 1.0))

    def project(self, p: Vector) -> Vector:
        """Project a point onto this coordinate system."""
        return Vector(p.dot(self.x), p.dot(self.y), p.dot(self.z))
