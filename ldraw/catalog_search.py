"""Literal ranked catalog search with a qualified in-memory fallback."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ldraw.diagnostics import Diagnostic, Severity
from ldraw.part_metadata import PartFileKind, PartStatus

if TYPE_CHECKING:
    from ldraw.parts import CatalogEntry, PartCategory, Parts


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    """A catalog page; total describes the full filtered result."""

    items: tuple[CatalogEntry, ...]
    total: int
    limit: int | None
    offset: int
    diagnostics: tuple[Diagnostic, ...] = ()


def fts5_available() -> bool:
    """Probe this SQLite runtime without creating persistent files."""
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
    except sqlite3.Error:
        return False
    return True


def _fts_codes(parts: Parts, query: str) -> list[str]:
    if parts.search_index is None:
        message = "persistent catalog unavailable"
        raise sqlite3.OperationalError(message)
    tokens = query.split()
    literal = " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
    )
    with sqlite3.connect(
        f"{parts.search_index.resolve().as_uri()}?mode=ro", uri=True
    ) as connection:
        text_matches = (
            connection.execute(
                "SELECT code, bm25(parts_fts) FROM parts_fts WHERE parts_fts MATCH ?",
                (literal,),
            ).fetchall()
            if literal
            else []
        )
        codes = connection.execute(
            "SELECT code FROM parts ORDER BY code COLLATE NOCASE"
        ).fetchall()
    text_ranks = dict(text_matches)
    normalized = query.strip().casefold()
    matches = [
        code
        for (code,) in codes
        if not normalized
        or code.casefold().startswith(normalized)
        or code in text_ranks
    ]
    return sorted(
        matches,
        key=lambda code: (
            0
            if code.casefold() == normalized
            else 1
            if code.casefold().startswith(normalized)
            else 2,
            0.0
            if code.casefold().startswith(normalized)
            else text_ranks.get(code, 0.0),
            code.casefold(),
            code,
        ),
    )


def search_parts(  # noqa: PLR0913 - explicit search and presentation options
    parts: Parts,
    *,
    query: str,
    category: PartCategory | str | None,
    physical_only: bool,
    limit: int | None,
    offset: int,
) -> CatalogSearchResult:
    """Use BM25 when available and preserve the ranked matcher as fallback."""
    if offset < 0 or (limit is not None and limit < 0):
        message = "limit and offset must be non-negative"
        raise ValueError(message)
    diagnostics = list(parts.diagnostics)
    catalog = parts.catalog
    try:
        entries = tuple(catalog.by_code[code] for code in _fts_codes(parts, query))
    except (OSError, sqlite3.Error, KeyError) as error:
        entries = catalog.search(query)
        diagnostics.append(
            Diagnostic(
                code="catalog.search_fallback",
                severity=Severity.WARNING,
                message=f"Using ranked in-memory search: {error}",
            )
        )
    entries = tuple(
        entry
        for entry in entries
        if (category is None or entry.category == category)
        and (
            not physical_only
            or (
                entry.metadata is not None
                and entry.metadata.file_kind == PartFileKind.PART
                and entry.metadata.status not in {PartStatus.ALIAS, PartStatus.MOVED}
            )
        )
    )
    end = None if limit is None else offset + limit
    return CatalogSearchResult(
        items=entries[offset:end],
        total=len(entries),
        limit=limit,
        offset=offset,
        diagnostics=tuple(diagnostics),
    )
