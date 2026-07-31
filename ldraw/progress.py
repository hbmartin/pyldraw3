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
    FINGERPRINT = "fingerprint"
    INDEX_LOAD = "index-load"
    INDEX_REBUILD = "index-rebuild"
    LIBRARY_DISCOVERY = "library-discovery"
    VALIDATION = "validation"
    RENDER = "render"
    DONE = "done"


class ProgressUnit(StrEnum):
    """Unit carried by determinate progress events."""

    BYTES = "bytes"
    FILES = "files"
    PARTS = "parts"
    STEPS = "steps"
    VIEWS = "views"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One progress update from a long-running library operation."""

    stage: ProgressStage
    message: str
    current: int | None = None
    total: int | None = None
    path: Path | None = None
    unit: ProgressUnit | None = None

    @property
    def determinate(self) -> bool:
        """Whether this event has a current value, total, and explicit unit."""
        return (
            self.current is not None
            and self.total is not None
            and self.unit is not None
        )


ProgressCallback = Callable[[ProgressEvent], None]


def emit_progress(
    on_progress: ProgressCallback | None,
    event: ProgressEvent,
) -> None:
    """Send ``event`` to ``on_progress`` when a callback is configured."""
    if on_progress is not None:
        on_progress(event)


__all__ = [
    "ProgressCallback",
    "ProgressEvent",
    "ProgressStage",
    "ProgressUnit",
    "emit_progress",
]
