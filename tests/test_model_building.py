"""Tests for the Model building and query API."""

from pathlib import Path

import pytest

from ldraw.colour import Colour
from ldraw.errors import (
    DuplicateSubmodelError,
    SubmodelCycleError,
    SubmodelNameRequiredError,
    UnknownSubmodelError,
)
from ldraw.figure import Person
from ldraw.geometry import Identity, Vector
from ldraw.lines import Comment, MetaCommand
from ldraw.model import Model, parse_model, read_model
from ldraw.pieces import Group, Piece

MODELS_DIR = Path("tests/models")


def brick(part: str = "3001", colour: Colour | int = 4) -> Piece:
    return Piece.place(part, colour=colour)


def test_add_appends_mixed_objects_in_order() -> None:
    model = Model()
    comment = Comment("A comment")
    meta = MetaCommand("KEYWORDS", "test")
    piece = brick()

    model.add(comment, meta)
    model.add(piece)

    assert model.objects == [comment, meta, piece]
    assert parse_model(model.to_ldraw()).to_ldraw() == model.to_ldraw()


def test_add_group_applies_transform_at_serialization() -> None:
    group = Group(position=Vector(10, 0, 0))
    piece = Piece(15, Vector(40, 0, 0), Identity(), "3001", group)
    model = Model()

    model.add_group(group)

    assert model.pieces == [piece]
    assert model.to_ldraw() == "1 15 50 0 0 1 0 0 0 1 0 0 0 1 3001.DAT"


def test_add_group_captures_all_figure_pieces() -> None:
    group = Group()
    figure = Person(group=group)
    figure.head(colour=14)
    figure.torso(colour=4)
    figure.hips(colour=1)
    model = Model()

    model.add_group(group)

    assert len(model.pieces) == len(group.pieces) == 3


def test_from_pieces_sets_headers_and_round_trips() -> None:
    model = Model.from_pieces(
        [brick(), brick(part="3005", colour=0)],
        name="built.ldr",
        description="Built Model",
        author="pyldraw3 tests",
    )

    assert model.name == "built.ldr"
    assert model.description == "Built Model"
    assert model.author == "pyldraw3 tests"
    assert len(model.pieces) == 2
    assert model.to_ldraw().splitlines()[:2] == [
        "0 Built Model",
        "0 Author: pyldraw3 tests",
    ]
    assert parse_model(model.to_ldraw()).to_ldraw() == model.to_ldraw()


def test_from_pieces_without_headers() -> None:
    model = Model.from_pieces([brick()])

    assert model.description is None
    assert model.author is None
    assert len(model.objects) == 1


def test_set_header_inserts_into_empty_model_in_canonical_order() -> None:
    model = Model()

    model.set_header(author="someone", name="a.ldr", description="A Model")

    assert model.objects == [
        Comment("A Model"),
        Comment("Name: a.ldr"),
        Comment("Author: someone"),
    ]


def test_set_header_replaces_existing_values() -> None:
    model = parse_model("0 Old\n0 Name: old.ldr\n0 Author: old author\n")

    model.set_header(description="New", name="new.ldr", author="new author")

    assert model.objects == [
        Comment("New"),
        Comment("Name: new.ldr"),
        Comment("Author: new author"),
    ]


def test_set_header_description_does_not_clobber_name_comment() -> None:
    model = parse_model("0 Name: a.ldr\n")

    model.set_header(description="A Model")

    assert model.objects == [Comment("A Model"), Comment("Name: a.ldr")]


def test_set_header_author_lands_after_existing_name() -> None:
    model = parse_model("0 A Model\n0 Name: a.ldr\n")

    model.set_header(author="someone")

    assert model.objects == [
        Comment("A Model"),
        Comment("Name: a.ldr"),
        Comment("Author: someone"),
    ]


def test_set_header_skips_non_header_objects() -> None:
    model = Model(objects=[brick()])

    model.set_header(name="a.ldr")

    assert model.objects[0] == Comment("Name: a.ldr")
    assert isinstance(model.objects[1], Piece)


def test_add_submodel_round_trips_through_mpd() -> None:
    root = Model(name="main.ldr", objects=[Comment("Main")])
    body = Model(name="car body.ldr", objects=[Comment("Body"), brick()])

    piece = root.add_submodel(body, colour=14, position=Vector(0, -24, 0))

    assert piece.reference == "CAR BODY.LDR"
    assert root.submodel_for(piece) is body
    reparsed = parse_model(root.to_ldraw())
    assert sorted(reparsed.submodels) == ["car body.ldr"]
    assert reparsed.to_ldraw() == root.to_ldraw()


def test_add_submodel_defaults_and_extensionless_name() -> None:
    root = Model(name="main.ldr")
    sub = Model(name="body", objects=[brick()])

    piece = root.add_submodel(sub)

    assert piece.reference == "BODY"
    assert piece.colour == Colour(code=16)
    assert piece.position == Vector(0, 0, 0)
    assert root.submodel_for(piece) is sub


def test_add_submodel_requires_a_name() -> None:
    root = Model(name="main.ldr")

    with pytest.raises(SubmodelNameRequiredError):
        root.add_submodel(Model())


def test_add_submodel_rejects_duplicates_case_insensitively() -> None:
    root = Model(name="main.ldr")
    root.add_submodel(Model(name="body.ldr"))

    with pytest.raises(DuplicateSubmodelError):
        root.add_submodel(Model(name="BODY.LDR"))
    with pytest.raises(DuplicateSubmodelError):
        root.add_submodel(Model(name="Main.ldr"))


def test_add_submodel_hoists_nested_submodels() -> None:
    inner = Model(name="wheel.ldr", objects=[brick(part="3005")])
    middle = Model(name="axle.ldr")
    middle.add_submodel(inner)
    root = Model(name="main.ldr")

    root.add_submodel(middle)

    assert sorted(root.submodels) == ["axle.ldr", "wheel.ldr"]
    reparsed = parse_model(root.to_ldraw())
    assert reparsed.to_ldraw() == root.to_ldraw()


def test_add_submodel_rejects_hoisted_duplicates() -> None:
    middle = Model(name="axle.ldr")
    middle.add_submodel(Model(name="wheel.ldr"))
    root = Model(name="main.ldr")
    root.add_submodel(Model(name="wheel.ldr"))

    with pytest.raises(DuplicateSubmodelError):
        root.add_submodel(middle)
    assert "axle.ldr" not in root.submodels


def test_iter_pieces_expands_submodel_references() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    leaves = [(piece.part, piece.colour.code) for piece in model.iter_pieces()]

    assert leaves == [("3005", 4), ("3005", 0), ("3001", 14)]


def test_iter_pieces_counts_repeated_references_twice() -> None:
    root = Model(name="main.ldr")
    wheels = Model(name="wheels.ldr", objects=[brick(part="3005", colour=0)])
    root.add_submodel(wheels)
    root.add(Piece.place("wheels", suffix=".LDR"))

    assert len(list(root.iter_pieces())) == 2


def test_iter_pieces_raises_on_self_reference() -> None:
    piece = Piece(16, Vector(0, 0, 0), Identity(), "main", suffix=".LDR")
    model = Model(name="main.ldr", objects=[piece])

    with pytest.raises(SubmodelCycleError):
        list(model.iter_pieces())


def test_iter_pieces_raises_on_mutual_cycle() -> None:
    a = Model(name="a.ldr", objects=[Piece.place("b", suffix=".LDR")])
    b = Model(name="b.ldr", objects=[Piece.place("a", suffix=".LDR")])
    root = Model(
        name="main.ldr",
        objects=[Piece.place("a", suffix=".LDR")],
        submodels={"a.ldr": a, "b.ldr": b},
    )

    with pytest.raises(SubmodelCycleError):
        list(root.iter_pieces())


def nested_mpd_root() -> Model:
    inner = Model(name="inner.ldr", objects=[brick(part="3005", colour=0)])
    outer = Model(
        name="outer.ldr",
        objects=[brick(part="3001", colour=4), Piece.place("inner", suffix=".LDR")],
    )
    return Model(
        name="main.ldr",
        objects=[Piece.place("outer", suffix=".LDR")],
        submodels={"outer.ldr": outer, "inner.ldr": inner},
    )


def test_bare_submodel_iteration_treats_nested_references_as_leaves() -> None:
    root = nested_mpd_root()
    bare = root.submodels["outer.ldr"]

    leaves = sorted(piece.reference for piece in bare.iter_pieces())

    assert leaves == ["3001.DAT", "INNER.LDR"]


def test_submodel_view_expands_nested_references_against_the_root() -> None:
    root = nested_mpd_root()

    view = root.submodel_view("outer.ldr")
    leaves = sorted(piece.reference for piece in view.iter_pieces())

    assert leaves == ["3001.DAT", "3005.DAT"]


def test_submodel_view_bill_of_materials_counts_nested_leaves() -> None:
    root = nested_mpd_root()

    rows = root.submodel_view("outer.ldr").bill_of_materials()

    assert [(row.part, row.quantity) for row in rows] == [("3001", 1), ("3005", 1)]


def test_submodel_view_resolves_names_case_insensitively() -> None:
    root = nested_mpd_root()

    assert root.submodel_view("OUTER.LDR").name == "outer.ldr"


def test_submodel_view_of_the_root_name_is_the_root() -> None:
    root = nested_mpd_root()

    assert root.submodel_view("Main.ldr") is root


def test_submodel_view_unknown_name_raises() -> None:
    root = nested_mpd_root()

    with pytest.raises(UnknownSubmodelError):
        root.submodel_view("ghost.ldr")


def test_iter_pieces_allows_diamond_references() -> None:
    shared = Model(name="shared.ldr", objects=[brick(part="3005")])
    left = Model(name="left.ldr", objects=[Piece.place("shared", suffix=".LDR")])
    right = Model(name="right.ldr", objects=[Piece.place("shared", suffix=".LDR")])
    root = Model(
        name="main.ldr",
        objects=[
            Piece.place("left", suffix=".LDR"),
            Piece.place("right", suffix=".LDR"),
        ],
        submodels={
            "left.ldr": left,
            "right.ldr": right,
            "shared.ldr": shared,
        },
    )

    assert len(list(root.iter_pieces())) == 2


def test_find_pieces_by_part_and_colour() -> None:
    red_brick = brick(part="3626B")
    black_plate = brick(part="3024", colour=0)
    model = Model(objects=[red_brick, black_plate])

    assert model.find_pieces(part="3626b") == [red_brick]
    assert model.find_pieces(part="9999") == []
    assert model.find_pieces(colour=0) == [black_plate]
    assert model.find_pieces(colour=Colour(code=4)) == [red_brick]
    assert model.find_pieces(part="3024", colour=0) == [black_plate]
    assert model.find_pieces(part="3024", colour=4) == []
    assert model.find_pieces() == [red_brick, black_plate]


def test_find_pieces_ignores_non_piece_objects() -> None:
    model = Model(objects=[Comment("A comment"), brick()])

    assert len(model.find_pieces()) == 1


def test_find_pieces_recursive() -> None:
    model = read_model(MODELS_DIR / "car.mpd")

    assert model.find_pieces(part="3005") == []
    recursive = model.find_pieces(part="3005", recursive=True)
    assert [piece.colour.code for piece in recursive] == [4, 0]
