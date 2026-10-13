"""Comparison costs for large flat, grouped, and repeated nested inventories."""

from collections.abc import Callable
from typing import Protocol

import pytest

from ldraw.bom import bill_of_materials, compare_inventory
from ldraw.geometry import Matrix, Vector
from ldraw.model import Model
from ldraw.pieces import Group, Piece


class _Benchmark(Protocol):
    def pedantic(
        self, target: Callable[[], object], *, rounds: int, iterations: int
    ) -> object: ...


def comparison_model(workload: str) -> Model:
    """Build 100,000 occurrences, keeping setup outside benchmark timing."""
    group = (
        Group(position=Vector(20, 40, 60), matrix=Matrix.rotation(x=17, y=31, z=23))
        if workload == "grouped"
        else None
    )
    leaf = Model(
        name="leaf.ldr",
        objects=[
            Piece.place("3001", colour=4, position=Vector(index, 0, 0), group=group)
            for index in range(1_000 if workload == "nested" else 100_000)
        ],
    )
    if workload != "nested":
        return leaf
    middle = Model(name="middle.ldr")
    middle.add_submodel(leaf)
    root = Model(name="main.ldr")
    for index in range(100):
        root.add_submodel(middle, position=Vector(index * 1_000, 0, 0))
    return root


@pytest.mark.parametrize("workload", ["flat", "grouped", "nested"])
def test_inventory_comparison(benchmark: _Benchmark, workload: str) -> None:
    """Measure complete comparison without imposing CI timing thresholds."""
    model = comparison_model(workload)
    expected = bill_of_materials(model)
    if sum(row.quantity for row in expected) != 100_000:
        message = "comparison benchmark must contain 100,000 occurrences"
        raise ValueError(message)
    benchmark.pedantic(
        lambda: compare_inventory(model, expected), rounds=5, iterations=1
    )
