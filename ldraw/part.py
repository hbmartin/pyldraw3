"""Part file parsing and processing functionality."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from ldraw.colour import Colour
from ldraw.errors import (
    InvalidLineDataError,
    InvalidNumericValueError,
    PartError,
    UnknownCommandError,
)
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


def _floats(line_type: str, values: list[str], line: list[str]) -> list[float]:
    """Parse numeric fields, naming the offending token on failure."""
    result: list[float] = []
    for value in values:
        try:
            result.append(float(value))
        except ValueError as exc:
            raise InvalidNumericValueError(
                line_type=line_type,
                token=value,
                line=line,
            ) from exc
    return result


def _split_reference(ref: str) -> tuple[str, str]:
    """Split a subfile reference into an uppercased stem and extension."""
    stem, dot, ext = ref.rpartition(".")
    if not dot:
        return ref.upper(), ""
    return stem.upper(), f".{ext.upper()}"


def _sub_file(pieces: list[str]) -> Piece:
    if len(pieces) < 14:
        raise InvalidLineDataError(line_type="subfile", size=14, line=pieces)
    values = _floats("subfile", pieces[1:13], pieces)
    rows = [values[3:6], values[6:9], values[9:12]]
    part, suffix = _split_reference(" ".join(pieces[13:]))
    return Piece(
        _colour(pieces),
        Vector(*values[:3]),
        Matrix(rows),
        part,
        suffix=suffix,
    )


def _line(pieces: list[str]) -> Line:
    if len(pieces) != 7:
        raise InvalidLineDataError(line_type="line", size=7, line=pieces)
    values = _floats("line", pieces[1:7], pieces)
    return Line(_colour(pieces), Vector(*values[:3]), Vector(*values[3:6]))


def _triangle(pieces: list[str]) -> Triangle:
    if len(pieces) != 10:
        raise InvalidLineDataError(line_type="triangle", size=10, line=pieces)
    values = _floats("triangle", pieces[1:10], pieces)
    return Triangle(
        _colour(pieces),
        Vector(*values[:3]),
        Vector(*values[3:6]),
        Vector(*values[6:9]),
    )


def _quadrilateral(pieces: list[str]) -> Quadrilateral:
    if len(pieces) != 13:
        raise InvalidLineDataError(
            line_type="quadrilateral",
            size=13,
            line=pieces,
        )
    values = _floats("quadrilateral", pieces[1:13], pieces)
    return Quadrilateral(
        _colour(pieces),
        Vector(*values[:3]),
        Vector(*values[3:6]),
        Vector(*values[6:9]),
        Vector(*values[9:12]),
    )


def _optional_line(pieces: list[str]) -> OptionalLine:
    if len(pieces) != 13:
        raise InvalidLineDataError(line_type="optional", size=13, line=pieces)
    values = _floats("optional", pieces[1:13], pieces)
    return OptionalLine(
        _colour(pieces),
        Vector(*values[:3]),
        Vector(*values[3:6]),
        Vector(*values[6:9]),
        Vector(*values[9:12]),
    )


HANDLERS: dict[str, LineHandler] = {
    "0": _comment_or_meta,
    "1": _sub_file,
    "2": _line,
    "3": _triangle,
    "4": _quadrilateral,
    "5": _optional_line,
}


def parse_ldraw_line(line: str) -> ParsedObject | None:
    """Parse a single LDraw line; return None for a blank line."""
    pieces = line.split()
    if not pieces:
        return None
    if (handler := HANDLERS.get(pieces[0])) is None:
        raise UnknownCommandError(pieces[0])
    return handler(pieces[1:])


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
        for number, line in enumerate(self.lines, start=1):
            try:
                parsed = parse_ldraw_line(line)
            except PartError as parse_error:
                message = f"{parse_error.message} in {self.path} at line {number}"
                raise PartError(message) from parse_error
            if parsed is not None:
                yield parsed

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
