"""Part file parsing and processing functionality."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
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
ParsedObject = (
    Comment | MetaCommand | Piece | Line | Triangle | Quadrilateral | OptionalLine
)
LineHandler = Callable[[list[str]], ParsedObject]


def colour_from_str(colour_str: str) -> Colour | int | None:
    """Get a colour code or direct colour from a string."""
    try:
        return int(colour_str)
    except ValueError:
        if colour_str.startswith("0x2"):
            return Colour(rgb=f"#{colour_str[3:]}", alpha=255)
    return None


def _colour(pieces: list[str]) -> Colour:
    value = colour_from_str(pieces[0])
    if isinstance(value, Colour):
        return value
    return Colour(value)


def _comment_or_meta(pieces: list[str]) -> Comment | MetaCommand:
    if not pieces:
        return Comment("")
    if pieces[0][:1] == "!":
        return MetaCommand(pieces[0][1:], " ".join(pieces[1:]))
    return Comment(" ".join(pieces))


def _sub_file(pieces: list[str]) -> Piece:
    if len(pieces) != 14:
        raise InvalidLineDataError("subfile", 14, pieces)
    position = [float(value) for value in pieces[1:4]]
    rows = [
        [float(value) for value in pieces[4:7]],
        [float(value) for value in pieces[7:10]],
        [float(value) for value in pieces[10:13]],
    ]
    part = pieces[13].upper()
    if re.search(ENDS_DOT_DAT, part):
        part = part[:-4]
    return Piece(_colour(pieces), Vector(*position), Matrix(rows), part)


def _line(pieces: list[str]) -> Line:
    if len(pieces) != 7:
        raise InvalidLineDataError("line", 7, pieces)
    point1 = [float(value) for value in pieces[1:4]]
    point2 = [float(value) for value in pieces[4:7]]
    return Line(_colour(pieces), Vector(*point1), Vector(*point2))


def _triangle(pieces: list[str]) -> Triangle:
    if len(pieces) != 10:
        raise InvalidLineDataError("triangle", 10, pieces)
    point1 = [float(value) for value in pieces[1:4]]
    point2 = [float(value) for value in pieces[4:7]]
    point3 = [float(value) for value in pieces[7:10]]
    return Triangle(_colour(pieces), Vector(*point1), Vector(*point2), Vector(*point3))


def _quadrilateral(pieces: list[str]) -> Quadrilateral:
    if len(pieces) != 13:
        raise InvalidLineDataError("quadrilateral", 13, pieces)
    point1 = [float(value) for value in pieces[1:4]]
    point2 = [float(value) for value in pieces[4:7]]
    point3 = [float(value) for value in pieces[7:10]]
    point4 = [float(value) for value in pieces[10:13]]
    return Quadrilateral(
        _colour(pieces),
        Vector(*point1),
        Vector(*point2),
        Vector(*point3),
        Vector(*point4),
    )


def _optional_line(pieces: list[str]) -> OptionalLine:
    if len(pieces) != 13:
        raise InvalidLineDataError("optional", 13, pieces)
    point1 = [float(value) for value in pieces[1:4]]
    point2 = [float(value) for value in pieces[4:7]]
    point3 = [float(value) for value in pieces[7:10]]
    point4 = [float(value) for value in pieces[10:13]]
    return OptionalLine(
        _colour(pieces),
        Vector(*point1),
        Vector(*point2),
        Vector(*point3),
        Vector(*point4),
    )


HANDLERS: dict[str, LineHandler] = {
    "0": _comment_or_meta,
    "1": _sub_file,
    "2": _line,
    "3": _triangle,
    "4": _quadrilateral,
    "5": _optional_line,
}


class Part:
    """Contains data from an LDraw part file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._category: str | None = None
        self._description: str | None = None

    @property
    def lines(self) -> Iterator[str]:
        """Yield lines from the part file."""
        with self.path.open("r", encoding="utf-8") as file:
            yield from file

    @property
    def objects(self) -> Iterator[ParsedObject]:
        """Load objects from the part file."""
        for number, line in enumerate(self.lines):
            pieces = line.split()
            if not pieces:
                continue
            try:
                handler = HANDLERS[pieces[0]]
            except KeyError as exc:
                message = (
                    f"Unknown command ({pieces[0]}) in {self.path} at line {number}"
                )
                raise PartError(message) from exc
            try:
                yield handler(pieces[1:])
            except PartError as parse_error:
                message = f"{parse_error.message} in {self.path} at line {number}"
                raise PartError(message) from parse_error

    @property
    def description(self) -> str:
        """Get the description of the part from the first line of the file."""
        if self._description is None:
            self._description = " ".join(next(self.lines).split()[1:])
        return self._description

    @property
    def category(self) -> str | None:
        """Get the category of the part from CATEGORY meta command."""
        if self._category is None:
            for obj in self.objects:
                if not isinstance(obj, Comment | MetaCommand):
                    self._category = None
                    break
                if isinstance(obj, MetaCommand) and obj.type == "CATEGORY":
                    self._category = obj.text
                    break

        return self._category
