"""Benchmark tests for parts loading performance."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ldraw.parts import PartCategory, Parts

PARTS_LST: Path = (
    Path(__file__).resolve().parents[1] / "tests" / "test_ldraw" / "ldraw" / "parts.lst"
)


@pytest.fixture
def parts() -> Parts:
    """Create Parts instance for benchmarks."""
    return Parts(PARTS_LST)


def test_parts_initialization(benchmark: Callable[..., Any]) -> None:
    """Benchmark Parts class initialization."""
    benchmark(Parts, PARTS_LST)


def test_parts_loading_single(benchmark: Callable[..., Any], parts: Parts) -> None:
    """Benchmark loading a single part."""
    benchmark(parts.part, code="3001")


def test_parts_loading_multiple(benchmark: Callable[..., Any], parts: Parts) -> None:
    """Benchmark loading multiple parts."""
    part_numbers = ["3001", "box5", "stud", "stud4"]

    def load_multiple() -> list[object]:
        return [parts.part(code=part_number) for part_number in part_numbers]

    benchmark(load_multiple)


def test_parts_search(benchmark: Callable[..., Any], parts: Parts) -> None:
    """Benchmark part category access."""
    benchmark(parts.entries_by_category, PartCategory.BRICK)


def test_parts_catalog_access(benchmark: Callable[..., Any], parts: Parts) -> None:
    """Benchmark accessing parts catalog."""
    benchmark(lambda: list(parts.catalog.by_code)[:100])
