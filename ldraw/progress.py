"""Progress events for embeddable setup and generation flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ProgressStage(StrEnum):
    """High-level setup stages reported to embedding applications."""

    DOWNLOAD = "download"
    UNPACK = "unpack"
    PARTS_LIST = "parts-list"
    LIBRARY_GENERATION = "library-generation"
    INDEX_REBUILD = "index-rebuild"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One progress update from a long-running library operation."""

    stage: ProgressStage
    message: str
    current: int | None = None
    total: int | None = None
    path: Path | None = None


ProgressCallback = Callable[[ProgressEvent], None]


def emit_progress(
    on_progress: ProgressCallback | None,
    event: ProgressEvent,
) -> None:
    """Send ``event`` to ``on_progress`` when a callback is configured."""
    if on_progress is not None:
        on_progress(event)
