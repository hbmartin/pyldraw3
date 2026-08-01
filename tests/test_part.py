"""Tests for part file line parsing."""

from pathlib import Path

import pytest

from ldraw.colour import Colour
from ldraw.errors import (
    EmptyPartFileError,
    InvalidColourValueError,
    InvalidLineDataError,
    InvalidNumericValueError,
    PartError,
    UnknownCommandError,
)
from ldraw.geometry import Vector
from ldraw.lines import (
    Comment,
    Line,
    MetaCommand,
    OptionalLine,
    Quadrilateral,
    Triangle,
)
from ldraw.part import HANDLERS, ParsedObject, Part, colour_from_str, parse_ldraw_line
from ldraw.pieces import Piece


@pytest.mark.parametrize(
    ("line_type", "fields"),
    [
        ("1", "16 x 0 0 1 0 0 0 1 0 0 0 1 3001.dat"),
        ("2", "16 0 0 zero 1 1 1"),
        ("3", "16 0 0 0 1 1 1 2 2 bad"),
        ("4", "16 0 0 0 1 1 1 2 2 2 3 3 bad"),
        ("5", "16 0 0 0 1 1 1 2 2 2 3 3 bad"),
    ],
)
def test_handler_rejects_bad_float(line_type: str, fields: str) -> None:
    with pytest.raises(InvalidNumericValueError) as excinfo:
        HANDLERS[line_type](fields.split())

    assert isinstance(excinfo.value, PartError)
    assert isinstance(excinfo.value, ValueError)
    assert (
        "'x'" in str(excinfo.value)
        or "'zero'" in str(excinfo.value)
        or "'bad'" in str(excinfo.value)
    )


def test_parse_ldraw_line_blank_returns_none() -> None:
    assert parse_ldraw_line("") is None
    assert parse_ldraw_line("   \t") is None


def test_parse_ldraw_line_unknown_command() -> None:
    with pytest.raises(UnknownCommandError, match=r"Unknown command \(9\)"):
        parse_ldraw_line("9 16 0 0 0")


def test_parse_ldraw_line_each_type() -> None:
    assert parse_ldraw_line("0 A comment") == Comment("A comment")
    assert parse_ldraw_line("0 !CATEGORY Brick") == MetaCommand("CATEGORY", "Brick")

    piece = parse_ldraw_line("1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat")
    assert isinstance(piece, Piece)
    assert piece.part == "3001"
    assert piece.suffix == ".dat"

    line = parse_ldraw_line("2 16 0 0 0 1 1 1")
    assert isinstance(line, Line)
    assert line.points == [Vector(0, 0, 0), Vector(1, 1, 1)]

    triangle = parse_ldraw_line("3 16 0 0 0 1 1 1 2 2 2")
    assert isinstance(triangle, Triangle)
    assert triangle.point3 == Vector(2, 2, 2)

    quad = parse_ldraw_line("4 16 0 0 0 1 1 1 2 2 2 3 3 3")
    assert isinstance(quad, Quadrilateral)
    assert quad.point4 == Vector(3, 3, 3)

    optional = parse_ldraw_line("5 16 0 0 0 1 1 1 2 2 2 3 3 3")
    assert isinstance(optional, OptionalLine)
    assert optional.points == [
        Vector(0, 0, 0),
        Vector(1, 1, 1),
        Vector(2, 2, 2),
        Vector(3, 3, 3),
    ]


def test_sub_file_reference_with_spaces() -> None:
    piece = parse_ldraw_line("1 16 0 0 0 1 0 0 0 1 0 0 0 1 my body.ldr")
    assert isinstance(piece, Piece)
    assert piece.part == "my body"
    assert piece.suffix == ".ldr"


def test_sub_file_reference_without_extension() -> None:
    piece = parse_ldraw_line("1 16 0 0 0 1 0 0 0 1 0 0 0 1 submodel")
    assert isinstance(piece, Piece)
    assert piece.part == "submodel"
    assert piece.suffix == ""
    assert piece.to_ldraw().endswith(" submodel")


def test_sub_file_subdirectory_reference() -> None:
    piece = parse_ldraw_line("1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\3001s01.dat")
    assert isinstance(piece, Piece)
    assert piece.part == "s\\3001s01"
    assert piece.suffix == ".dat"


def test_objects_adds_path_and_line_context(tmp_path: Path) -> None:
    path = tmp_path / "bad.dat"
    path.write_text("0 Test Part\n2 16 0 0 x 1 1 1\n")

    with pytest.raises(
        InvalidNumericValueError,
        match=r"Invalid numeric value 'x' .* in .*bad\.dat at line 2",
    ):
        list(Part(path).objects)


def test_objects_wraps_field_count_error(tmp_path: Path) -> None:
    path = tmp_path / "short.dat"
    path.write_text("2 16 0 0\n")

    with pytest.raises(PartError, match=r"(?s)must have 7 parameters.* at line 1"):
        list(Part(path).objects)

    short_fields: list[str] = ["16", "0", "0"]
    with pytest.raises(InvalidLineDataError):
        HANDLERS["2"](short_fields)


def test_objects_unknown_command(tmp_path: Path) -> None:
    path = tmp_path / "unknown.dat"
    path.write_text("0 Test Part\n\n9 16 0 0 0\n")

    with pytest.raises(
        UnknownCommandError,
        match=r"Unknown command \(9\) in .*unknown\.dat at line 3",
    ):
        list(Part(path).objects)


def test_invalid_colour_token_raises_at_parse_time() -> None:
    with pytest.raises(InvalidColourValueError, match=r"'abc'") as excinfo:
        parse_ldraw_line("1 abc 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat")

    assert isinstance(excinfo.value, PartError)
    assert isinstance(excinfo.value, ValueError)


def test_short_direct_colour_token_is_rejected() -> None:
    with pytest.raises(InvalidColourValueError, match=r"'0x2FFF'"):
        parse_ldraw_line("2 0x2FFF 0 0 0 1 1 1")


def test_direct_colour_decimal_and_uppercase_prefix_parse() -> None:
    expected = Colour(rgb="#FF0000", alpha=255)
    assert colour_from_str("50266112") == expected
    assert colour_from_str("0X2FF0000") == expected
    assert colour_from_str("0x2FF0000") == expected
    assert colour_from_str("4") == 4


def test_part_file_with_utf8_bom_parses(tmp_path: Path) -> None:
    path = tmp_path / "bom.dat"
    path.write_bytes(b"\xef\xbb\xbf0 Test Part\n2 16 0 0 0 1 1 1\n")

    part = Part(path)
    assert part.description == "Test Part"
    objects = list(part.objects)
    assert isinstance(objects[0], Comment)
    assert isinstance(objects[1], Line)


def test_empty_part_file_description_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.dat"
    path.write_text("")

    with pytest.raises(EmptyPartFileError, match=r"empty"):
        _ = Part(path).description


def test_empty_part_file_category_and_keywords_degrade(tmp_path: Path) -> None:
    path = tmp_path / "empty.dat"
    path.write_text("")
    part = Part(path)

    assert part.category is None
    assert part.keywords == ()
    with pytest.raises(EmptyPartFileError, match=r"empty"):
        _ = part.metadata


def test_header_commands_accept_tab_separation(tmp_path: Path) -> None:
    path = tmp_path / "tabbed.dat"
    path.write_text(
        "0 Test Part\n"
        "0\t!CATEGORY Brick\n"
        "0\t!KEYWORDS Space, Castle\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n",
    )
    part = Part(path)

    assert part.category == "Brick"
    assert part.keywords == ("Space", "Castle")


def test_bare_zero_line_does_not_close_the_header(tmp_path: Path) -> None:
    path = tmp_path / "bare.dat"
    path.write_text(
        "0 Test Part\n0\n0 !CATEGORY Brick\n0 !KEYWORDS Space\n",
    )
    part = Part(path)

    assert part.category == "Brick"
    assert part.keywords == ("Space",)


def test_keywords_from_multiple_lines(tmp_path: Path) -> None:
    path = tmp_path / "keyworded.dat"
    path.write_text(
        "0 Test Part\n"
        "0 !CATEGORY Brick\n"
        "0 !KEYWORDS Space, Castle,  bar \n"
        "0 !KEYWORDS female stud, Space, rod\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n",
    )

    assert Part(path).keywords == ("Space", "Castle", "bar", "female stud", "rod")


def test_keywords_without_meta_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "plain.dat"
    path.write_text("0 Test Part\n0 !CATEGORY Brick\n")

    assert Part(path).keywords == ()


def test_keywords_ignores_lines_after_header(tmp_path: Path) -> None:
    path = tmp_path / "late.dat"
    path.write_text(
        "0 Test Part\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n0 !KEYWORDS too late\n",
    )

    assert Part(path).keywords == ()


def test_category_and_keywords_share_header_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "keyworded.dat"
    path.write_text(
        "0 Test Part\n"
        "0 !CATEGORY Brick\n"
        "0 !KEYWORDS Space, Castle\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n",
    )
    parse_count = 0
    original_parse = parse_ldraw_line

    def counting_parse(line: str) -> ParsedObject | None:
        nonlocal parse_count
        parse_count += 1
        return original_parse(line)

    monkeypatch.setattr("ldraw.part.parse_ldraw_line", counting_parse)

    part = Part(path)

    assert part.category == "Brick"
    assert part.keywords == ("Space", "Castle")
    # Structured header parsing is shared; only the first relationship line is
    # parsed so alias/moved targets can be retained.
    assert parse_count == 1


def test_objects_parses_valid_lines(tmp_path: Path) -> None:
    path = tmp_path / "good.dat"
    path.write_text(
        "0 Test Part\n"
        "0 !CATEGORY Brick\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        "2 16 0 0 0 1 1 1\n"
        "3 16 0 0 0 1 1 1 2 2 2\n"
        "4 16 0 0 0 1 1 1 2 2 2 3 3 3\n"
        "5 16 0 0 0 1 1 1 2 2 2 3 3 3\n",
    )

    objects = list(Part(path).objects)

    assert [type(obj) for obj in objects] == [
        Comment,
        MetaCommand,
        Piece,
        Line,
        Triangle,
        Quadrilateral,
        OptionalLine,
    ]
