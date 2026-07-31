"""Structured metadata parsed from official and unofficial part headers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ldraw.geometry import Matrix, Vector
from ldraw.pieces import Piece

if TYPE_CHECKING:
    from pathlib import Path

_AUTHOR_USER_RE = re.compile(r"^(?P<author>.*?)(?:\s*\[(?P<user>[^]]+)\])?$")
_HISTORY_RE = re.compile(
    r"^(?P<date>\S+)\s+(?:\[(?P<user>[^]]+)\]|\{(?P<author>[^}]+)\})\s*(?P<text>.*)$"
)
_RELEASE_RE = re.compile(r"^\d{4}-\d{2}$")


class PartFileKind(StrEnum):
    """Kind declared by the ``!LDRAW_ORG`` header."""

    PART = "part"
    SUBPART = "subpart"
    PRIMITIVE = "primitive"
    PRIMITIVE_8 = "8_primitive"
    PRIMITIVE_48 = "48_primitive"
    SHORTCUT = "shortcut"
    UNKNOWN = "unknown"


class LibraryOrigin(StrEnum):
    """Whether a header declares official or unofficial library origin."""

    OFFICIAL = "official"
    UNOFFICIAL = "unofficial"
    UNKNOWN = "unknown"


class PartStatus(StrEnum):
    """Relationship/lifecycle status derived from header evidence."""

    CURRENT = "current"
    ALIAS = "alias"
    MOVED = "moved"
    OBSOLETE = "obsolete"


class BfcCertification(StrEnum):
    """Back-face-culling certification declared in the header."""

    CCW = "ccw"
    CW = "cw"
    NOCERTIFY = "nocertify"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PartHistoryEntry:
    """One parsed ``!HISTORY`` line."""

    date: str
    contributor: str | None
    text: str
    raw: str


@dataclass(frozen=True, slots=True)
class PreviewTransform:
    """Official ``!PREVIEW`` colour and placement transform."""

    colour_code: int
    position: Vector
    matrix: Matrix


@dataclass(frozen=True, slots=True)
class PartMetadata:
    """Metadata and relationships represented by an LDraw part header."""

    description: str
    name: str | None = None
    author: str | None = None
    author_username: str | None = None
    file_kind: PartFileKind = PartFileKind.UNKNOWN
    origin: LibraryOrigin = LibraryOrigin.UNKNOWN
    qualifiers: tuple[str, ...] = ()
    release: str | None = None
    license: str | None = None
    bfc: BfcCertification = BfcCertification.UNKNOWN
    history: tuple[PartHistoryEntry, ...] = ()
    category: str | None = None
    keywords: tuple[str, ...] = ()
    status: PartStatus = PartStatus.CURRENT
    replacement: str | None = None
    preview: PreviewTransform | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation for the persistent catalog."""
        preview = None
        if self.preview is not None:
            preview = {
                "colour_code": self.preview.colour_code,
                "position": [
                    self.preview.position.x,
                    self.preview.position.y,
                    self.preview.position.z,
                ],
                "matrix": [list(row) for row in self.preview.matrix.rows],
            }
        return {
            "description": self.description,
            "name": self.name,
            "author": self.author,
            "author_username": self.author_username,
            "file_kind": self.file_kind.value,
            "origin": self.origin.value,
            "qualifiers": list(self.qualifiers),
            "release": self.release,
            "license": self.license,
            "bfc": self.bfc.value,
            "history": [
                {
                    "date": entry.date,
                    "contributor": entry.contributor,
                    "text": entry.text,
                    "raw": entry.raw,
                }
                for entry in self.history
            ],
            "category": self.category,
            "keywords": list(self.keywords),
            "status": self.status.value,
            "replacement": self.replacement,
            "preview": preview,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PartMetadata:
        """Restore metadata previously returned by ``to_dict``."""
        preview_value = value.get("preview")
        preview = None
        if isinstance(preview_value, dict):
            preview = PreviewTransform(
                colour_code=int(preview_value["colour_code"]),
                position=Vector(*preview_value["position"]),
                matrix=Matrix(preview_value["matrix"]),
            )
        return cls(
            description=str(value.get("description", "")),
            name=value.get("name"),
            author=value.get("author"),
            author_username=value.get("author_username"),
            file_kind=PartFileKind(value.get("file_kind", PartFileKind.UNKNOWN)),
            origin=LibraryOrigin(value.get("origin", LibraryOrigin.UNKNOWN)),
            qualifiers=tuple(value.get("qualifiers", ())),
            release=value.get("release"),
            license=value.get("license"),
            bfc=BfcCertification(value.get("bfc", BfcCertification.UNKNOWN)),
            history=tuple(
                PartHistoryEntry(
                    date=str(entry.get("date", "")),
                    contributor=entry.get("contributor"),
                    text=str(entry.get("text", "")),
                    raw=str(entry.get("raw", "")),
                )
                for entry in value.get("history", ())
            ),
            category=value.get("category"),
            keywords=tuple(value.get("keywords", ())),
            status=PartStatus(value.get("status", PartStatus.CURRENT)),
            replacement=value.get("replacement"),
            preview=preview,
        )


@dataclass(slots=True)
class _MetadataFields:
    name: str | None = None
    author: str | None = None
    author_username: str | None = None
    file_kind: PartFileKind = PartFileKind.UNKNOWN
    origin: LibraryOrigin = LibraryOrigin.UNKNOWN
    qualifiers: tuple[str, ...] = ()
    release: str | None = None
    license: str | None = None
    bfc: BfcCertification = BfcCertification.UNKNOWN
    history: list[PartHistoryEntry] = field(default_factory=list)
    category: str | None = None
    keywords: list[str] = field(default_factory=list)
    preview: PreviewTransform | None = None
    first_reference: str | None = None


def parse_part_metadata(path: Path) -> PartMetadata:
    """Parse one part header and relationship target from disk."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines:
        from ldraw.errors import EmptyPartFileError  # noqa: PLC0415

        raise EmptyPartFileError(str(path))
    description = " ".join(lines[0].split()[1:])
    fields = _collect_metadata_fields(lines[1:])
    status, replacement = _part_status(
        description,
        qualifiers=fields.qualifiers,
        first_reference=fields.first_reference,
    )
    return PartMetadata(
        description=description,
        name=fields.name,
        author=fields.author,
        author_username=fields.author_username,
        file_kind=fields.file_kind,
        origin=fields.origin,
        qualifiers=fields.qualifiers,
        release=fields.release,
        license=fields.license,
        bfc=fields.bfc,
        history=tuple(fields.history),
        category=fields.category,
        keywords=tuple(fields.keywords),
        status=status,
        replacement=replacement,
        preview=fields.preview,
    )


def _collect_metadata_fields(lines: list[str]) -> _MetadataFields:
    fields = _MetadataFields()
    header_open = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("0 "):
            header_open = False
        if header_open and _apply_header_command(stripped, fields):
            continue
        if fields.first_reference is None and stripped.startswith("1 "):
            fields.first_reference = _reference_from_line(stripped)
    return fields


def _apply_header_command(  # noqa: C901 - flat dispatch over header commands
    stripped: str,
    fields: _MetadataFields,
) -> bool:
    if stripped.startswith("0 Name:"):
        fields.name = stripped.removeprefix("0 Name:").strip() or None
    elif stripped.startswith("0 Author:"):
        raw_author = stripped.removeprefix("0 Author:").strip()
        if match := _AUTHOR_USER_RE.match(raw_author):
            fields.author = match.group("author").strip() or None
            fields.author_username = match.group("user")
    elif stripped.startswith("0 !LDRAW_ORG "):
        declaration = stripped.removeprefix("0 !LDRAW_ORG ").strip()
        (
            fields.file_kind,
            fields.origin,
            fields.qualifiers,
            fields.release,
        ) = _parse_ldraw_org(declaration)
    elif stripped.startswith("0 !LICENSE "):
        fields.license = stripped.removeprefix("0 !LICENSE ").strip() or None
    elif stripped.startswith("0 BFC "):
        fields.bfc = _parse_bfc(stripped.removeprefix("0 BFC "))
    elif stripped.startswith("0 !CATEGORY "):
        fields.category = stripped.removeprefix("0 !CATEGORY ").strip() or None
    elif stripped.startswith("0 !KEYWORDS "):
        _extend_keywords(
            fields.keywords,
            stripped.removeprefix("0 !KEYWORDS "),
        )
    elif stripped.startswith("0 !HISTORY "):
        fields.history.append(
            _parse_history(stripped.removeprefix("0 !HISTORY ").strip()),
        )
    elif stripped.startswith("0 !PREVIEW "):
        fields.preview = _parse_preview(stripped.removeprefix("0 !PREVIEW "))
    else:
        return False
    return True


def _extend_keywords(keywords: list[str], value: str) -> None:
    for keyword in value.split(","):
        if (candidate := keyword.strip()) and candidate not in keywords:
            keywords.append(candidate)


def _parse_preview(value: str) -> PreviewTransform | None:
    from ldraw.part import colour_from_str, parse_ldraw_line  # noqa: PLC0415

    tokens = value.split()
    if len(tokens) != 13:
        return None
    colour = colour_from_str(tokens[0])
    parsed = parse_ldraw_line(f"1 {' '.join(tokens)} preview.dat")
    if not isinstance(parsed, Piece) or not isinstance(colour, int):
        return None
    return PreviewTransform(
        colour_code=colour,
        position=parsed.position,
        matrix=parsed.matrix,
    )


def _reference_from_line(line: str) -> str | None:
    from ldraw.part import parse_ldraw_line  # noqa: PLC0415

    parsed = parse_ldraw_line(line)
    return parsed.reference if isinstance(parsed, Piece) else None


def _part_status(
    description: str,
    *,
    qualifiers: tuple[str, ...],
    first_reference: str | None,
) -> tuple[PartStatus, str | None]:
    lowered = description.casefold()
    if lowered.startswith("~moved to "):
        replacement = description[len("~Moved to ") :].strip() or first_reference
        return PartStatus.MOVED, replacement
    if "obsolete" in lowered and description.startswith("~"):
        return PartStatus.OBSOLETE, first_reference
    if any(qualifier.casefold() == "alias" for qualifier in qualifiers):
        return PartStatus.ALIAS, first_reference
    return PartStatus.CURRENT, None


def _parse_ldraw_org(
    declaration: str,
) -> tuple[PartFileKind, LibraryOrigin, tuple[str, ...], str | None]:
    tokens = declaration.split()
    if not tokens:
        return PartFileKind.UNKNOWN, LibraryOrigin.UNKNOWN, (), None
    raw_kind = tokens[0]
    origin = (
        LibraryOrigin.UNOFFICIAL
        if raw_kind.casefold().startswith("unofficial_")
        else LibraryOrigin.OFFICIAL
    )
    kind_name = raw_kind.casefold().removeprefix("unofficial_")
    try:
        file_kind = PartFileKind(kind_name)
    except ValueError:
        file_kind = PartFileKind.UNKNOWN
    qualifiers = tuple(
        qualifier.strip()
        for group in re.findall(r"\(([^)]+)\)", declaration)
        for qualifier in group.split(",")
        if qualifier.strip()
    )
    release = next(
        (token for token in reversed(tokens) if _RELEASE_RE.match(token)), None
    )
    return file_kind, origin, qualifiers, release


def _parse_bfc(value: str) -> BfcCertification:
    upper = value.upper().split()
    if "NOCERTIFY" in upper:
        return BfcCertification.NOCERTIFY
    if "CCW" in upper:
        return BfcCertification.CCW
    if "CW" in upper:
        return BfcCertification.CW
    return BfcCertification.UNKNOWN


def _parse_history(raw: str) -> PartHistoryEntry:
    if match := _HISTORY_RE.match(raw):
        return PartHistoryEntry(
            date=match.group("date"),
            contributor=match.group("user") or match.group("author"),
            text=match.group("text"),
            raw=raw,
        )
    return PartHistoryEntry(date="", contributor=None, text=raw, raw=raw)


__all__ = [
    "BfcCertification",
    "LibraryOrigin",
    "PartFileKind",
    "PartHistoryEntry",
    "PartMetadata",
    "PartStatus",
    "PreviewTransform",
]
