"""Listing-only part descriptions, shared with the full library loader."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Self

DOT_DAT = re.compile(r"\.DAT", flags=re.IGNORECASE)
logger = logging.getLogger("ldraw.parts")


class PartDescriptionSource(Protocol):
    """Minimum listing evidence needed to classify an inventory reference."""

    def description_for(self, code: str) -> str | None:
        """Return a description without resolving geometry."""
        ...


def iter_parts_listing(path: Path) -> Iterator[tuple[str, str]]:
    """Read codes and unchanged descriptions, skipping malformed listing lines."""
    with path.open(mode="r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            pieces = DOT_DAT.split(line, maxsplit=1)
            if len(pieces) != 2:
                logger.warning(
                    "skipping malformed line %d in %s: %r",
                    line_number,
                    path,
                    line.strip(),
                )
                continue
            yield pieces[0], pieces[1].strip()


@dataclass(frozen=True, slots=True)
class PartsListing:
    """Descriptions loaded exclusively from parts.lst, with no library scans."""

    by_code: dict[str, str]
    normalized: dict[str, str]

    @classmethod
    def read(cls, path: Path) -> Self:
        """Load a listing and its case-insensitive reference index."""
        by_code = dict(iter_parts_listing(path))
        return cls(
            by_code=by_code,
            normalized={
                code.replace("\\", "/").casefold(): description
                for code, description in by_code.items()
            },
        )

    def description_for(self, code: str) -> str | None:
        """Prefer an exact code before normalized reference fallback."""
        if (description := self.by_code.get(code)) is not None:
            return description
        return self.normalized.get(code.replace("\\", "/").casefold())
