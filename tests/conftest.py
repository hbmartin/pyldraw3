"""Pytest configuration and fixtures."""

import os

import pytest

from ldraw import LibraryImporter, generate
from ldraw.config import use
from ldraw.utils import ensure_exists


def pytest_addoption(parser) -> None:
    parser.addoption("--integration", action="store_true", help="run integration tests")


def pytest_configure(config) -> None:
    # Skip version-specific download for now
    pass


def pytest_runtest_setup(item) -> None:

    run_integration = item.config.getoption("--integration")

    if run_integration and "integration" not in item.keywords:
        pytest.skip("skipping test not marked as integration")
    elif "integration" in item.keywords and not run_integration:
        pytest.skip("pass --integration option to pytest to run this test")


@pytest.fixture(scope="module")
def library_version():
    config = use("2018-01")
    cached_generated = ".cached-generated"
    config.generated_path = cached_generated

    if not os.path.exists(cached_generated):
        ensure_exists(cached_generated)
        generate(config)

    LibraryImporter.set_config(config=config)

    yield config
    LibraryImporter.clean()
