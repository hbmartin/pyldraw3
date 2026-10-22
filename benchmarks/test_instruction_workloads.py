"""Instruction construction and cycle analysis without an external parts library."""

from collections.abc import Callable
from typing import Protocol

from ldraw._model_structure import iter_structure_edges
from ldraw.lines import Comment
from ldraw.model import Model
from ldraw.pieces import Piece


class _Benchmark(Protocol):
    def pedantic(
        self,
        target: Callable[[], object],
        *,
        rounds: int,
        iterations: int,
    ) -> object: ...


def _instruction_model() -> Model:
    sections = [
        Model(
            name=f"child-{index}.ldr",
            objects=[
                obj for _ in range(10) for obj in (Piece.place("3001"), Comment("STEP"))
            ],
        )
        for index in range(50)
    ]
    return Model(
        name="main.ldr",
        objects=[Piece.place(section.name) for section in sections],
        submodels={section.name: section for section in sections},
    )


def _unique_model() -> Model:
    sections = [Model(name=f"child-{index}.ldr") for index in range(5_000)]
    return Model(
        name="main.ldr",
        objects=[Piece.place(section.name) for section in sections],
        submodels={section.name: section for section in sections},
    )


def test_instruction_document_construction(benchmark: _Benchmark) -> None:
    """Measure document construction, including source-role ownership."""
    model = _instruction_model()
    benchmark.pedantic(model.instruction_document, rounds=7, iterations=5)


def test_unique_name_graph_analysis(benchmark: _Benchmark) -> None:
    """Measure complete identity-cycle checks with no ambiguous names."""
    model = _unique_model()
    benchmark.pedantic(
        lambda: list(iter_structure_edges(root=model)), rounds=7, iterations=5
    )
