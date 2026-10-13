"""Bill-of-materials extraction from LDraw models."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ldraw.colour import Colour
from ldraw.errors import PartError
from ldraw.part import colour_from_str
from ldraw.utils import normalize_ref, split_reference

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from ldraw._parts_listing import PartDescriptionSource
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


@dataclass(frozen=True, slots=True)
class _BomLeaf:
    """An expanded leaf with its BOM identity and classification prepared once."""

    reference: str
    part: str
    colour: Colour
    requires_listing: bool
    unresolved_submodel: bool


def _bom_leaf(occurrence: ModelOccurrence) -> _BomLeaf:
    stem, suffix = split_reference(occurrence.reference)
    suffix = suffix.casefold()
    return _BomLeaf(
        reference=occurrence.reference,
        part=(stem if suffix == ".dat" else occurrence.reference).replace("\\", "/"),
        colour=occurrence.colour,
        requires_listing=suffix not in {".dat", ".ldr", ".mpd"},
        unresolved_submodel=suffix in {".ldr", ".mpd"},
    )


def _prepare_inventory_occurrences(
    occurrences: Iterable[ModelOccurrence],
) -> tuple[_BomLeaf, ...]:
    return tuple(_bom_leaf(occurrence) for occurrence in occurrences)


def _bom_rows(leaves: Iterable[_BomLeaf], *, parts: Parts | None) -> list[BomRow]:
    counts: Counter[tuple[str, Colour]] = Counter()
    display: dict[str, str] = {}
    for leaf in leaves:
        part_key = leaf.part.casefold()
        display.setdefault(part_key, leaf.part)
        counts[(part_key, leaf.colour)] += 1
    rows = [
        BomRow(
            part=display[part_key],
            description=_description(display[part_key], parts),
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
    first written in the model, removing only a terminal .dat suffix.
    """
    if (model is None) == (occurrences is None):
        message = "provide exactly one of model or occurrences"
        raise ValueError(message)
    source: Iterable[ModelOccurrence] | None = (
        _model_occurrences(model) if model is not None else occurrences
    )
    if source is None:  # pragma: no cover - guarded above
        raise AssertionError
    return _bom_rows((_bom_leaf(occurrence) for occurrence in source), parts=parts)


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


@dataclass(frozen=True, slots=True)
class InventoryDifference:
    """A mismatched part/colour count; expected is the inventory quantity."""

    part: str
    colour: str
    expected: int
    actual: int

    @property
    def missing(self) -> int:
        """Number of inventory pieces missing from the model."""
        return max(0, self.expected - self.actual)

    @property
    def extra(self) -> int:
        """Number of model pieces absent from the inventory."""
        return max(0, self.actual - self.expected)

    def to_dict(self) -> dict[str, str | int]:
        """Return counts suitable for JSON and CSV output."""
        return {**asdict(self), "missing": self.missing, "extra": self.extra}


@dataclass(frozen=True, slots=True)
class InventoryComparison:
    """Deterministically ordered inventory differences."""

    differences: tuple[InventoryDifference, ...]

    @property
    def matched(self) -> bool:
        """Whether the model and inventory have identical counts."""
        return not self.differences

    def to_dict(self) -> dict[str, object]:
        """Return the comparison as a JSON-ready object."""
        return {
            "matched": self.matched,
            "differences": [item.to_dict() for item in self.differences],
        }


def _inventory_colour(token: str) -> Colour:
    token = token.strip()
    if token.startswith("#"):
        return Colour(rgb=token)
    value = colour_from_str(token)
    if isinstance(value, int):
        if value < 0:
            message = f"negative colour code {value}"
            raise ValueError(message)
        return Colour(code=value)
    return value


def _inventory_row(
    row: dict[str, str | None],
    *,
    columns: Mapping[str, str],
    colour_map: Mapping[str, str | int] | None,
) -> BomRow:
    part = (row.get(columns["part"]) or "").strip()
    if not part:
        message = "empty part identifier"
        raise ValueError(message)
    quantity = int(row.get(columns["quantity"]) or "")
    if quantity < 0:
        message = "quantity must be a nonnegative integer"
        raise ValueError(message)
    colour_token = (row.get(columns["colour"]) or "").strip()
    if not colour_token and columns["colour"] == "colour_code":
        colour_token = (row.get("colour_name") or "").strip()
    if colour_map is not None:
        if colour_token not in colour_map:
            message = f"unmapped inventory colour {colour_token!r}"
            raise ValueError(message)
        colour_token = str(colour_map[colour_token])
    colour = _inventory_colour(colour_token)
    return BomRow(
        part=part,
        description=None,
        colour_code=colour.code,
        colour_name=colour.rgb,
        quantity=quantity,
    )


def read_inventory(
    path: str | Path,
    *,
    columns: Mapping[str, str] | None = None,
    colour_map: Mapping[str, str | int] | None = None,
) -> list[BomRow]:
    """Read native BOM CSV or explicitly mapped inventory columns/colours.

    ``columns`` maps ``part``, ``colour``, and ``quantity`` to CSV headers.
    Without a colour map, colour values are LDraw codes or direct RGB.
    When a map is supplied, every inventory colour must have an entry.
    Empty native ``colour_code`` cells fall back to ``colour_name`` for RGB.
    Malformed rows raise ``ValueError`` with their CSV line number.
    """
    names = {"part": "part", "colour": "colour_code", "quantity": "quantity"}
    if columns is not None:
        if set(columns) - names.keys():
            message = "column mapping supports only part, colour, and quantity"
            raise ValueError(message)
        names.update(columns)
    if any(not isinstance(value, str) or not value for value in names.values()):
        message = "column names must be nonempty strings"
        raise ValueError(message)
    rows: list[BomRow] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not set(names.values()) <= set(
            reader.fieldnames
        ):
            message = (
                f"inventory is missing required columns: {', '.join(names.values())}"
            )
            raise ValueError(message)
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            message = "inventory contains duplicate column headers"
            raise ValueError(message)
        for row in reader:
            try:
                if None in row:
                    message = "row has more cells than the header"
                    raise ValueError(message)  # noqa: TRY301 - attach CSV line context
                parsed = _inventory_row(row, columns=names, colour_map=colour_map)
            except (ValueError, TypeError, PartError) as exc:
                message = f"inventory line {reader.line_num}: {exc}"
                raise ValueError(message) from exc
            if parsed.quantity:
                rows.append(parsed)
    return rows


def _canonical_part(code: str, aliases: Mapping[str, str]) -> str:
    key = normalize_ref(code).removesuffix(".dat")
    seen: set[str] = set()
    while key in aliases and aliases[key] != key:
        if key in seen:
            message = f"cyclic part alias involving {key!r}"
            raise ValueError(message)
        seen.add(key)
        key = aliases[key]
    return key


def _inventory_counts(
    rows: Iterable[BomRow], *, aliases: Mapping[str, str]
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if not isinstance(row.quantity, int) or row.quantity < 0:
            message = "inventory quantities must be nonnegative integers"
            raise ValueError(message)
        colour = (
            str(row.colour_code)
            if row.colour_code is not None
            else _inventory_colour(row.colour_name or "").rgb
        )
        if colour is None:  # pragma: no cover - direct colours always have RGB
            raise AssertionError
        counts[(_canonical_part(row.part, aliases), colour)] += row.quantity
    return counts


def _validate_inventory_reference(
    occurrence: _BomLeaf, *, parts: PartDescriptionSource | None
) -> None:
    """Require listing evidence for leaves without an explicit .dat suffix."""
    if occurrence.unresolved_submodel:
        message = (
            f"model contains unresolved submodel reference {occurrence.reference!r}"
        )
        raise ValueError(message)
    if occurrence.requires_listing and (
        parts is None or parts.description_for(occurrence.reference) is None
    ):
        message = (
            f"unresolved or ambiguous reference without an explicit .dat suffix "
            f"{occurrence.reference!r}; "
            "supply a parts catalog or use .dat for part references"
        )
        raise ValueError(message)


def compare_inventory(
    model: _ModelLike,
    expected: Iterable[BomRow],
    *,
    part_aliases: Mapping[str, str] | None = None,
    parts: Parts | None = None,
) -> InventoryComparison:
    """Compare expanded model counts with inventory rows, aggregating duplicates.

    Part aliases apply to both sides; colour mapping belongs to CSV input.
    Cyclic or unresolved submodel references fail instead of returning a
    potentially matching partial inventory. Leaf references without an
    explicit ``.dat`` suffix require listing evidence in ``parts`` before
    aliases are applied;
    explicit ``.dat`` part references do not require a catalog.
    """
    return _compare_inventory_occurrences(
        occurrences=_prepare_inventory_occurrences(
            model.iter_occurrences(include_steps=False)
        ),
        expected=expected,
        part_aliases=part_aliases,
        parts=parts,
    )


def _compare_inventory_occurrences(
    occurrences: tuple[_BomLeaf, ...],
    expected: Iterable[BomRow],
    *,
    part_aliases: Mapping[str, str] | None = None,
    parts: PartDescriptionSource | None = None,
) -> InventoryComparison:
    """Compare already-expanded leaves without traversing the model again."""
    aliases = {
        normalize_ref(key).removesuffix(".dat"): normalize_ref(value).removesuffix(
            ".dat"
        )
        for key, value in (part_aliases or {}).items()
    }
    for key in aliases:
        _canonical_part(key, aliases)
    for occurrence in occurrences:
        _validate_inventory_reference(occurrence, parts=parts)
    actual = _inventory_counts(
        _bom_rows(occurrences, parts=None),
        aliases=aliases,
    )
    inventory = _inventory_counts(expected, aliases=aliases)
    differences = tuple(
        InventoryDifference(
            part=part, colour=colour, expected=inventory[key], actual=actual[key]
        )
        for key in sorted(actual.keys() | inventory.keys())
        if actual[key] != inventory[key]
        for part, colour in (key,)
    )
    return InventoryComparison(differences=differences)


def comparison_to_csv(comparison: InventoryComparison) -> str:
    """Serialize comparison differences as CSV, including an empty header on match."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=("part", "colour", "expected", "actual", "missing", "extra"),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(item.to_dict() for item in comparison.differences)
    return buffer.getvalue()
