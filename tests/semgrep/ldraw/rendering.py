# ruff: noqa: D100, D101, D102, INP001

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Process:
    def communicate(self, *_args: object, **_kwargs: object) -> tuple[str, str]:
        return "", ""


def _stop_renderer(process: Process) -> tuple[str, str]:
    # ruleid: pyldraw-renderer-shutdown-must-bound-communicate
    return process.communicate(input=b"quit")


def _drain_forced_renderer(process: Process) -> tuple[str, str]:
    # ok: pyldraw-renderer-shutdown-must-bound-communicate
    return process.communicate(input=b"quit", timeout=5)


@contextmanager
def _preview_cache_prune_claim(cache_root: Path) -> Iterator[bool]:
    yield cache_root.is_dir()


def _prune_preview_cache(cache_root: Path) -> None:
    del cache_root


def _maybe_prune_preview_cache(cache_root: Path, other: Path) -> None:
    # ruleid: pyldraw-preview-cache-prune-requires-process-claim
    _prune_preview_cache(cache_root)
    with _preview_cache_prune_claim(cache_root) as claimed:
        # ruleid: pyldraw-preview-cache-prune-requires-process-claim
        _prune_preview_cache(cache_root)
        if not claimed:
            return
    with _preview_cache_prune_claim(other) as claimed:
        if not claimed:
            return
        # ruleid: pyldraw-preview-cache-prune-requires-process-claim
        _prune_preview_cache(cache_root)
    with _preview_cache_prune_claim(cache_root) as claimed:
        if not claimed:
            return
        # ok: pyldraw-preview-cache-prune-requires-process-claim
        _prune_preview_cache(cache_root)
    with _preview_cache_prune_claim(cache_root) as claimed:
        if claimed:
            # ok: pyldraw-preview-cache-prune-requires-process-claim
            _prune_preview_cache(cache_root)
