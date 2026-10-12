"""Cold and warm geometry, inspection, and analysis against a pinned library."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest

from benchmarks.synthetic_model import PART_CODES, synthetic_model
from ldraw._library_content import library_content_sha256
from ldraw.analysis import analyze_model
from ldraw.dirs import get_cache_dir
from ldraw.inspection import inspect_model
from ldraw.part_geometry import clear_part_geometry_cache
from ldraw.parts import Parts


class _Benchmark(Protocol):
    def pedantic(
        self,
        target: Callable[[], object],
        *,
        setup: Callable[[], None] | None,
        rounds: int,
        iterations: int,
    ) -> object: ...


@pytest.fixture
def pinned_parts() -> Parts:
    """Use the same dated library content as the connection regression corpus."""
    path = Path(get_cache_dir()) / "2018-02" / "ldraw" / "parts.lst"
    if not path.is_file():
        pytest.fail(
            "Download the pinned library: uv run ldraw download --version 2018-02 --yes"
        )
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "tests/snapshots/connections-2018-02-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest["schema_version"] != 2
        or library_content_sha256(path.parent) != manifest["library_content_sha256"]
    ):
        pytest.fail("Pinned benchmark library content mismatch; redownload 2018-02.")
    return Parts(path)


@pytest.mark.parametrize("warm", [False, True], ids=["cold", "warm"])
@pytest.mark.parametrize("operation", ["geometry", "inspection", "analysis"])
def test_model_workload(
    benchmark: _Benchmark, pinned_parts: Parts, *, warm: bool, operation: str
) -> None:
    """Measure end-to-end operations, separating recursive geometry caches."""
    model = synthetic_model()
    operations: dict[str, Callable[[], object]] = {
        "geometry": lambda: tuple(pinned_parts.geometry(code) for code in PART_CODES),
        "inspection": lambda: inspect_model(model, parts=pinned_parts),
        "analysis": lambda: analyze_model(model, parts=pinned_parts),
    }
    run = operations[operation]
    if warm:
        run()
    benchmark.pedantic(
        run,
        setup=None if warm else lambda: clear_part_geometry_cache(pinned_parts),
        rounds=7,
        iterations=1,
    )
