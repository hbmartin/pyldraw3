"""parts.py - Part management classes for the Python ldraw package.

Copyright (C) 2008 David Boddie <david@boddie.org.uk>

This file is part of the ldraw Python package.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

# pylint: disable=too-few-public-methods
import contextlib
import hashlib
import logging
import os
import re
from collections import defaultdict
from pathlib import Path

import inflect
from attridict import AttriDict

from ldraw.colour import Colour
from ldraw.errors import PartError, PartNotFoundError
from ldraw.lines import (
    MetaCommand,
)
from ldraw.part import Part

DOT_DAT = re.compile(r"\.DAT", flags=re.IGNORECASE)
logger = logging.getLogger(__name__)


p = inflect.engine()

MEMOIZED = {}


CATEGORIES = {
    "Animal",
    "Antenna",
    "Arch",
    "Arm",
    "Bar",
    "Baseplate",
    "Belville",
    "Boat",
    "Brick",
    "Canvas",
    "Car",
    "Cone",
    "Constraction",
    "Container",
    "Crane",
    "Cylinder",
    "Dish",
    "Door",
    "Electric",
    "Fence",
    "Figure",
    "Figure Accessory",
    "Freestyle",
    "Hinge",
    "Homemaker",
    "Hose",
    "Magnet",
    "Minifig",
    "Minifig Accessory",
    "Minifig Footwear",
    "Minifig Headwear",
    "Minifig Hipwear",
    "Minifig Neckwear",
    "Plane",
    "Plant",
    "Plate",
    "Propellor",
    "Roadsign",
    "Screw",
    "Sheet Cardboard",
    "Sheet Fabric",
    "Sheet Plastic",
    "Slope",
    "Sphere",
    "Staircase",
    "Sticker",
    "Support",
    "Tap",
    "Technic",
    "Tile",
    "Train",
    "Turntable",
    "Tyre",
    "Vehicle",
    "Wheel",
    "Winch",
    "Window",
    "Windscreen",
    "Wing",
}


class Parts:
    # pylint: disable=too-many-instance-attributes
    """Part class."""

    ColourAttributes = ("CHROME", "PEARLESCENT", "RUBBER", "MATTE_METALLIC", "METAL")

    @classmethod
    def get(cls, parts_lst, *args, **kwargs):
        """Get a Parts instance using memoization based on file hash."""
        md5_parts_lst = hashlib.md5(Path(parts_lst).read_bytes()).hexdigest()
        if md5_parts_lst in MEMOIZED:
            return MEMOIZED[md5_parts_lst]
        instance = Parts(parts_lst, *args, **kwargs)
        MEMOIZED[md5_parts_lst] = instance
        return instance

    def __init__(self, parts_lst: str | Path):
        logger.debug("reading parts %s", parts_lst)
        self.path = Path(parts_lst)

        self.parts_dirs: list[Path] = []
        self.parts_subdirs = {}
        self.by_name = {}
        self.by_code = {}
        self.by_code_name = {}
        self.by_category: defaultdict[str, dict[str, str]] = defaultdict(dict)

        self.primitives_by_name = {}
        self.primitives_by_code = {}

        self.colours = {}
        self.alpha_values = {}
        self.colour_attributes = {}

        self.colours_by_name = {}
        self.colours_by_code = {}

        self.parts = AttriDict(
            minifig=AttriDict(
                hats={},
                heads={},
                torsos={},
                hips={},
                legs={},
                arms={},
                hands={},
                accessories={},
            ),
        )

        self.minifig_descriptions = {
            "torsos": "Torso",
            "hips": "Hip",
            "arms": "Arm",
            "heads": "Head",
            "accessories": "Accessory",
            "hands": "Hand",
            "hats": "Hat",
            "legs": "Leg",
        }

        self.load()

        # reference in others
        for v in list(self.by_category.values()):
            self.by_category[""].update(v)

        for k in list(self.by_category.keys()):
            split = k.split()
            if len(split) == 1:
                value = self.by_category.pop(k)
                if k in self.parts:
                    self.parts[k][""] = value
                elif k in {"car", "train", "technic"}:
                    self.parts[k] = value
                else:
                    self.parts[p.plural(k)] = value

    def get_category(self, part_description: str) -> str | None:
        """Get the category of a part based on its description."""
        split = part_description.strip(" ~=_|").split()

        if (split[0].lower() == "space" or split[0].lower() == "castle") and len(
            split,
        ) >= 2:
            potential = split[1]
        else:
            potential = split[0]
        if potential in CATEGORIES:
            return potential
        return None

    def load(self):
        """Load parts from a path."""
        self._load_parts_list()
        self._scan_library_directories()
        self._categorize_parts()

    def _load_parts_list(self):
        """Load parts from the parts.lst file."""
        with self.path.open(mode="r", encoding="utf-8") as parts_lst_file:
            for line in parts_lst_file.readlines():
                pieces = re.split(DOT_DAT, line)
                if len(pieces) != 2:
                    break

                code, description = self.section_find(pieces)
                self.by_name[description] = code
                self.by_code[code] = description
                self.by_code_name[(code, description)] = None

    def _scan_library_directories(self):
        """Scan the library directory for parts, colours, and primitives."""
        for item in self.path.parent.iterdir():
            if (item.name == "parts" and item.is_dir()) or (
                item.name == "p" and item.is_dir()
            ):
                self.parts_dirs.append(item)
                self._find_parts_subdirs(item)
            elif item.name == "ldconfig.ldr":
                self._load_colours(item)
            elif item.name == "p.lst" and item.is_file():
                self._load_primitives(item)

    def _categorize_parts(self):
        """Load part files and categorize them."""
        for code, description in self.by_code_name:
            part = self.part(code=code)
            if part is None:
                raise PartNotFoundError(code=code, path=str(self.path))
            self.by_code_name[(code, description)] = part
            # read from the part, meta comment CATEGORY
            category = part.category
            if category is None:
                # try to infer from the description
                category = self.get_category(description)
            if category is None:
                self.by_category["other"][description] = code
            else:
                self.by_category[category.lower()][description] = code

    def section_find(self, pieces):
        """Return code, description from a pieces element."""
        code = pieces[0]
        description = pieces[1].strip()
        for key, section in self.parts["minifig"].items():
            searched = self.minifig_descriptions[key]
            index_find = description.find(searched)

            if index_find != -1 and (
                index_find + len(searched) == len(description)
                or description[index_find + len(searched)] == " "
            ):
                if description.startswith("Minifig "):
                    description = description[8:]
                    if description.startswith("(") and description.endswith(")"):
                        description = description[1:-1]
                    section[description] = code
                break
        else:
            # The accessories are those Minifig items which do not fall into any
            # of the above categories.
            if description.startswith("Minifig "):
                description = description[8:]
                if description.startswith("(") and description.endswith(")"):
                    description = description[1:-1]
                self.parts["minifig"]["accessories"][description] = code
        return code, description

    def part(self, description=None, code=None) -> Part | None:
        """Get a Part from its description or code."""
        if not self.path:
            return None
        if description:
            with contextlib.suppress(KeyError):
                code = self.by_name[description]
        elif not code:
            return None
        return self._load_part(code)

    def _find_parts_subdirs(self, directory: Path):
        for item in os.listdir(directory):
            obj = os.path.join(directory, item)
            if os.path.isdir(obj):
                self.parts_subdirs[item] = obj
                self.parts_subdirs[item.lower()] = obj
                self.parts_subdirs[item.upper()] = obj

    def _load_part(self, code) -> Part | None:
        code = code.replace("\\", os.sep)
        code = code.replace("/", os.sep)
        if os.sep in code:
            pieces = code.split(os.sep)
            if len(pieces) != 2:
                return None
            try:
                parts_dirs = [self.parts_subdirs[pieces[0]]]
            except KeyError:
                return None
            code = pieces[1]
        else:
            parts_dirs = self.parts_dirs
        paths = []
        for parts_dir in parts_dirs:
            paths.append(os.path.join(parts_dir, code.lower()) + os.extsep + "dat")
            paths.append(os.path.join(parts_dir, code.upper()) + os.extsep + "DAT")
        for path in paths:
            if os.path.exists(path):
                return Part(path)
            continue
        raise PartError("part file not found: %s" % code)

    def _load_colours(self, path: Path):
        try:
            colours_part = Part(path=str(path))
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

                self.colours[name] = rgb
                self.colours[code] = rgb

                colour = Colour(code, name, rgb)
                self.colours_by_name[name] = colour
                self.colours_by_code[code] = colour

            except (ValueError, IndexError):
                continue
            try:
                alpha_at = pieces.index("ALPHA")
                alpha = int(pieces[alpha_at])
                self.alpha_values[name] = alpha
                self.alpha_values[code] = alpha
            except (IndexError, ValueError):
                pass

            colour_attributes = [
                attribute for attribute in Parts.ColourAttributes if attribute in pieces
            ]

            self.colour_attributes[name] = colour_attributes
            self.colour_attributes[code] = colour_attributes

            alpha = self.alpha_values.get(name, 255)
            colour = Colour(code, name, rgb, alpha, colour_attributes)
            self.colours_by_name[name] = colour
            self.colours_by_code[code] = colour

    def _load_primitives(self, path: Path):
        with path.open(mode="r", encoding="utf=8") as part_path:
            for line in part_path:
                pieces = re.split(DOT_DAT, line)
                if len(pieces) != 2:
                    break
                code = pieces[0]
                description = pieces[1].strip()
                self.primitives_by_name[description] = code
                self.primitives_by_code[code] = description
