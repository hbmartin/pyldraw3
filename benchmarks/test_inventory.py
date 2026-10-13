"""Comparison costs for large flat, grouped, and repeated nested inventories."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

import pytest

from ldraw.bom import bill_of_materials, compare_inventory, rows_to_csv
from ldraw.cli import main
from ldraw.geometry import Matrix, Vector
from ldraw.model import Model, ModelOccurrence
from ldraw.pieces import Group, Piece


class _Benchmark(Protocol):
    def pedantic(
        self, target: Callable[[], object], *, rounds: int, iterations: int
    ) -> object: ...


class _InheritedModel(Model):
    """Exercise the optimized inherited traversal."""


class _CustomTraversalModel(Model):
    """Exercise the source audit plus authoritative custom occurrence checks."""

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        """Emit unchanged occurrences through a custom entry point."""
        return super().iter_occurrences(
            expand_submodels=expand_submodels, include_steps=include_steps
        )


def comparison_model(workload: str) -> Model:
    """Build 100,000 occurrences, keeping setup outside benchmark timing."""
    nested = workload in {"nested", "custom_nested"}
    group = (
        Group(position=Vector(20, 40, 60), matrix=Matrix.rotation(x=17, y=31, z=23))
        if workload == "grouped"
        else None
    )
    model_type = {
        "inherited": _InheritedModel,
        "custom": _CustomTraversalModel,
    }.get(workload, Model)
    leaf = model_type(
        name="leaf.ldr",
        objects=[
            Piece.place("3001", colour=4, position=Vector(index, 0, 0), group=group)
            for index in range(1_000 if nested else 100_000)
        ],
    )
    if workload == "view":
        root = Model(name="main.ldr", submodels={"leaf.ldr": leaf})
        return root.submodel_view(leaf.name)
    if not nested:
        return leaf
    middle = Model(name="middle.ldr")
    middle.add_submodel(leaf)
    root_type = _CustomTraversalModel if workload == "custom_nested" else Model
    root = root_type(name="main.ldr")
    for index in range(100):
        root.add_submodel(middle, position=Vector(index * 1_000, 0, 0))
    return root


@pytest.mark.parametrize(
    "workload",
    ["flat", "grouped", "nested", "view", "inherited", "custom", "custom_nested"],
)
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


def test_inventory_cli_comparison(benchmark: _Benchmark, tmp_path: Path) -> None:
    """Measure report loading plus comparison of 100,000 flat placements."""
    model = comparison_model("flat")
    source = tmp_path / "model.ldr"
    source.write_text(model.to_ldraw(), encoding="utf-8")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(rows_to_csv(bill_of_materials(model)), encoding="utf-8")
    output = tmp_path / "comparison.json"
    arguments = [
        "bom",
        str(source),
        "--compare",
        str(inventory),
        "--format",
        "json",
        "-o",
        str(output),
    ]
    if benchmark.pedantic(lambda: main(arguments), rounds=5, iterations=1) != 0:
        message = "CLI comparison benchmark must match its exported inventory"
        raise ValueError(message)
