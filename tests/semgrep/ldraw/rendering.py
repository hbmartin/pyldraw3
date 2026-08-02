# ruff: noqa: D100, D101, D102, INP001

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

_CACHE_LOCK: AbstractContextManager[bool] = threading.RLock()


class Process:
    def communicate(self, *_args: object, **_kwargs: object) -> tuple[str, str]:
        return "", ""


def _stop_renderer(process: Process) -> tuple[str, str]:
    # ruleid: pyldraw-renderer-shutdown-must-bound-communicate
    process.communicate(input=b"quit")
    # ruleid: pyldraw-renderer-shutdown-must-bound-communicate
    return process.communicate(input=b"quit", timeout=None)


def _drain_forced_renderer(process: Process) -> tuple[str, str]:
    # ok: pyldraw-renderer-shutdown-must-bound-communicate
    return process.communicate(input=b"quit", timeout=5)


@contextmanager
def _preview_cache_prune_claim(cache_root: Path) -> Iterator[bool]:
    yield cache_root.is_dir()


@contextmanager
def _preview_cache_write_claim(cache_root: Path) -> Iterator[None]:
    del cache_root
    yield


def _prune_preview_cache(cache_root: Path) -> None:
    metadata = cache_root.stat()
    retained: list[tuple[float, int, Path]] = []
    # ruleid: pyldraw-preview-cache-eviction-must-use-nanosecond-mtime
    retained.append((metadata.st_mtime, metadata.st_size, cache_root))
    mtime = metadata.st_mtime
    # ruleid: pyldraw-preview-cache-eviction-must-use-nanosecond-mtime
    if cache_root.stat().st_mtime != mtime:
        return
    # ok: pyldraw-preview-cache-eviction-must-use-nanosecond-mtime
    retained.append((metadata.st_mtime_ns, metadata.st_size, cache_root))
    mtime_ns = metadata.st_mtime_ns
    # ok: pyldraw-preview-cache-eviction-must-use-nanosecond-mtime
    if cache_root.stat().st_mtime_ns != mtime_ns:
        return


def _publish_cached_preview(
    cache_root: Path,
    temporary_path: Path,
    cached_path: Path,
) -> None:
    # ruleid: pyldraw-preview-cache-publish-requires-process-claim
    temporary_path.replace(cached_path)
    with _preview_cache_write_claim(cache_root):
        # ok: pyldraw-preview-cache-publish-requires-process-claim
        temporary_path.replace(cached_path)
    with _preview_cache_write_claim(cache_root):  # noqa: SIM117 - lock order explicit
        with _CACHE_LOCK:
            # ok: pyldraw-preview-cache-publish-requires-process-claim
            temporary_path.replace(cached_path)


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
