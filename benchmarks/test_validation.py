"""Serialization-precision duplicate checks on large placement collections."""

from collections.abc import Callable
from typing import Protocol

import pytest

from ldraw.geometry import Matrix, Vector
from ldraw.model import Model
from ldraw.pieces import Piece
from ldraw.validation import iter_duplicate_issues


class _Benchmark(Protocol):
    def pedantic(
        self,
        target: Callable[[], object],
        *,
        setup: Callable[[], None] | None,
        rounds: int,
        iterations: int,
    ) -> object: ...


@pytest.mark.parametrize("fractional", [False, True], ids=["integer", "fractional"])
def test_duplicate_placements(benchmark: _Benchmark, *, fractional: bool) -> None:
    """Measure 100,000 placements without imposing noisy timing assertions."""
    offset = 0.1234567 if fractional else 0
    rotation = Matrix.rotation(x=17, y=31, z=23) if fractional else None
    model = Model(
        objects=[
            Piece.place(
                "3001",
                colour=4,
                position=Vector(index + offset, offset, offset),
                matrix=rotation,
            )
            for index in range(100_000)
        ]
    )
    benchmark.pedantic(
        lambda: tuple(iter_duplicate_issues(model)),
        setup=None,
        rounds=5,
        iterations=1,
    )
