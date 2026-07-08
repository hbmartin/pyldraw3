"""Bill-of-materials extraction from LDraw models."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ldraw.colour import Colour
    from ldraw.parts import Parts
    from ldraw.pieces import Piece

BOM_FIELDS: tuple[str, ...] = (
    "part",
    "description",
    "colour_code",
    "colour_name",
    "quantity",
)


class _ModelLike(Protocol):
    """Object that can yield fully expanded leaf pieces."""

    def iter_pieces(self) -> Iterator[Piece]:
        """Yield leaf pieces, expanding submodel references."""
        ...


@dataclass(frozen=True, slots=True)
class BomRow:
    """One line of a bill of materials."""

    part: str
    description: str | None
    colour_code: int | None
    colour_name: str | None
    quantity: int

    def to_dict(self) -> dict[str, str | int | None]:
        """Return the row as a plain dict keyed by ``BOM_FIELDS``."""
        return asdict(self)


def _description(part: str, parts: Parts | None) -> str | None:
    if parts is None:
        return None
    return parts.by_code.get(part) or parts.by_code.get(part.lower())


def _colour_name(colour: Colour, parts: Parts | None) -> str | None:
    if colour.code is None:
        return colour.rgb
    if colour.name is not None:
        return colour.name
    if parts is None:
        return None
    catalogued = parts.colours_by_code.get(colour.code)
    return catalogued.name if catalogued is not None else None


def bill_of_materials(
    model: _ModelLike,
    *,
    parts: Parts | None = None,
) -> list[BomRow]:
    """Count leaf pieces by part and colour, expanding submodel references.

    A submodel placed twice contributes its pieces twice. Submodel
    reference pieces themselves are expanded, never counted. Descriptions
    and colour names are resolved when a parts catalog is given.
    """
    counts = Counter((piece.part, piece.colour) for piece in model.iter_pieces())
    rows = [
        BomRow(
            part=part,
            description=_description(part, parts),
            colour_code=colour.code,
            colour_name=_colour_name(colour, parts),
            quantity=quantity,
        )
        for (part, colour), quantity in counts.items()
    ]
    rows.sort(
        key=lambda row: (
            row.part,
            row.colour_code is None,
            row.colour_code or 0,
            row.colour_name or "",
        ),
    )
    return rows


def rows_to_csv(rows: Iterable[BomRow]) -> str:
    """Serialize rows to CSV text with a header line."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=BOM_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: "" if value is None else value
                for key, value in row.to_dict().items()
            },
        )
    return buffer.getvalue()


def rows_to_json(rows: Iterable[BomRow]) -> str:
    """Serialize rows to a JSON array of objects."""
    return json.dumps([row.to_dict() for row in rows], indent=2)
