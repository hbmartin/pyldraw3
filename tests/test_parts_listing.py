"""Listing-only lookups preserve the full loader's parsing and descriptions."""

from pathlib import Path

import pytest

from ldraw._parts_listing import PartsListing
from ldraw.parts import Parts


@pytest.mark.parametrize("reverse", [False, True])
def test_listing_descriptions_prefer_exact_case(
    tmp_path: Path, *, reverse: bool
) -> None:
    entries = ["Foo.dat  Uppercase\n", "foo.dat  Lowercase\n"]
    if reverse:
        entries.reverse()
    path = tmp_path / "parts.lst"
    path.write_text("".join(entries))
    for source in (Parts(parts_lst=path), PartsListing.read(path)):
        assert source.description_for("Foo") == "Uppercase"
        assert source.description_for("foo") == "Lowercase"
        assert source.description_for("FOO") == (
            "Uppercase" if reverse else "Lowercase"
        )
        assert source.description_for("unknown") is None


def test_listing_parser_is_shared_and_preserves_description_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "parts.lst"
    path.write_text(
        "\nmalformed listing line\n"
        "custom.v1.DAT  Minifig Torso  with .dat in description\n"
        "s\\Some.dat  =Alias Description\n"
    )
    full = Parts(parts_lst=path)
    listing = PartsListing.read(path)
    assert (
        full.by_code
        == listing.by_code
        == {
            "custom.v1": "Minifig Torso  with .dat in description",
            "s\\Some": "=Alias Description",
        }
    )
    assert listing.description_for("S/SOME") == "=Alias Description"
    assert full.description_for("S/SOME") == "=Alias Description"
    assert "skipping malformed line 2" in caplog.text
