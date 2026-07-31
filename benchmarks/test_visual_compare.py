"""Benchmark tests for silhouette registration."""

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ldraw.visual_compare import AlignmentConfig, register_silhouettes


def _masks(size: int) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Create deterministic reference and candidate silhouettes."""
    reference = np.zeros((size, size), dtype=np.bool_)
    reference[size // 5 : 4 * size // 5, size // 4 : 3 * size // 4] = True
    candidate = np.zeros((size, size), dtype=np.bool_)
    candidate[size // 4 : 3 * size // 4, size // 3 : 2 * size // 3] = True
    return reference, candidate


def test_visual_registration_scale_sweep(benchmark: Callable[..., Any]) -> None:
    """Benchmark a representative multi-scale silhouette registration."""
    reference, candidate = _masks(256)
    config = AlignmentConfig(scale_steps=21)

    benchmark(
        register_silhouettes,
        reference,
        candidate,
        config=config,
    )
