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
    from ldraw.model import ModelOccurrence
    from ldraw.parts import Parts

BOM_FIELDS: tuple[str, ...] = (
    "part",
    "description",
    "colour_code",
    "colour_name",
    "quantity",
)


class _ModelLike(Protocol):
    """Object that can yield colour-resolved leaf occurrences."""

    def iter_occurrences(  # pragma: no cover
        self,
        *,
        expand_submodels: bool = True,
        include_steps: bool = True,
    ) -> Iterator[ModelOccurrence]:
        """Yield placed leaf occurrences, expanding submodel references."""
        raise NotImplementedError


def _model_occurrences(model: _ModelLike) -> Iterator[ModelOccurrence]:
    """Yield BOM occurrences, tolerating cycles for concrete Models."""
    from ldraw.model import Model, _iter_occurrences_skip_cycles  # noqa: PLC0415

    if isinstance(model, Model):
        return _iter_occurrences_skip_cycles(model, include_steps=False)
    return model.iter_occurrences(include_steps=False)


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
    return parts.description_for(part)


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
    model: _ModelLike | None = None,
    *,
    parts: Parts | None = None,
    occurrences: Iterable[ModelOccurrence] | None = None,
) -> list[BomRow]:
    """Count leaf pieces by part and colour, expanding submodel references.

    A submodel placed twice contributes its pieces twice. Submodel
    reference pieces themselves are expanded, never counted. Colour 16
    (the main colour) inside a submodel is resolved to the colour the
    submodel was placed with. Descriptions and colour names are resolved
    when a parts catalog is given.

    References only resolve against the given model's own submodel table.
    To count one submodel of a larger model, pass
    ``root.submodel_view(name)`` rather than a model taken straight from
    ``Model.submodels`` — the latter treats nested submodel references as
    leaf parts.

    Part codes are counted case-insensitively; each row shows the code as
    first written in the model.
    """
    if (model is None) == (occurrences is None):
        message = "provide exactly one of model or occurrences"
        raise ValueError(message)
    source: Iterable[ModelOccurrence] | None = (
        _model_occurrences(model) if model is not None else occurrences
    )
    if source is None:  # pragma: no cover - guarded above
        raise AssertionError
    counts: Counter[tuple[str, Colour]] = Counter()
    display: dict[str, str] = {}
    for occurrence in source:
        part_key = occurrence.part_code.casefold()
        display.setdefault(part_key, occurrence.part_code)
        counts[(part_key, occurrence.colour)] += 1
    rows = [
        BomRow(
            part=display[part_key],
            description=_description(part_key, parts),
            colour_code=colour.code,
            colour_name=_colour_name(colour, parts),
            quantity=quantity,
        )
        for (part_key, colour), quantity in counts.items()
    ]
    rows.sort(
        key=lambda row: (
            row.part.casefold(),
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
