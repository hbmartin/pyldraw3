"""Tests for parts.lst generation."""

from pathlib import Path

from ldraw.generate import generate_parts_lst
from ldraw.parts import Parts

BRICK_2X4 = "0 Brick  2 x  4\n0 Name: 3001.dat\n"
BRICK_2X2_CRLF = "0 Brick  2 x  2\r\n0 Name: 3003.dat\r\n"


def test_generate_parts_lst_round_trip(tmp_path: Path) -> None:
    parts_dir = tmp_path / "ldraw" / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text(BRICK_2X4)
    (parts_dir / "3003.dat").write_text(BRICK_2X2_CRLF)

    generate_parts_lst(mode="description", version_dir=tmp_path)

    parts_lst = tmp_path / "ldraw" / "parts.lst"
    raw = parts_lst.read_bytes()
    # header newlines must be stripped, else entries turn into blank lines
    assert b"\n\r\n" not in raw
    lines = raw.decode("utf-8").split("\r\n")
    assert len(lines) == 2
    assert lines[0].startswith("3003.dat")
    assert lines[0].endswith("Brick  2 x  2")

    parts = Parts(parts_lst)
    parts.load()
    assert parts.by_name == {"Brick  2 x  4": "3001", "Brick  2 x  2": "3003"}
