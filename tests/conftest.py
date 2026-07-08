"""Pytest configuration and fixtures."""

import os

import pytest
from hypothesis import settings

settings.register_profile(
    "ci",
    database=None,
    derandomize=True,
    deadline=None,
    max_examples=100,
)
settings.register_profile("dev", database=None, deadline=None)
settings.load_profile("ci" if os.environ.get("CI") else "dev")


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
