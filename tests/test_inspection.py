"""Tests for model geometry inspection and attribution diagnostics."""

from pathlib import Path

import pytest

from ldraw.geometry import Matrix, Vector
from ldraw.inspection import bounds_gap, inspect_model
from ldraw.lines import Comment
from ldraw.model import Model
from ldraw.part_geometry_types import BoundingBox
from ldraw.parts import Parts
from ldraw.pieces import Piece


@pytest.fixture
def inspection_parts(tmp_path: Path) -> Parts:
    ldraw_dir = tmp_path / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (ldraw_dir / "parts.lst").write_text(
        "box.dat                        Inspection Box\n"
        "connector.dat                  Stud Connector\n"
        "empty.dat                      Empty Inspection Part\n"
        "receiver.dat                   Stud Receptacle\n",
        encoding="utf-8",
    )
    (ldraw_dir / "p.lst").write_text(
        "stud.dat                       Stud\n"
        "stud4.dat                      Stud Tube Open\n",
        encoding="utf-8",
    )
    primitive_dir = ldraw_dir / "p"
    primitive_dir.mkdir()
    (primitive_dir / "stud.dat").write_text(
        "0 Stud\n2 24 -1 0 0 1 0 0\n",
        encoding="utf-8",
    )
    (primitive_dir / "stud4.dat").write_text(
        "0 Stud Tube Open\n2 24 0 0 -1 0 0 1\n",
        encoding="utf-8",
    )
    (parts_dir / "box.dat").write_text(
        "0 Inspection Box\n4 16 -5 0 -5 5 0 -5 5 10 5 -5 10 5\n",
        encoding="utf-8",
    )
    (parts_dir / "empty.dat").write_text(
        "0 Empty Inspection Part\n",
        encoding="utf-8",
    )
    (parts_dir / "connector.dat").write_text(
        "0 Stud Connector\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n",
        encoding="utf-8",
    )
    (parts_dir / "receiver.dat").write_text(
        "0 Stud Receptacle\n1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud4.dat\n",
        encoding="utf-8",
    )
    return Parts(ldraw_dir / "parts.lst")


def test_repeated_submodels_have_distinct_page_and_path_attribution(
    inspection_parts: Parts,
) -> None:
    module = Model(
        name="module.ldr",
        objects=[Comment("// PDF_PAGE 002"), Piece.place("box")],
    )
    root = Model(
        name="main.mpd",
        objects=[
            Comment("// PDF_PAGE 010"),
            Piece.place("module", suffix=".ldr"),
            Comment("// PDF_PAGE 020"),
            Piece.place("module", position=Vector(100, 0, 0), suffix=".ldr"),
        ],
        submodels={"module.ldr": module},
    )

    inspection = inspect_model(root, inspection_parts)

    assert inspection.occurrence_count == 2
    assert inspection.bounds == BoundingBox(
        min=Vector(-5, 0, -5),
        max=Vector(105, 10, 5),
    )
    first, second = inspection.occurrences
    assert first.index == 0
    assert second.index == 1
    assert first.attribution.model_path == ("main.mpd", "module.ldr")
    assert first.attribution.reference_path == ("module.ldr", "box.dat")
    assert first.attribution.page_path == (10, 2)
    assert first.attribution.installation_page == 10
    assert first.attribution.source_page == 2
    assert second.attribution.page_path == (20, 2)
    assert first.occurrence.path[0].piece is not second.occurrence.path[0].piece
    assert first.occurrence.path[-1].piece is second.occurrence.path[-1].piece


def test_custom_page_prefix_and_skipped_geometry_are_reported(
    inspection_parts: Parts,
) -> None:
    model = Model(
        name="model.ldr",
        objects=[
            Comment("SOURCE_PAGE 7"),
            Piece.place("empty"),
            Piece.place("box", position=Vector(20, 0, 0)),
        ],
    )

    inspection = inspect_model(
        model,
        inspection_parts,
        page_marker_prefix="SOURCE_PAGE ",
    )

    assert inspection.occurrence_count == 2
    assert len(inspection.occurrences) == 1
    (skipped,) = inspection.skipped_geometry
    assert skipped.attribution.source_page == 7
    assert skipped.attribution.occurrence.part_code == "empty"
    assert "no drawable geometry" in skipped.reason


def test_contact_gaps_can_exclude_future_installation_pages(
    inspection_parts: Parts,
) -> None:
    model = Model(
        name="model.ldr",
        objects=[
            Comment("// PDF_PAGE 001"),
            Piece.place("box"),
            Comment("// PDF_PAGE 002"),
            Piece.place("box", position=Vector(100, 0, 0)),
            Comment("// PDF_PAGE 003"),
            Piece.place("box", position=Vector(110, 0, 0)),
        ],
    )
    inspection = inspect_model(model, inspection_parts)

    (unrestricted_gap,) = inspection.contact_gaps(minimum_gap=50)
    assert unrestricted_gap.subject.index == 0
    assert unrestricted_gap.nearest.index == 1

    (chronological_gap,) = inspection.contact_gaps(
        minimum_gap=50,
        chronological=True,
    )
    assert chronological_gap.subject.index == 1
    assert chronological_gap.nearest.index == 0
    assert chronological_gap.gap.axes == Vector(90, 0, 0)
    assert chronological_gap.gap.distance == 90


def test_bounds_gap_reports_axis_separation_and_intersection() -> None:
    origin = BoundingBox(min=Vector(0, 0, 0), max=Vector(10, 10, 10))
    diagonal = BoundingBox(min=Vector(13, 14, 0), max=Vector(20, 20, 10))

    separated = bounds_gap(origin, diagonal)
    assert separated.axes == Vector(3, 4, 0)
    assert separated.distance == 5
    assert not separated.intersects

    touching = bounds_gap(
        origin,
        BoundingBox(min=Vector(10, 2, 2), max=Vector(12, 4, 4)),
    )
    assert touching.distance == 0
    assert touching.intersects


def test_stud_contacts_match_stud_base_and_probe_against_supported_part(
    inspection_parts: Parts,
) -> None:
    inspection = inspect_model(
        Model(
            objects=[
                Piece.place("connector"),
                Piece.place("box", position=Vector(0, -10, 0)),
            ],
        ),
        inspection_parts,
    )

    (contact,) = inspection.stud_contacts()
    assert contact.stud_occurrence.index == 0
    assert contact.supported_occurrence.index == 1
    assert contact.stud.name == "stud"
    assert contact.position == Vector(0, 0, 0)

    with pytest.raises(ValueError, match="tolerance"):
        inspection.stud_contacts(tolerance=-1)
    with pytest.raises(ValueError, match="probe_distance"):
        inspection.stud_contacts(probe_distance=0)


def test_empty_page_prefix_disables_page_attribution(
    inspection_parts: Parts,
) -> None:
    model = Model(
        objects=[Comment("// PDF_PAGE 009"), Piece.place("box")],
    )

    (occurrence,) = inspect_model(
        model,
        inspection_parts,
        page_marker_prefix="",
    ).occurrences

    assert occurrence.attribution.page_path == (None,)


def test_invalid_page_markers_are_ignored_and_empty_models_have_no_bounds(
    inspection_parts: Parts,
) -> None:
    model = Model(
        objects=[
            Comment("unrelated comment"),
            Comment("// PDF_PAGE nope"),
            Piece.place("box"),
        ],
    )

    (occurrence,) = inspect_model(model, inspection_parts).occurrences
    assert occurrence.attribution.source_page is None

    empty = inspect_model(Model(), inspection_parts)
    assert empty.bounds is None
    assert empty.occurrences == ()


def test_stud_contact_diagnostics_reject_receptacles_gaps_and_zero_axes(
    inspection_parts: Parts,
) -> None:
    receptacle = inspect_model(
        Model(
            objects=[
                Piece.place("receiver"),
                Piece.place("box", position=Vector(0, -10, 0)),
            ],
        ),
        inspection_parts,
    )
    assert receptacle.stud_contacts() == ()

    separated = inspect_model(
        Model(
            objects=[
                Piece.place("connector"),
                Piece.place("box", position=Vector(20, -10, 0)),
            ],
        ),
        inspection_parts,
    )
    assert separated.stud_contacts() == ()

    zero_axis = inspect_model(
        Model(
            objects=[
                Piece.place(
                    "connector",
                    matrix=Matrix([[0, 0, 0], [0, 0, 0], [0, 0, 0]]),
                ),
                Piece.place("box", position=Vector(0, -10, 0)),
            ],
        ),
        inspection_parts,
    )
    assert zero_axis.stud_contacts() == ()


def test_negative_contact_gap_threshold_is_rejected(
    inspection_parts: Parts,
) -> None:
    inspection = inspect_model(
        Model(objects=[Piece.place("box")]),
        inspection_parts,
    )

    with pytest.raises(ValueError, match="non-negative"):
        inspection.contact_gaps(minimum_gap=-1)
