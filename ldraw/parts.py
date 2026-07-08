"""Part management classes for the Python ldraw package."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ldraw.colour import Colour
from ldraw.errors import PartError, PartNotFoundError
from ldraw.lines import MetaCommand
from ldraw.part import Part

if TYPE_CHECKING:
    from ldraw.geometry import Vector
    from ldraw.part_geometry import BoundingBox, StudReference

DOT_DAT = re.compile(r"\.DAT", flags=re.IGNORECASE)
logger = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Typed catalog entry for one part or primitive."""

    code: str
    description: str
    category: PartCategory
    part: Part | None = None
    minifig_section: MinifigSection | None = None
    keywords: tuple[str, ...] = ()


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

    def add(self, entry: CatalogEntry) -> None:
        """Add or replace an entry in every lookup index."""
        self.by_code[entry.code] = entry
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

    def module_sections(self) -> dict[tuple[str, ...], dict[str, str]]:
        """Return generated module sections keyed by package path.

        Section dicts are keyed by ``symbol_description`` (the minifig
        prefix is stripped), not by the catalog description.
        """
        sections: dict[tuple[str, ...], dict[str, str]] = {}
        for category, entries in self.by_category.items():
            if category == PartCategory.OTHER:
                continue
            module_path = (category.module_name,)
            module_dict = sections.setdefault(module_path, {})
            for entry in entries:
                module_dict[symbol_description(entry.description)] = entry.code

        for section, entries in self.by_minifig_section.items():
            module_path = ("minifig", section.value)
            module_dict = sections.setdefault(module_path, {})
            for entry in entries:
                module_dict[symbol_description(entry.description)] = entry.code

        return sections


@lru_cache(maxsize=8)
def _parts_for_stat(parts_lst: str, _stat_key: tuple[int, int]) -> Parts:
    return Parts(parts_lst)


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
    def get(cls, parts_lst: str | Path) -> Parts:
        """Get a memoized Parts instance, keyed by path, mtime, and size."""
        path = Path(parts_lst)
        stat_result = path.stat()
        return _parts_for_stat(
            str(path),
            (stat_result.st_mtime_ns, stat_result.st_size),
        )

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the memoized Parts instances."""
        _parts_for_stat.cache_clear()

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
        self._minifig_sections_by_code: dict[str, MinifigSection] = {}

        self.load()

    @classmethod
    def from_catalog(cls, parts_lst: str | Path, catalog: PartsCatalog) -> Parts:
        """Construct a Parts that adopts a prebuilt catalog.

        Skips the expensive per-part categorization pass.
        """
        parts = cls(parts_lst)
        parts._catalog = catalog
        parts._categorized = True
        for entry in catalog.by_code.values():
            parts.by_code_name[(entry.code, entry.description)] = entry.part
            parts.by_category[entry.category.value][entry.description] = entry.code
            parts.by_category[""][entry.description] = entry.code
        return parts

    @property
    def catalog(self) -> PartsCatalog:
        """The typed parts catalog, categorized on first access."""
        self._ensure_categorized()
        return self._catalog

    def _ensure_categorized(self) -> None:
        if not self._categorized:
            self._categorize_parts()
            self._categorized = True

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
        """Load parts from the parts.lst file."""
        duplicate_descriptions = 0
        with self.path.open(mode="r", encoding="utf-8") as parts_lst_file:
            for line in parts_lst_file:
                pieces = re.split(DOT_DAT, line)
                if len(pieces) != 2:
                    break

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

    def _categorize_parts(self) -> None:
        """Load part files and categorize them."""
        for code, description in self.by_code_name:
            part = self.part(code=code)
            self.by_code_name[(code, description)] = part
            category = PartCategory.from_label(part.category)
            if category is None and part.category is not None:
                logger.warning(
                    "unknown LDraw category %r for part %s;"
                    " falling back to description",
                    part.category,
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
            for line in part_path:
                pieces = re.split(DOT_DAT, line)
                if len(pieces) != 2:
                    break
                code = pieces[0]
                description = pieces[1].strip()
                self.primitives_by_name[description] = code
                self.primitives_by_code[code] = description
