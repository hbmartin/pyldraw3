"""Part management classes for the Python ldraw package."""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ldraw.colour import Colour
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import PartError, PartNotFoundError
from ldraw.lines import MetaCommand
from ldraw.operations import CancellationToken, check_cancelled
from ldraw.part import Part
from ldraw.pieces import Piece
from ldraw.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    ProgressUnit,
    emit_progress,
)
from ldraw.utils import camel, clean

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.connection_metadata import (
        ConnectionMetadataReport,
        LDCadShadowLibrary,
        ShadowConnectionResult,
    )
    from ldraw.connection_studio import StudioConnectionLibrary
    from ldraw.connection_types import ConnectionFeature, PartCompatibility
    from ldraw.geometry import Matrix, Vector
    from ldraw.part_geometry_types import BoundingBox, PartGeometry, StudReference
    from ldraw.part_metadata import PartMetadata

DOT_DAT = re.compile(r"\.DAT", flags=re.IGNORECASE)
logger = logging.getLogger(__name__)


def _normalized_reference_code(code: str) -> str:
    return code.replace("\\", "/")


def _reference_key(code: str) -> str:
    return _normalized_reference_code(code).casefold()


def _normalized_index(mapping: dict[str, str]) -> dict[str, str]:
    """Index ``mapping`` by normalized reference key for O(1) casefold lookups."""
    return {_reference_key(code): value for code, value in mapping.items()}


class PartCategory(StrEnum):
    """Known LDraw part categories, mirroring the official LDraw.org list."""

    ANIMAL = "animal"
    ANTENNA = "antenna"
    ARCH = "arch"
    ARM = "arm"
    BAR = "bar"
    BASEPLATE = "baseplate"
    BELVILLE = "belville"
    BOAT = "boat"
    BRACKET = "bracket"
    BRICK = "brick"
    CANVAS = "canvas"
    CAR = "car"
    CLIKITS = "clikits"
    COCKPIT = "cockpit"
    CONE = "cone"
    CONSTRACTION = "constraction"
    CONSTRACTION_ACCESSORY = "constraction accessory"
    CONTAINER = "container"
    CONVEYOR = "conveyor"
    CRANE = "crane"
    CYLINDER = "cylinder"
    DISH = "dish"
    DOOR = "door"
    DUPLO = "duplo"
    ELECTRIC = "electric"
    EXHAUST = "exhaust"
    FENCE = "fence"
    FIGURE = "figure"
    FIGURE_ACCESSORY = "figure accessory"
    FLAG = "flag"
    FORKLIFT = "forklift"
    FREESTYLE = "freestyle"
    GARAGE = "garage"
    GLASS = "glass"
    GRAB = "grab"
    HINGE = "hinge"
    HOMEMAKER = "homemaker"
    HOSE = "hose"
    LADDER = "ladder"
    LEVER = "lever"
    MAGNET = "magnet"
    MINIFIG = "minifig"
    MINIFIG_ACCESSORY = "minifig accessory"
    MINIFIG_FOOTWEAR = "minifig footwear"
    MINIFIG_HEADWEAR = "minifig headwear"
    MINIFIG_HIPWEAR = "minifig hipwear"
    MINIFIG_NECKWEAR = "minifig neckwear"
    MONORAIL = "monorail"
    PANEL = "panel"
    PLANE = "plane"
    PLANT = "plant"
    PLATE = "plate"
    PLATFORM = "platform"
    PROPELLOR = "propellor"
    RACK = "rack"
    ROADSIGN = "roadsign"
    ROCK = "rock"
    SCALA = "scala"
    SCREW = "screw"
    SHEET_CARDBOARD = "sheet cardboard"
    SHEET_FABRIC = "sheet fabric"
    SHEET_PLASTIC = "sheet plastic"
    SLOPE = "slope"
    SPHERE = "sphere"
    STAIRCASE = "staircase"
    STICKER = "sticker"
    STRING = "string"
    SUPPORT = "support"
    TAIL = "tail"
    TAP = "tap"
    TECHNIC = "technic"
    TILE = "tile"
    TIPPER = "tipper"
    TRACTOR = "tractor"
    TRAILER = "trailer"
    TRAIN = "train"
    TURNTABLE = "turntable"
    TYRE = "tyre"
    VEHICLE = "vehicle"
    WEDGE = "wedge"
    WHEEL = "wheel"
    WINCH = "winch"
    WINDOW = "window"
    WINDSCREEN = "windscreen"
    WING = "wing"
    ZNAP = "znap"
    OTHER = "other"

    @classmethod
    def from_label(cls, label: str | None) -> PartCategory | None:
        """Return the category matching an LDraw label."""
        if label is None:
            return None
        normalized = label.strip().lower()
        return _CATEGORY_BY_VALUE.get(normalized)

    @property
    def module_name(self) -> str:
        """Return the generated module name for this category.

        These names are a frozen public contract: renaming one would break
        existing ``ldraw.library.parts.*`` imports.
        """
        return _MODULE_NAMES[self]


_CATEGORY_BY_VALUE = {category.value: category for category in PartCategory}

_MODULE_NAMES: dict[PartCategory, str] = {
    PartCategory.ANIMAL: "animals",
    PartCategory.ANTENNA: "antennas",
    PartCategory.ARCH: "arches",
    PartCategory.ARM: "arms",
    PartCategory.BAR: "bars",
    PartCategory.BASEPLATE: "baseplates",
    PartCategory.BELVILLE: "belvilles",
    PartCategory.BOAT: "boats",
    PartCategory.BRACKET: "brackets",
    PartCategory.BRICK: "bricks",
    PartCategory.CANVAS: "canvases",
    PartCategory.CAR: "car",
    PartCategory.CLIKITS: "clikits",
    PartCategory.COCKPIT: "cockpits",
    PartCategory.CONE: "cones",
    PartCategory.CONSTRACTION: "constractions",
    PartCategory.CONSTRACTION_ACCESSORY: "constraction_accessory",
    PartCategory.CONTAINER: "containers",
    PartCategory.CONVEYOR: "conveyors",
    PartCategory.CRANE: "cranes",
    PartCategory.CYLINDER: "cylinders",
    PartCategory.DISH: "dishes",
    PartCategory.DOOR: "doors",
    PartCategory.DUPLO: "duplo",
    PartCategory.ELECTRIC: "electrics",
    PartCategory.EXHAUST: "exhausts",
    PartCategory.FENCE: "fences",
    PartCategory.FIGURE: "figures",
    PartCategory.FIGURE_ACCESSORY: "figure_accessory",
    PartCategory.FLAG: "flags",
    PartCategory.FORKLIFT: "forklifts",
    PartCategory.FREESTYLE: "freestyles",
    PartCategory.GARAGE: "garages",
    PartCategory.GLASS: "glass",
    PartCategory.GRAB: "grabs",
    PartCategory.HINGE: "hinges",
    PartCategory.HOMEMAKER: "homemakers",
    PartCategory.HOSE: "hoses",
    PartCategory.LADDER: "ladders",
    PartCategory.LEVER: "levers",
    PartCategory.MAGNET: "magnets",
    PartCategory.MINIFIG: "minifigs",
    PartCategory.MINIFIG_ACCESSORY: "minifig_accessory",
    PartCategory.MINIFIG_FOOTWEAR: "minifig_footwear",
    PartCategory.MINIFIG_HEADWEAR: "minifig_headwear",
    PartCategory.MINIFIG_HIPWEAR: "minifig_hipwear",
    PartCategory.MINIFIG_NECKWEAR: "minifig_neckwear",
    PartCategory.MONORAIL: "monorail",
    PartCategory.PANEL: "panels",
    PartCategory.PLANE: "planes",
    PartCategory.PLANT: "plants",
    PartCategory.PLATE: "plates",
    PartCategory.PLATFORM: "platforms",
    PartCategory.PROPELLOR: "propellors",
    PartCategory.RACK: "racks",
    PartCategory.ROADSIGN: "roadsigns",
    PartCategory.ROCK: "rocks",
    PartCategory.SCALA: "scala",
    PartCategory.SCREW: "screws",
    PartCategory.SHEET_CARDBOARD: "sheet_cardboard",
    PartCategory.SHEET_FABRIC: "sheet_fabric",
    PartCategory.SHEET_PLASTIC: "sheet_plastic",
    PartCategory.SLOPE: "slopes",
    PartCategory.SPHERE: "spheres",
    PartCategory.STAIRCASE: "staircases",
    PartCategory.STICKER: "stickers",
    PartCategory.STRING: "string",
    PartCategory.SUPPORT: "supports",
    PartCategory.TAIL: "tails",
    PartCategory.TAP: "taps",
    PartCategory.TECHNIC: "technic",
    PartCategory.TILE: "tiles",
    PartCategory.TIPPER: "tippers",
    PartCategory.TRACTOR: "tractors",
    PartCategory.TRAILER: "trailers",
    PartCategory.TRAIN: "train",
    PartCategory.TURNTABLE: "turntables",
    PartCategory.TYRE: "tyres",
    PartCategory.VEHICLE: "vehicles",
    PartCategory.WEDGE: "wedges",
    PartCategory.WHEEL: "wheels",
    PartCategory.WINCH: "winches",
    PartCategory.WINDOW: "windows",
    PartCategory.WINDSCREEN: "windscreens",
    PartCategory.WING: "wings",
    PartCategory.ZNAP: "znap",
    PartCategory.OTHER: "others",
}


class MinifigSection(StrEnum):
    """Known minifigure catalog sections."""

    HATS = "hats"
    HEADS = "heads"
    TORSOS = "torsos"
    HIPS = "hips"
    LEGS = "legs"
    ARMS = "arms"
    HANDS = "hands"
    ACCESSORIES = "accessories"

    @property
    def marker(self) -> str:
        """Return the description marker used to infer this section."""
        return _MINIFIG_MARKERS[self]


_MINIFIG_MARKERS: dict[MinifigSection, str] = {
    MinifigSection.TORSOS: "Torso",
    MinifigSection.HIPS: "Hip",
    MinifigSection.ARMS: "Arm",
    MinifigSection.HEADS: "Head",
    MinifigSection.ACCESSORIES: "Accessory",
    MinifigSection.HANDS: "Hand",
    MinifigSection.HATS: "Hat",
    MinifigSection.LEGS: "Leg",
}

_MINIFIG_PREFIX = "Minifig "


class PartReferenceKind(StrEnum):
    """Kind of type-1 reference found inside a part file."""

    PART = "part"
    SUBPART = "subpart"
    PRIMITIVE = "primitive"
    UNKNOWN = "unknown"


class CatalogSearchField(StrEnum):
    """Catalog entry fields considered by ``PartsCatalog.search``."""

    CODE = "code"
    DESCRIPTION = "description"
    CATEGORY = "category"
    KEYWORD = "keyword"


ALL_CATALOG_SEARCH_FIELDS = tuple(CatalogSearchField)


def _split_minifig_description(
    description: str,
) -> tuple[str, MinifigSection] | None:
    """Return the stripped symbol name and section for a minifig description."""
    if not description.startswith(_MINIFIG_PREFIX):
        return None

    stripped = description[len(_MINIFIG_PREFIX) :]
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]

    for section in MinifigSection:
        searched = section.marker
        index_find = stripped.find(searched)
        if index_find != -1 and (
            index_find + len(searched) == len(stripped)
            or stripped[index_find + len(searched)] == " "
        ):
            return stripped, section
    return stripped, MinifigSection.ACCESSORIES


def symbol_description(description: str) -> str:
    """Return the description that generated symbol names derive from.

    Minifig part descriptions drop their ``Minifig `` prefix so symbols in
    the ``minifig``/``minifig_*`` modules read ``Torso``, not
    ``MinifigTorso``; every other description passes through unchanged.
    """
    split = _split_minifig_description(description)
    return description if split is None else split[0]


def symbol_name_for_description(description: str) -> str:
    """Return the generated Python symbol for an LDraw description."""
    return clean(camel(symbol_description(description)))


def _catalog_entry_symbol_name(entry: CatalogEntry) -> str:
    return symbol_name_for_description(entry.description)


def _catalog_entry_module_path(entry: CatalogEntry) -> str | None:
    if entry.minifig_section is not None:
        return f"ldraw.library.parts.minifig.{entry.minifig_section.value}"
    if entry.category is PartCategory.OTHER:
        return None
    return f"ldraw.library.parts.{entry.category.module_name}"


def _catalog_entry_import_statement(entry: CatalogEntry) -> str | None:
    if (module := _catalog_entry_module_path(entry)) is None:
        return None
    return f"from {module} import {_catalog_entry_symbol_name(entry)}"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Typed catalog entry for one part or primitive."""

    code: str
    description: str
    category: PartCategory
    part: Part | None = None
    minifig_section: MinifigSection | None = None
    keywords: tuple[str, ...] = ()
    metadata: PartMetadata | None = None

    @property
    def symbol_name(self) -> str:
        """Generated Python symbol name for this entry."""
        return _catalog_entry_symbol_name(self)

    @property
    def module_path(self) -> str | None:
        """Generated module path for this entry, if it is importable."""
        return _catalog_entry_module_path(self)

    def import_statement(self) -> str | None:
        """Generated-library import statement for this entry, if available."""
        return _catalog_entry_import_statement(self)


@dataclass(frozen=True, slots=True)
class PartReference:
    """A type-1 subfile reference found inside a part file."""

    parent_code: str
    code: str
    reference: str
    kind: PartReferenceKind
    description: str | None
    colour: Colour
    position: Vector
    matrix: Matrix
    depth: int


@dataclass(frozen=True, slots=True)
class PartInspection:
    """Part lookup, metadata, references, geometry, and explicit failures."""

    code: str
    entry: CatalogEntry | None
    path: Path | None
    metadata: PartMetadata | None
    references: tuple[PartReference, ...]
    geometry: PartGeometry | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def complete(self) -> bool:
        """Return whether every requested inspection component succeeded."""
        return not any(
            diagnostic.severity is Severity.ERROR for diagnostic in self.diagnostics
        ) and (self.geometry is None or self.geometry.complete)


@dataclass(slots=True)
class PartsCatalog:
    """Typed collection of part catalog entries."""

    by_code: dict[str, CatalogEntry] = field(default_factory=dict)
    by_description: dict[str, CatalogEntry] = field(default_factory=dict)
    by_category: defaultdict[PartCategory, list[CatalogEntry]] = field(
        default_factory=lambda: defaultdict(list),
    )
    by_minifig_section: defaultdict[MinifigSection, list[CatalogEntry]] = field(
        default_factory=lambda: defaultdict(list),
    )
    _entries_by_category_cache: dict[PartCategory, tuple[CatalogEntry, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _search_haystacks: dict[tuple[str, tuple[CatalogSearchField, ...]], str] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def add(self, entry: CatalogEntry) -> None:
        """Add or replace an entry in every lookup index."""
        if (existing := self.by_code.get(entry.code)) is not None:
            if self.by_description.get(existing.description) is existing:
                del self.by_description[existing.description]
            self.by_category[existing.category].remove(existing)
            self._entries_by_category_cache.pop(existing.category, None)
            if existing.minifig_section is not None:
                self.by_minifig_section[existing.minifig_section].remove(existing)
        self.by_code[entry.code] = entry
        self._search_haystacks = {
            key: value
            for key, value in self._search_haystacks.items()
            if key[0] != entry.code
        }
        self.by_description[entry.description] = entry
        self.by_category[entry.category].append(entry)
        self._entries_by_category_cache.pop(entry.category, None)
        if entry.minifig_section is not None:
            self.by_minifig_section[entry.minifig_section].append(entry)

    def get_entry_by_code(self, code: str) -> CatalogEntry | None:
        """Return a catalog entry by part code."""
        return self.by_code.get(code)

    def get_entry_by_description(self, description: str) -> CatalogEntry | None:
        """Return a catalog entry by part description."""
        return self.by_description.get(description)

    def entries_by_category(self, category: PartCategory) -> tuple[CatalogEntry, ...]:
        """Return catalog entries in a category."""
        try:
            return self._entries_by_category_cache[category]
        except KeyError:
            entries = tuple(self.by_category.get(category, ()))
            self._entries_by_category_cache[category] = entries
            return entries

    def minifig_entries(
        self,
        section: MinifigSection | None = None,
    ) -> tuple[CatalogEntry, ...]:
        """Return minifigure catalog entries, optionally for one section."""
        if section is not None:
            return tuple(self.by_minifig_section.get(section, ()))
        entries: list[CatalogEntry] = []
        for section_entries in self.by_minifig_section.values():
            entries.extend(section_entries)
        return tuple(entries)

    def search(
        self,
        query: str,
        *,
        within: Iterable[CatalogEntry] | None = None,
        fields: Iterable[CatalogSearchField] = ALL_CATALOG_SEARCH_FIELDS,
        limit: int | None = None,
    ) -> tuple[CatalogEntry, ...]:
        """Return normalized token matches in deterministic relevance order.

        Every token must occur somewhere in the selected fields. ``within``
        scopes the search to a caller-provided category or other subset.
        """
        if limit is not None and limit < 0:
            message = "search limit must be non-negative"
            raise ValueError(message)
        selected_fields = tuple(dict.fromkeys(fields))
        if not selected_fields:
            return ()
        entries = tuple(within) if within is not None else tuple(self.by_code.values())
        normalized = _normalize_search_text(query)
        tokens = normalized.split()
        if not tokens:
            matches = entries
        else:
            matches = tuple(
                entry
                for entry in entries
                if all(
                    token in self._search_haystack(entry, selected_fields)
                    for token in tokens
                )
            )
            matches = tuple(
                sorted(
                    matches,
                    key=lambda entry: (
                        _catalog_search_rank(entry, normalized),
                        entry.code.casefold(),
                        _normalize_search_text(entry.description),
                    ),
                ),
            )
        return matches if limit is None else matches[:limit]

    def _search_haystack(
        self,
        entry: CatalogEntry,
        fields: tuple[CatalogSearchField, ...],
    ) -> str:
        key = (entry.code, fields)
        if (cached := self._search_haystacks.get(key)) is not None:
            return cached
        values: list[str] = []
        for field_name in fields:
            match field_name:
                case CatalogSearchField.CODE:
                    values.append(entry.code)
                case CatalogSearchField.DESCRIPTION:
                    values.append(entry.description)
                case CatalogSearchField.CATEGORY:
                    values.append(entry.category.value)
                case CatalogSearchField.KEYWORD:
                    values.extend(entry.keywords)
        cached = _normalize_search_text(" ".join(values))
        self._search_haystacks[key] = cached
        return cached

    def module_sections(self) -> dict[tuple[str, ...], dict[str, str]]:
        """Return generated module sections keyed by package path.

        Section dicts are keyed by the catalog description exactly as
        written in ``parts.lst``; symbol names (including minifig-prefix
        stripping) are derived at generation time, where collisions are
        deduplicated with part-code suffixes.
        """
        sections: dict[tuple[str, ...], dict[str, str]] = {}
        for category, entries in self.by_category.items():
            if category == PartCategory.OTHER:
                continue
            module_path = (category.module_name,)
            module_dict = sections.setdefault(module_path, {})
            for entry in entries:
                module_dict[entry.description] = entry.code

        for section, entries in self.by_minifig_section.items():
            module_path = ("minifig", section.value)
            module_dict = sections.setdefault(module_path, {})
            for entry in entries:
                module_dict[entry.description] = entry.code

        return sections


def _normalize_search_text(text: str) -> str:
    """Casefold text and collapse whitespace used for visual alignment."""
    return " ".join(text.casefold().split())


def _catalog_search_rank(entry: CatalogEntry, query: str) -> int:
    code = entry.code.casefold()
    description = _normalize_search_text(entry.description)
    if code == query:
        return 0
    if code.startswith(query):
        return 1
    if description == query:
        return 2
    if description.startswith(query):
        return 3
    if query in description:
        return 4
    return 5


_SourceStatKey = tuple[str, str, int, int, str]


def _source_stat_key(source: str | Path) -> _SourceStatKey:
    """Key a connection source without walking directory descendants.

    Root metadata catches cheap, common changes such as replacing a source
    directory. In-place edits below that root require the explicit
    ``Parts.fresh`` or ``Parts.clear_cache`` invalidation path.
    """
    path = Path(source).expanduser()
    try:
        stat_result = path.stat()
        if path.is_dir():
            return (
                str(path),
                "directory",
                stat_result.st_mtime_ns,
                stat_result.st_size,
                f"{stat_result.st_dev}:{stat_result.st_ino}",
            )
    except OSError:
        return (str(path), "unreadable", -1, -1, "")
    return (
        str(path),
        "file",
        stat_result.st_mtime_ns,
        stat_result.st_size,
        "",
    )


@lru_cache(maxsize=8)
def _parts_for_stat(
    parts_lst: str,
    _stat_key: tuple[int, int],
    _tree_fingerprint: str | None,
    _parts_lst_md5: str | None,
    connection_shadows: tuple[_SourceStatKey, ...],
    studio_metadata: tuple[_SourceStatKey, ...],
) -> Parts:
    parts = Parts(parts_lst)
    parts._memo_building = True  # noqa: SLF001 - factory owns the instance
    try:
        for source, *_ in connection_shadows:
            parts.add_connection_shadow(source)
        for source, *_ in studio_metadata:
            parts.add_studio_metadata(source)
    finally:
        parts._memo_building = False  # noqa: SLF001
    return parts


class Parts:
    """Part catalog loader."""

    # Finish tokens recognized in LDConfig !COLOUR lines. GLITTER and
    # SPECKLE appear after a MATERIAL token; LUMINANCE marks glow-in-the-dark
    # colours. MATERIAL itself is not an attribute — it always accompanies
    # GLITTER or SPECKLE and would only add noise.
    ColourAttributes = (
        "CHROME",
        "PEARLESCENT",
        "RUBBER",
        "MATTE_METALLIC",
        "METAL",
        "GLITTER",
        "SPECKLE",
        "LUMINANCE",
    )

    @classmethod
    def get(
        cls,
        parts_lst: str | Path,
        *,
        tree_fingerprint: str | None = None,
        parts_lst_md5: str | None = None,
        connection_shadows: Iterable[str | Path] = (),
        studio_metadata: Iterable[str | Path] = (),
    ) -> Parts:
        """Get a memoized Parts keyed by list and optional content fingerprints.

        Omitting ``parts_lst_md5`` memoizes under a different key than
        passing it, so mixing both styles for one file parses it twice.
        Directory connection sources are deliberately not walked on cache
        lookup; call ``fresh`` after editing their nested contents.
        """
        path = Path(parts_lst).expanduser()
        stat_result = path.stat()
        return _parts_for_stat(
            str(path),
            (stat_result.st_mtime_ns, stat_result.st_size),
            tree_fingerprint,
            parts_lst_md5,
            tuple(_source_stat_key(source) for source in connection_shadows),
            tuple(_source_stat_key(source) for source in studio_metadata),
        )

    @classmethod
    def clear_cache(cls) -> None:
        """Clear memoized instances, including stale directory sources."""
        _parts_for_stat.cache_clear()

    @classmethod
    def fresh(
        cls,
        parts_lst: str | Path,
        *,
        tree_fingerprint: str | None = None,
        parts_lst_md5: str | None = None,
        connection_shadows: Iterable[str | Path] = (),
        studio_metadata: Iterable[str | Path] = (),
    ) -> Parts:
        """Return a freshly constructed Parts, replacing the memoized one.

        Explicit rebuild paths call this to guarantee a genuinely fresh
        categorization and reload nested connection-source edits; the memo
        is repopulated with the fresh instance.
        """
        cls.clear_cache()
        return cls.get(
            parts_lst,
            tree_fingerprint=tree_fingerprint,
            parts_lst_md5=parts_lst_md5,
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )

    def __init__(self, parts_lst: str | Path) -> None:
        logger.debug("reading parts %s", parts_lst)
        self.path = Path(parts_lst)

        self.parts_dirs: list[Path] = []
        self.parts_subdirs: dict[str, Path] = {}
        self.by_name: dict[str, str] = {}
        self.by_code: dict[str, str] = {}
        self.by_code_name: dict[tuple[str, str], Part | None] = {}
        self.by_category: defaultdict[str, dict[str, str]] = defaultdict(dict)

        self.primitives_by_name: dict[str, str] = {}
        self.primitives_by_code: dict[str, str] = {}

        self.colours: dict[str | int, str] = {}
        self.alpha_values: dict[str | int, int] = {}
        self.colour_attributes: dict[str | int, list[str]] = {}

        self.colours_by_name: dict[str, Colour] = {}
        self.colours_by_code: dict[int, Colour] = {}

        self._catalog = PartsCatalog()
        self._categorized = False
        self._categorize_lock = threading.Lock()
        self._minifig_sections_by_code: dict[str, MinifigSection] = {}
        self._connection_shadow_libraries: list[LDCadShadowLibrary] = []
        self._studio_connection_libraries: list[StudioConnectionLibrary] = []
        self._connection_overrides: dict[
            str,
            tuple[tuple[ConnectionFeature, ...], bool],
        ] = {}
        self._tyre_rim_compatibility: tuple[PartCompatibility, ...] | None = None
        self._memo_building: bool = False

        self.load()

    @property
    def library_root(self) -> Path:
        """Directory containing ``parts.lst``, parts, primitives, and colours."""
        return self.path.parent

    @classmethod
    def from_catalog(cls, parts_lst: str | Path, catalog: PartsCatalog) -> Parts:
        """Construct a Parts that adopts a prebuilt catalog.

        Skips the expensive per-part categorization pass.
        """
        parts = cls(parts_lst)
        parts.adopt_catalog(catalog)
        return parts

    def adopt_catalog(self, catalog: PartsCatalog) -> None:
        """Adopt a prebuilt catalog, skipping categorization.

        A no-op when this instance is already categorized, so a memoized
        instance can safely adopt the same persisted index repeatedly.
        """
        with self._categorize_lock:
            if self._categorized:
                return
            self._catalog = catalog
            for entry in catalog.by_code.values():
                self.by_code_name[(entry.code, entry.description)] = entry.part
                self.by_category[entry.category.value][entry.description] = entry.code
                self.by_category[""][entry.description] = entry.code
            self._categorized = True

    @property
    def catalog(self) -> PartsCatalog:
        """The typed parts catalog, categorized on first access."""
        self._ensure_categorized()
        return self._catalog

    def _ensure_categorized(self) -> None:
        if self._categorized:
            return
        with self._categorize_lock:
            if not self._categorized:
                self._categorize_parts()
                self._categorized = True

    def build_catalog(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> PartsCatalog:
        """Materialize the catalog with determinate progress and cancellation."""
        if self._categorized:
            return self._catalog
        with self._categorize_lock:
            if not self._categorized:
                self._categorize_parts(
                    on_progress=on_progress,
                    cancellation=cancellation,
                )
                self._categorized = True
        return self._catalog

    def get_entry_by_code(self, code: str) -> CatalogEntry | None:
        """Return a typed catalog entry by part code."""
        return self.catalog.get_entry_by_code(code)

    def get_entry_by_description(self, description: str) -> CatalogEntry | None:
        """Return a typed catalog entry by part description."""
        return self.catalog.get_entry_by_description(description)

    def entries_by_category(self, category: PartCategory) -> tuple[CatalogEntry, ...]:
        """Return entries in a part category."""
        return self.catalog.entries_by_category(category)

    def minifig_entries(
        self,
        section: MinifigSection | None = None,
    ) -> tuple[CatalogEntry, ...]:
        """Return entries in minifigure sections."""
        return self.catalog.minifig_entries(section)

    def get_category(self, part_description: str) -> PartCategory | None:
        """Get the category of a part based on its description."""
        split = part_description.strip(" ~=_|").split()
        if not split:
            return None

        if split[0].lower() in {"space", "castle"} and len(split) >= 2:
            potential = split[1]
        else:
            potential = split[0]
        return PartCategory.from_label(potential)

    def load(self) -> None:
        """Load the parts list, colours, and primitives (all cheap passes).

        The expensive categorization pass — opening every part file for its
        ``!CATEGORY`` header — runs lazily on first catalog access.
        """
        self._load_parts_list()
        self._scan_library_directories()

    def _load_parts_list(self) -> None:
        """Load parts from the parts.lst file, skipping malformed lines."""
        duplicate_descriptions = 0
        with self.path.open(mode="r", encoding="utf-8") as parts_lst_file:
            for line_number, line in enumerate(parts_lst_file, start=1):
                if not line.strip():
                    continue
                pieces = DOT_DAT.split(line, maxsplit=1)
                if len(pieces) != 2:
                    logger.warning(
                        "skipping malformed line %d in %s: %r",
                        line_number,
                        self.path,
                        line.strip(),
                    )
                    continue

                code, description = self.section_find(pieces)
                if description in self.by_name and self.by_name[description] != code:
                    duplicate_descriptions += 1
                self.by_name[description] = code
                self.by_code[code] = description
                self.by_code_name[(code, description)] = None
        if duplicate_descriptions:
            logger.info(
                "%d parts in %s share a description with another part"
                " (mostly '=' alias parts); lookups by description and"
                " generated symbols resolve to the last listed code",
                duplicate_descriptions,
                self.path,
            )

    def _scan_library_directories(self) -> None:
        """Scan the library directory for parts, colours, and primitives."""
        for item in self.path.parent.iterdir():
            name = item.name.lower()
            match name:
                case "parts" | "p" if item.is_dir():
                    self.parts_dirs.append(item)
                    self._find_parts_subdirs(item)
                case "ldconfig.ldr":
                    self._load_colours(item)
                case "p.lst" if item.is_file():
                    self._load_primitives(item)

    def _categorize_parts(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        cancellation: CancellationToken | None = None,
    ) -> None:
        """Load part files and categorize them, skipping unloadable ones."""
        entries = tuple(self.by_code_name)
        total = len(entries)
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.INDEX_REBUILD,
                message="Classifying parts",
                current=0,
                total=total,
                path=self.path,
                unit=ProgressUnit.PARTS,
            ),
        )
        for current, (code, description) in enumerate(entries, start=1):
            check_cancelled(cancellation)
            try:
                part = self.part(code=code)
                part_category = part.category
            except (OSError, PartError, UnicodeError, ValueError):
                logger.warning(
                    "skipping part %s (%r): part file missing or unparseable",
                    code,
                    description,
                )
                # Only build events when a callback is registered: this
                # loop runs for every part in the library.
                if on_progress is not None:
                    on_progress(
                        ProgressEvent(
                            stage=ProgressStage.INDEX_REBUILD,
                            message="Classifying parts",
                            current=current,
                            total=total,
                            path=self.path,
                            unit=ProgressUnit.PARTS,
                        ),
                    )
                continue
            self.by_code_name[(code, description)] = part
            category = PartCategory.from_label(part_category)
            if category is None and part_category is not None:
                logger.warning(
                    "unknown LDraw category %r for part %s;"
                    " falling back to description",
                    part_category,
                    code,
                )
            if category is None:
                category = self.get_category(description)
            if category is None:
                category = PartCategory.OTHER

            self.by_category[category.value][description] = code
            self.by_category[""].update({description: code})
            self._catalog.add(
                CatalogEntry(
                    code=code,
                    description=description,
                    category=category,
                    part=part,
                    minifig_section=self._minifig_sections_by_code.get(code),
                    keywords=part.keywords,
                    metadata=part.metadata,
                ),
            )
            if on_progress is not None:
                on_progress(
                    ProgressEvent(
                        stage=ProgressStage.INDEX_REBUILD,
                        message="Classifying parts",
                        current=current,
                        total=total,
                        path=self.path,
                        unit=ProgressUnit.PARTS,
                    ),
                )

    def section_find(self, pieces: list[str]) -> tuple[str, str]:
        """Return code and description from a parts.lst split line.

        The description is kept exactly as written in ``parts.lst``;
        detected minifig sections are recorded for the catalog. Generated
        symbol names strip the ``Minifig `` prefix at generation time
        (see ``symbol_description``).
        """
        code = pieces[0]
        description = pieces[1].strip()
        if (split := _split_minifig_description(description)) is not None:
            self._minifig_sections_by_code[code] = split[1]
        return code, description

    def description_for(self, code: str) -> str | None:
        """Return the ``parts.lst`` description for a part code, or None.

        The lookup tolerates casing differences: ``Piece.part`` preserves
        whatever casing the source used while ``parts.lst`` codes are
        typically lowercase, so the code is tried as given, lowercased,
        and uppercased.
        """
        for candidate in dict.fromkeys((code, code.lower(), code.upper())):
            if (description := self.by_code.get(candidate)) is not None:
                return description
        return None

    def part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part:
        """Get a Part from its description or code.

        Raises ``PartNotFoundError`` when the description or code is not
        in the library or the part file is missing; use ``find_part`` for
        a lookup that returns None instead.
        """
        if description is not None:
            try:
                code = self.by_name[description]
            except KeyError:
                raise PartNotFoundError(
                    code=description,
                    path=str(self.path),
                ) from None
        if code is None:
            message = "part() needs a description or a code"
            raise ValueError(message)
        return self._load_part(code)

    def find_part(
        self,
        description: str | None = None,
        code: str | None = None,
    ) -> Part | None:
        """Get a Part from its description or code, or None when not found."""
        try:
            return self.part(description=description, code=code)
        except PartError:
            return None

    def bounding_box(self, code: str) -> BoundingBox:
        """Axis-aligned bounding box of a part's geometry, in LDU.

        Subfiles are resolved recursively; unresolvable ones are skipped
        with a warning. Raises ``PartNotFoundError`` for an unknown code
        and ``NoGeometryError`` when the part draws nothing.
        """
        from ldraw.part_geometry import part_bounding_box  # noqa: PLC0415

        return part_bounding_box(self, code)

    def geometry(self, code: str) -> PartGeometry:
        """Return exact expanded geometry and completeness diagnostics."""
        from ldraw.part_geometry import part_geometry  # noqa: PLC0415

        return part_geometry(self, code)

    def connections(self, code: str) -> tuple[ConnectionFeature, ...]:
        """Return physical connection features detected for a part."""
        return self.connection_metadata(code).features

    def connection_metadata(self, code: str) -> ConnectionMetadataReport:
        """Return features and normalized metadata coverage for a part."""
        from ldraw.part_geometry import part_geometry  # noqa: PLC0415

        report = part_geometry(self, code).connection_metadata
        if report is None:  # pragma: no cover - defensive for third-party adapters
            message = f"connection metadata report unavailable for {code!r}"
            raise RuntimeError(message)
        return report

    def add_connection_shadow(self, source: str | Path) -> None:
        """Add an LDCad shadow library as an optional connection source.

        Sources are applied in registration order; later sources can clear or
        supersede features from earlier sources.
        """
        from ldraw.connection_metadata import LDCadShadowLibrary  # noqa: PLC0415

        self._connection_shadow_libraries.append(LDCadShadowLibrary(source))
        self._clear_derived_geometry()

    def clear_connection_shadows(self) -> None:
        """Remove all configured LDCad shadow-library sources."""
        self._connection_shadow_libraries.clear()
        self._clear_derived_geometry()

    def add_studio_metadata(self, source: str | Path) -> None:
        """Add a Studio connectivity JSON source at Studio precedence."""
        from ldraw.connection_studio import StudioConnectionLibrary  # noqa: PLC0415

        self._studio_connection_libraries.append(StudioConnectionLibrary(source))
        self._clear_derived_geometry()

    def clear_studio_metadata(self) -> None:
        """Remove every configured Studio connectivity source."""
        self._studio_connection_libraries.clear()
        self._clear_derived_geometry()

    def set_connection_overrides(
        self,
        code: str,
        features: Iterable[ConnectionFeature],
        *,
        replace_existing: bool = False,
    ) -> None:
        """Register authoritative connection features for one part.

        By default overrides augment inferred and shadow-derived features.
        Set ``replace_existing`` to discard every lower-priority feature.
        """
        from dataclasses import replace  # noqa: PLC0415

        from ldraw.connection_types import (  # noqa: PLC0415
            ConnectionProvenance,
            ConnectionSource,
        )

        key = _reference_key(code)
        self._connection_overrides[key] = (
            tuple(
                replace(
                    feature,
                    feature_id=feature.feature_id or f"override:{index}",
                    source=ConnectionSource.OVERRIDE,
                    owner_code=code,
                    connection_provenance=ConnectionProvenance(
                        source=ConnectionSource.OVERRIDE,
                        command=f"explicit override {index}",
                    ),
                )
                for index, feature in enumerate(features)
            ),
            replace_existing,
        )
        self._clear_derived_geometry()

    def clear_connection_overrides(self, code: str | None = None) -> None:
        """Remove connection overrides for one part or the whole library."""
        if code is None:
            self._connection_overrides.clear()
        else:
            self._connection_overrides.pop(_reference_key(code), None)
        self._clear_derived_geometry()

    @property
    def tyre_rim_compatibility(self) -> tuple[PartCompatibility, ...]:
        """Tyre/rim pairs evidenced by official complete-part shortcuts."""
        if self._tyre_rim_compatibility is None:
            self._tyre_rim_compatibility = self._build_tyre_rim_compatibility()
        return self._tyre_rim_compatibility

    def compatible_tyres(self, rim_code: str) -> tuple[str, ...]:
        """Return tyre codes evidenced as compatible with ``rim_code``."""
        key = _reference_key(rim_code)
        return tuple(
            relation.second
            for relation in self.tyre_rim_compatibility
            if _reference_key(relation.first) == key
        )

    def compatible_rims(self, tyre_code: str) -> tuple[str, ...]:
        """Return rim codes evidenced as compatible with ``tyre_code``."""
        key = _reference_key(tyre_code)
        return tuple(
            relation.first
            for relation in self.tyre_rim_compatibility
            if _reference_key(relation.second) == key
        )

    def _shadow_connections_for(self, code: str) -> ShadowConnectionResult:
        from ldraw.connection_metadata import ShadowConnectionResult  # noqa: PLC0415

        shadows = tuple(self._connection_shadow_libraries)
        combined = ShadowConnectionResult()
        for library in shadows:
            combined = combined.combined(
                library.connections_for(code, siblings=shadows),
            )
        return combined

    def _connection_shadows_for_inline(self) -> tuple[LDCadShadowLibrary, ...]:
        return tuple(self._connection_shadow_libraries)

    def _connection_metadata_for(
        self,
        code: str,
    ) -> tuple[ShadowConnectionResult, ...]:
        shadows = tuple(self._connection_shadow_libraries)
        return (
            *(library.connections_for(code, siblings=shadows) for library in shadows),
            *(
                library._part_feature_contribution(code)  # noqa: SLF001
                for library in self._studio_connection_libraries
            ),
        )

    def _connection_document_results(
        self,
        codes: frozenset[str],
    ) -> tuple[ShadowConnectionResult, ...]:
        return tuple(
            library._document_result_for(codes)  # noqa: SLF001
            for library in self._studio_connection_libraries
        )

    def _connection_overrides_for(
        self,
        code: str,
    ) -> tuple[tuple[ConnectionFeature, ...], bool]:
        return self._connection_overrides.get(_reference_key(code), ((), False))

    def _clear_derived_geometry(self) -> None:
        from ldraw.part_geometry import clear_part_geometry_cache  # noqa: PLC0415

        clear_part_geometry_cache(self)
        if not self._memo_building:
            # Mutating connection sources changes what any memo key would
            # rebuild, so drop memoized instances rather than alias them.
            _parts_for_stat.cache_clear()

    def _build_tyre_rim_compatibility(self) -> tuple[PartCompatibility, ...]:
        from ldraw.connection_types import (  # noqa: PLC0415
            ConnectionSource,
            PartCompatibility,
        )

        descriptions = {
            _reference_key(code): (code, description.strip(" ~=_|-"))
            for code, description in self.by_code.items()
        }
        rims = {
            key
            for key, (_, description) in descriptions.items()
            if description.casefold().startswith("wheel rim ")
            and " with tyre " not in description.casefold()
        }
        tyres = {
            key
            for key, (_, description) in descriptions.items()
            if description.casefold().startswith("tyre ")
        }
        pairs: dict[tuple[str, str], PartCompatibility] = {}
        for shortcut_code, shortcut_description in self.by_code.items():
            if " with tyre " not in shortcut_description.casefold():
                continue
            try:
                references = self.references_for(shortcut_code)
            except (OSError, PartError, UnicodeError, ValueError):
                logger.warning(
                    "could not inspect wheel/tyre shortcut %s",
                    shortcut_code,
                )
                continue
            referenced = {_reference_key(reference.code) for reference in references}
            shortcut_rims = referenced & rims
            shortcut_tyres = referenced & tyres
            for rim_key in sorted(shortcut_rims):
                rim_code = descriptions[rim_key][0]
                for tyre_key in sorted(shortcut_tyres):
                    tyre_code = descriptions[tyre_key][0]
                    pairs.setdefault(
                        (rim_key, tyre_key),
                        PartCompatibility(
                            first=rim_code,
                            second=tyre_code,
                            relation="tyre_rim",
                            source=ConnectionSource.SHORTCUT,
                            evidence=shortcut_code,
                        ),
                    )
        return tuple(pairs[key] for key in sorted(pairs))

    def inspect_part(
        self,
        code: str,
        *,
        include_geometry: bool = True,
        recursive_references: bool = False,
    ) -> PartInspection:
        """Inspect one part without translating failures into empty data."""
        diagnostics: list[Diagnostic] = []
        try:
            entry = self.get_entry_by_code(code)
        except (OSError, PartError, UnicodeError, ValueError) as exc:
            entry = None
            diagnostics.append(
                Diagnostic(
                    line_number=0,
                    message=f"Could not read catalog metadata for {code}: {exc}",
                    severity=Severity.ERROR,
                    code=DiagnosticCode.PART_HEADER_INVALID,
                    path=self.library_root,
                    offending_value=code,
                    cause=exc,
                ),
            )
        try:
            part = self.part(code=code)
        except PartError as exc:
            return PartInspection(
                code=code,
                entry=entry,
                path=None,
                metadata=None,
                references=(),
                geometry=None,
                diagnostics=(
                    Diagnostic(
                        line_number=0,
                        message=str(exc),
                        severity=Severity.ERROR,
                        code=DiagnosticCode.PART_NOT_FOUND,
                        path=self.library_root,
                        offending_value=code,
                        cause=exc,
                    ),
                ),
            )
        try:
            metadata = part.metadata
        except (OSError, PartError, UnicodeError, ValueError) as exc:
            metadata = None
            diagnostics.append(
                Diagnostic(
                    line_number=0,
                    message=f"Could not parse metadata for {code}: {exc}",
                    severity=Severity.ERROR,
                    code=DiagnosticCode.PART_HEADER_INVALID,
                    path=part.path,
                    offending_value=code,
                    cause=exc,
                ),
            )
        try:
            references = self.references_for(code, recursive=recursive_references)
        except (OSError, PartError, UnicodeError, ValueError) as exc:
            references = ()
            diagnostics.append(
                Diagnostic(
                    line_number=0,
                    message=f"Could not inspect references for {code}: {exc}",
                    severity=Severity.ERROR,
                    code=DiagnosticCode.PART_REFERENCE_UNRESOLVED,
                    path=part.path,
                    offending_value=code,
                    cause=exc,
                ),
            )
        geometry = None
        if include_geometry:
            try:
                geometry = self.geometry(code)
                diagnostics.extend(geometry.diagnostics)
            except (OSError, PartError, UnicodeError, ValueError) as exc:
                diagnostics.append(
                    Diagnostic(
                        line_number=0,
                        message=f"Could not inspect geometry for {code}: {exc}",
                        severity=Severity.ERROR,
                        code=DiagnosticCode.GEOMETRY_INCOMPLETE,
                        path=part.path,
                        offending_value=code,
                        cause=exc,
                    ),
                )
        return PartInspection(
            code=code,
            entry=entry,
            path=part.path,
            metadata=metadata,
            references=references,
            geometry=geometry,
            diagnostics=tuple(diagnostics),
        )

    def studs(self, code: str) -> tuple[StudReference, ...]:
        """All stud primitives a part places, in the part's own coordinates.

        Includes underside tubes and other downward studs; filter with
        ``StudReference.is_top_stud`` or use ``stud_positions``.
        """
        from ldraw.part_geometry import part_studs  # noqa: PLC0415

        return part_studs(self, code)

    def stud_positions(self, code: str) -> tuple[Vector, ...]:
        """Positions of a part's top studs (upward connectors), in LDU."""
        return tuple(stud.position for stud in self.studs(code) if stud.is_top_stud)

    def resolve_colour(self, colour: Colour | int) -> Colour:
        """Return catalog metadata for ``colour`` when it is known."""
        candidate = colour if isinstance(colour, Colour) else Colour(code=colour)
        if candidate.code is None:
            return candidate
        return self.colours_by_code.get(candidate.code, candidate)

    def references_for(
        self,
        code: str,
        *,
        recursive: bool = False,
    ) -> tuple[PartReference, ...]:
        """Return type-1 references placed by a part file."""
        return tuple(
            self._references_for(
                code=code,
                recursive=recursive,
                visiting=frozenset(),
                depth=0,
            ),
        )

    def _references_for(
        self,
        *,
        code: str,
        recursive: bool,
        visiting: frozenset[str],
        depth: int,
    ) -> list[PartReference]:
        key = _reference_key(code)
        if key in visiting:
            return []
        part = self.part(code=code)
        visiting = visiting | {key}
        references: list[PartReference] = []
        for obj in part.objects:
            if not isinstance(obj, Piece):
                continue
            reference = self._part_reference(
                parent_code=code,
                piece=obj,
                depth=depth + 1,
            )
            references.append(reference)
            if recursive and reference.kind is not PartReferenceKind.UNKNOWN:
                references.extend(
                    self._references_for(
                        code=reference.code,
                        recursive=True,
                        visiting=visiting,
                        depth=depth + 1,
                    ),
                )
        return references

    def _part_reference(
        self,
        *,
        parent_code: str,
        piece: Piece,
        depth: int,
    ) -> PartReference:
        code = _normalized_reference_code(piece.part)
        part = self.find_part(code=code)
        kind = self._reference_kind(code, part)
        return PartReference(
            parent_code=parent_code,
            code=code,
            reference=_normalized_reference_code(piece.reference),
            kind=kind,
            description=self._reference_description(code, kind, part),
            colour=self.resolve_colour(piece.colour),
            position=piece.position.copy(),
            matrix=piece.matrix.copy(),
            depth=depth,
        )

    @cached_property
    def _by_code_normalized(self) -> dict[str, str]:
        return _normalized_index(self.by_code)

    @cached_property
    def _primitives_by_code_normalized(self) -> dict[str, str]:
        return _normalized_index(self.primitives_by_code)

    def _primitive_description(self, key: str) -> str | None:
        primitives = self._primitives_by_code_normalized
        if (description := primitives.get(key)) is not None:
            return description
        return primitives.get(key.rpartition("/")[2])

    def _reference_kind(
        self,
        code: str,
        part: Part | None,
    ) -> PartReferenceKind:
        key = _reference_key(code)
        if key in self._by_code_normalized:
            return PartReferenceKind.PART
        primitives = self._primitives_by_code_normalized
        if key in primitives or key.rpartition("/")[2] in primitives:
            return PartReferenceKind.PRIMITIVE
        if part is None:
            return PartReferenceKind.UNKNOWN
        if key.split("/", maxsplit=1)[0] in {"8", "48", "p"}:
            return PartReferenceKind.PRIMITIVE
        return PartReferenceKind.SUBPART

    def _reference_description(
        self,
        code: str,
        kind: PartReferenceKind,
        part: Part | None,
    ) -> str | None:
        match kind:
            case PartReferenceKind.PART:
                return self.description_for(code)
            case PartReferenceKind.PRIMITIVE:
                return self._primitive_description(_reference_key(code))
            case PartReferenceKind.SUBPART if part is not None:
                return part.description
            case _:
                return None

    def _find_parts_subdirs(self, directory: Path) -> None:
        for item in directory.iterdir():
            if item.is_dir():
                self.parts_subdirs[item.name] = item
                self.parts_subdirs[item.name.lower()] = item
                self.parts_subdirs[item.name.upper()] = item

    def _load_part(self, code: str) -> Part:
        normalized_code = code.replace("\\", "/")
        if "/" in normalized_code:
            pieces = normalized_code.split("/")
            if len(pieces) != 2:
                raise PartNotFoundError(code=code, path=str(self.path))
            try:
                parts_dirs = [self.parts_subdirs[pieces[0]]]
            except KeyError:
                raise PartNotFoundError(code=code, path=str(self.path)) from None
            normalized_code = pieces[1]
        else:
            parts_dirs = self.parts_dirs

        paths = [
            candidate
            for parts_dir in parts_dirs
            for candidate in (
                parts_dir / f"{normalized_code.lower()}.dat",
                parts_dir / f"{normalized_code.upper()}.DAT",
            )
        ]
        for path in paths:
            if path.exists():
                return Part(path)
        raise PartNotFoundError(code=code, path=str(self.path))

    def _load_colours(self, path: Path) -> None:
        try:
            colours_part = Part(path=path)
        except PartError:
            return
        for obj in colours_part.objects:
            if not isinstance(obj, MetaCommand) or obj.type != "COLOUR":
                continue
            pieces = obj.text.split()
            try:
                name = pieces[0]
                code = int(pieces[pieces.index("CODE") + 1])
                rgb = pieces[pieces.index("VALUE") + 1]
            except (ValueError, IndexError):
                continue

            alpha: int | None
            try:
                alpha = int(pieces[pieces.index("ALPHA") + 1])
            except (IndexError, ValueError):
                alpha = None

            colour_attributes = [
                attribute for attribute in Parts.ColourAttributes if attribute in pieces
            ]

            try:
                colour = Colour(
                    code=code,
                    name=name,
                    rgb=rgb,
                    alpha=alpha if alpha is not None else 255,
                    colour_attributes=colour_attributes,
                )
            except ValueError:
                logger.warning(
                    "ignoring colour %r (code %s): invalid VALUE %r",
                    name,
                    code,
                    rgb,
                )
                continue

            canonical_rgb = cast("str", colour.rgb)
            if alpha is not None:
                self.alpha_values[name] = alpha
                self.alpha_values[code] = alpha
            self.colours[name] = canonical_rgb
            self.colours[code] = canonical_rgb
            self.colour_attributes[name] = colour_attributes
            self.colour_attributes[code] = colour_attributes
            self.colours_by_name[name] = colour
            self.colours_by_code[code] = colour

    def _load_primitives(self, path: Path) -> None:
        with path.open(mode="r", encoding="utf-8") as part_path:
            for line_number, line in enumerate(part_path, start=1):
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
                code = pieces[0]
                description = pieces[1].strip()
                self.primitives_by_name[description] = code
                self.primitives_by_code[code] = description
