"""Tests for reading and writing whole model files."""

from pathlib import Path

import pytest

from ldraw.errors import (
    DuplicateSubmodelError,
    InvalidNumericValueError,
    MisplacedNofileError,
    StructuralCommentError,
    SubmodelNameRequiredError,
)
from ldraw.geometry import Identity, Vector
from ldraw.lines import Comment, MetaCommand
from ldraw.model import Model, parse_model, read_model
from ldraw.pieces import Piece

MODELS_DIR = Path(__file__).resolve().parent / "models"


def test_read_simple_ldr() -> None:
    model = read_model(MODELS_DIR / "simple.ldr")

    assert model.name == "simple.ldr"
    assert model.submodels == {}
    assert model.description == "Simple Test Model"
    assert model.header_name == "simple.ldr"
    assert model.author == "pyldraw3 tests"
    assert model.ldraw_org == "Model"
    assert model.license == "Licensed under CC BY 4.0"
    assert model.bfc == "CERTIFY CCW"
    assert len(model.pieces) == 3
    assert model.pieces[0].part == "3001"
    assert model.pieces[2].colour.rgb == "#FF0000"


def test_simple_ldr_round_trips() -> None:
    model = read_model(MODELS_DIR / "simple.ldr")
    text = (MODELS_DIR / "simple.ldr").read_text()

    assert model.to_ldraw() == text.rstrip("\n")
    assert parse_model(model.to_ldraw()).to_ldraw() == model.to_ldraw()


def test_read_mpd_sections() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    assert model.name == "main.ldr"
    assert model.description == "Car"
    assert sorted(model.submodels) == ["car body.ldr", "wheels.ldr"]
    assert len(model.pieces) == 3


def test_mpd_submodel_resolution_is_case_insensitive() -> None:
    model = read_model(MODELS_DIR / "car.mpd")
    body_ref, wheels_ref, brick = model.pieces

    body = model.submodel_for(body_ref)
    assert body is not None
    assert body.description == "Car Body Submodel"

    wheels = model.submodel_for(wheels_ref)
    assert wheels is not None
    assert wheels.description == "Wheels Submodel"

    assert model.submodel_for(brick) is None


def test_submodel_for_self_reference() -> None:
    piece = Piece(16, Vector(0, 0, 0), Identity(), "main", suffix=".LDR")
    model = Model(name="main.ldr", objects=[piece])

    assert model.submodel_for(piece) is model


def test_mpd_round_trips() -> None:
    model = read_model(MODELS_DIR / "car.mpd")
    text = model.to_ldraw()

    assert text.startswith("0 FILE main.ldr\n")
    assert "0 FILE car body.ldr" in text
    assert text.count("0 NOFILE") == 3
    assert "ignored between sections" not in text
    assert parse_model(text).to_ldraw() == text


def test_mpd_junk_after_nofile_is_dropped() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    for submodel in model.submodels.values():
        for obj in submodel.objects:
            assert obj != Comment("ignored between sections")


def test_preamble_before_first_file_prepends_to_root() -> None:
    model = parse_model("0 stray comment\n0 FILE a.ldr\n0 Section A\n")

    assert model.name == "a.ldr"
    assert model.objects[0] == Comment("stray comment")
    assert model.objects[1] == Comment("Section A")


def test_empty_document() -> None:
    model = parse_model("")

    assert model.objects == []
    assert model.to_ldraw() == ""
    assert model.description is None
    assert model.header_name is None
    assert model.author is None
    assert model.ldraw_org is None
    assert model.license is None
    assert model.bfc is None


def test_header_stops_at_first_non_comment() -> None:
    model = parse_model(
        "0 Description\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n0 Author: too late\n",
    )

    assert model.author is None
    assert model.description == "Description"


def test_description_none_when_first_object_not_comment() -> None:
    model = parse_model("1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat")

    assert model.description is None
    assert isinstance(model.objects[0], Piece)


def test_missing_nofile_section_ends_at_next_file() -> None:
    model = parse_model(
        "0 FILE a.ldr\n0 Section A\n0 FILE b.ldr\n0 Section B\n",
    )

    assert model.objects == [Comment("Section A")]
    assert model.submodels["b.ldr"].objects == [Comment("Section B")]


def test_duplicate_file_section_raises() -> None:
    with pytest.raises(DuplicateSubmodelError, match=r"A\.LDR"):
        parse_model("0 FILE a.ldr\n0 NOFILE\n0 FILE A.LDR\n")


def test_unnamed_model_with_submodels_cannot_serialize() -> None:
    model = Model(objects=[], submodels={"sub.ldr": Model(name="sub.ldr")})

    with pytest.raises(SubmodelNameRequiredError):
        model.to_ldraw()


def test_parse_error_carries_source_and_line() -> None:
    text = "0 FILE a.ldr\n0 ok\n2 16 0 0 x 1 1 1\n"

    with pytest.raises(
        InvalidNumericValueError,
        match=r"'x' .* in model\.mpd at line 3",
    ):
        parse_model(text, source="model.mpd")

    with pytest.raises(InvalidNumericValueError, match=r"'x' .* in <string> at line 3"):
        parse_model(text)


def test_stray_nofile_raises() -> None:
    with pytest.raises(MisplacedNofileError, match=r"in m\.ldr at line 2"):
        parse_model("0 a\n0 NOFILE\n0 lost\n", source="m.ldr")

    with pytest.raises(MisplacedNofileError, match=r"in <string> at line 1"):
        parse_model("0 NOFILE\n0 FILE a.ldr\n")


def test_structural_comments_rejected_at_serialization() -> None:
    for text in ("NOFILE", "FILE other.ldr", "file x"):
        with pytest.raises(StructuralCommentError, match=r"section boundary"):
            Model(objects=[Comment(text)]).to_ldraw()

    root = Model(name="main.ldr")
    sub = Model(name="sub.ldr", objects=[Comment("NOFILE")])
    root.add_submodel(sub)
    with pytest.raises(StructuralCommentError):
        root.to_ldraw()

    assert Model(objects=[Comment("FILENAME: x")]).to_ldraw() == "0 FILENAME: x"


def test_description_ignores_managed_headers() -> None:
    assert parse_model("0 Name: a.ldr\n").description is None
    assert parse_model("0 Author: x\n").description is None
    assert parse_model("0 BFC CERTIFY CCW\n").description is None
    assert parse_model("0 A real description\n").description == "A real description"


def test_model_equality_and_hash_are_identity() -> None:
    text = "0 Model\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
    first = parse_model(text)
    second = parse_model(text)

    assert first != second
    assert first == first  # noqa: PLR0124 - identity equality is the contract
    assert isinstance(hash(first), int)
    assert first.to_ldraw() == second.to_ldraw()

    occurrence = next(first.iter_occurrences())
    assert isinstance(hash(occurrence), int)


def test_source_line_for_is_identity_based() -> None:
    model = parse_model("0 Model\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")
    piece = model.pieces[0]

    assert model.source_line_for(piece) == 2

    equal_valued = Piece.place("3001", colour=4)
    assert model.source_line_for(equal_valued) is None

    model.objects.remove(piece)
    del piece
    fresh = Piece.place("3005", colour=0)
    assert model.source_line_for(fresh) is None


def test_crlf_and_bom_are_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "crlf.ldr"
    path.write_bytes(b"\xef\xbb\xbf0 Description\r\n0 Name: crlf.ldr\r\n")

    model = read_model(path)

    assert model.description == "Description"
    assert model.header_name == "crlf.ldr"


def test_save_and_read_round_trip(tmp_path: Path) -> None:
    original = read_model(MODELS_DIR / "car.mpd")
    path = tmp_path / "saved.mpd"

    original.save(path)
    reread = read_model(path)

    assert reread.to_ldraw() == original.to_ldraw()
    assert path.read_text().endswith("0 NOFILE\n")


def test_save_empty_model(tmp_path: Path) -> None:
    path = tmp_path / "empty.ldr"

    Model().save(path)

    assert path.read_text() == ""


def test_empty_submodel_section_round_trips() -> None:
    model = parse_model("0 FILE a.ldr\n0 NOFILE\n0 FILE b.ldr\n0 NOFILE\n")

    assert model.submodels["b.ldr"].objects == []
    assert model.to_ldraw() == "0 FILE a.ldr\n0 NOFILE\n0 FILE b.ldr\n0 NOFILE"


def test_str_matches_to_ldraw() -> None:
    model = parse_model("0 hello")

    assert str(model) == model.to_ldraw() == "0 hello"


def test_mid_body_meta_preserved_in_order() -> None:
    text = (
        "0 Description\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.DAT\n"
        "0 STEP\n"
        "0 !HISTORY 2026-07-07 [tests] created\n"
        "1 16 0 -24 0 1 0 0 0 1 0 0 0 1 3001.DAT\n"
    )
    model = parse_model(text)

    assert model.objects[2] == Comment("STEP")
    assert model.objects[3] == MetaCommand(
        "HISTORY",
        "2026-07-07 [tests] created",
    )
    assert model.to_ldraw() == text.rstrip("\n")


def test_mixed_case_references_round_trip_byte_identically() -> None:
    text = (
        "0 Name: main.ldr\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3040b.dat\n"
        "1 4 0 0 0 1 0 0 0 1 0 0 0 1 s\\3040s01.dat\n"
        "1 14 0 0 0 1 0 0 0 1 0 0 0 1 LEGACY.DAT"
    )

    assert parse_model(text).to_ldraw() == text


def test_submodel_reference_case_matches_its_file_section() -> None:
    root = Model(name="main.ldr")
    sub = Model(name="wing.ldr", objects=[Piece.place("3001")])

    root.add_submodel(sub)

    text = root.to_ldraw()
    assert "1 16 0 0 0 1 0 0 0 1 0 0 0 1 wing.ldr" in text
    assert "0 FILE wing.ldr" in text
