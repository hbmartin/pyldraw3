"""Benchmark tests for parts loading performance."""

import pytest
from ldraw import config
from ldraw.parts import Parts


@pytest.fixture
def parts():
    """Create Parts instance for benchmarks."""
    return Parts(config.get_ldraw_path())


def test_parts_initialization(benchmark, parts):
    """Benchmark Parts class initialization."""
    benchmark(Parts, config.get_ldraw_path())


def test_parts_loading_single(benchmark, parts):
    """Benchmark loading a single part."""
    benchmark(parts.part, "3001")


def test_parts_loading_multiple(benchmark, parts):
    """Benchmark loading multiple parts."""
    part_numbers = ["3001", "3002", "3004", "3005", "3022"]
    
    def load_multiple():
        return [parts.part(num) for num in part_numbers]
    
    benchmark(load_multiple)


def test_parts_search(benchmark, parts):
    """Benchmark part search functionality."""
    benchmark(parts.parts_by_name, "brick")


def test_parts_catalog_access(benchmark, parts):
    """Benchmark accessing parts catalog."""
    benchmark(lambda: list(parts.parts.keys())[:100])