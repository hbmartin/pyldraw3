"""Part file parsing and processing functionality."""

import re
from pathlib import Path

from ldraw.colour import Colour
from ldraw.errors import InvalidLineDataError, PartError
from ldraw.geometry import Matrix, Vector
from ldraw.lines import (
    Comment,
    Line,
    MetaCommand,
    OptionalLine,
    Quadrilateral,
    Triangle,
)
from ldraw.pieces import Piece

ENDS_DOT_DAT = re.compile(r"\.DAT$", flags=re.IGNORECASE)


def colour_from_str(colour_str):
    """Get a Colour from a string."""
    try:
        return int(colour_str)
    except ValueError:
        if colour_str.startswith("0x2"):
            return Colour(rgb="#" + colour_str[3:], alpha=255)


def _comment_or_meta(pieces):
    if not pieces:
        return Comment("")
    if pieces[0][:1] == "!":
        return MetaCommand(pieces[0][1:], " ".join(pieces[1:]))
    return Comment(" ".join(pieces))


def _sub_file(pieces: list) -> Piece:
    if len(pieces) != 14:
        raise InvalidLineDataError("subfile", 14, pieces)
    colour = colour_from_str(pieces[0])
    position = list(map(float, pieces[1:4]))
    rows = [
        list(map(float, pieces[4:7])),
        list(map(float, pieces[7:10])),
        list(map(float, pieces[10:13])),
    ]
    part = pieces[13].upper()
    if re.search(ENDS_DOT_DAT, part):
        part = part[:-4]
    return Piece(Colour(colour), Vector(*position), Matrix(rows), part)


def _line(pieces: list) -> Line:
    if len(pieces) != 7:
        raise InvalidLineDataError("lint", 7, pieces)
    colour = colour_from_str(pieces[0])
    point1 = map(float, pieces[1:4])
    point2 = map(float, pieces[4:7])
    return Line(Colour(colour), Vector(*point1), Vector(*point2))


def _triangle(pieces: list) -> Triangle:
    if len(pieces) != 10:
        raise InvalidLineDataError("triangle", 10, pieces)
    colour = colour_from_str(pieces[0])
    point1 = map(float, pieces[1:4])
    point2 = map(float, pieces[4:7])
    point3 = map(float, pieces[7:10])
    return Triangle(Colour(colour), Vector(*point1), Vector(*point2), Vector(*point3))


def _quadrilateral(pieces: list) -> Quadrilateral:
    if len(pieces) != 13:
        raise InvalidLineDataError("quadrilateral", 13, pieces)
    colour = colour_from_str(pieces[0])
    point1 = map(float, pieces[1:4])
    point2 = map(float, pieces[4:7])
    point3 = map(float, pieces[7:10])
    point4 = map(float, pieces[10:13])
    return Quadrilateral(
        Colour(colour),
        Vector(*point1),
        Vector(*point2),
        Vector(*point3),
        Vector(*point4),
    )


def _optional_line(pieces: list) -> OptionalLine:
    if len(pieces) != 13:
        raise InvalidLineDataError("optional", 13, pieces)
    colour = colour_from_str(pieces[0])
    point1 = map(float, pieces[1:4])
    point2 = map(float, pieces[4:7])
    point3 = map(float, pieces[7:10])
    point4 = map(float, pieces[10:13])
    return OptionalLine(
        Colour(colour),
        Vector(*point1),
        Vector(*point2),
        Vector(*point3),
        Vector(*point4),
    )


HANDLERS = {
    "0": _comment_or_meta,
    "1": _sub_file,
    "2": _line,
    "3": _triangle,
    "4": _quadrilateral,
    "5": _optional_line,
}


class Part:
    """Contains data from a LDraw part file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._category = None
        self._description: str | None = None

    @property
    def lines(self):
        """Yield lines from the part file."""
        with self.path.open("r", encoding="utf-8") as file:
            yield from file

    @property
    def objects(self):
        """Load the Part from its path."""
        for number, line in enumerate(self.lines):
            pieces = line.split()
            if not pieces:
                continue
            try:
                handler = HANDLERS[pieces[0]]
            except KeyError as e:
                raise PartError(
                    "Unknown command (%s) in %s at line %i"
                    % (pieces[0], self.path, number),
                ) from e
            try:
                yield handler(pieces[1:])
            except PartError as parse_error:
                raise PartError(
                    parse_error.message + " in %s at line %i" % (self.path, number),
                ) from parse_error

    @property
    def description(self):
        """Get the description of the part from the first line of the file."""
        if self._description is None:
            self._description = " ".join(next(self.lines).split()[1:])
        return self._description

    @property
    def category(self):
        """Get the category of the part from CATEGORY meta command."""
        if self._category is None:
            for obj in self.objects:
                if not isinstance(obj, Comment) and not isinstance(obj, MetaCommand):
                    self._category = None
                    break
                if isinstance(obj, MetaCommand) and obj.type == "CATEGORY":
                    self._category = obj.text
                    break

        return self._category
