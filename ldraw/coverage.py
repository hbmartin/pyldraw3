"""Coverage vocabulary shared by qualified analysis reports."""

from enum import StrEnum


class Coverage(StrEnum):
    """Whether the requested evidence was available and fully processed."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
