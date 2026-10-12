"""Independent report cases for physical boundaries and semantic document reuse."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ldraw import (
    Coverage,
    Model,
    Parts,
    Piece,
    Vector,
    bom_report,
    inspect_model,
    parse_model,
)
from ldraw.assembly_validation import assembly_issues
from ldraw.cli import main
from ldraw.errors import SubmodelNameRequiredError
from ldraw.lines import Comment
from ldraw.model import parse_model_result

IDENTITY = "1 0 0 0 1 0 0 0 1"


def library(tmp_path):
    data = tmp_path / "library"
    (data / "parts").mkdir(parents=True)
    (data / "p").mkdir()
    (data / "parts" / "brick.dat").write_text(
        "0 Brick\n0 !LDRAW_ORG Part\n2 24 -10 0 -10 10 24 10\n"
    )
    (data / "parts" / "pair.dat").write_text(
        f"0 Pair\n0 !LDRAW_ORG Shortcut\n1 16 0 0 0 {IDENTITY} brick.dat\n"
        f"1 16 20 0 0 {IDENTITY} brick.dat\n"
    )
    (data / "p" / "stud.dat").write_text(
        "0 Stud\n0 !LDRAW_ORG Primitive\n2 24 -6 -4 -6 6 0 6\n"
    )
    return Parts.from_directory(data, cache=tmp_path / "cache")


def document():
    return parse_model(f"""0 FILE main.ldr
1 4 0 0 0 {IDENTITY} pair.dat
1 2 100 0 0 {IDENTITY} local.dat
0 NOFILE
0 FILE local.dat
0 Local Part
0 Author: Alice
0 !LICENSE Redistributable under CC BY 4.0 : see CAreadme.txt
0 !LDRAW_ORG Part
1 16 0 0 0 {IDENTITY} stud.dat
1 16 20 0 0 {IDENTITY} stud.dat
0 NOFILE
""")


def test_physical_bom_expands_shortcuts_stops_at_parts(tmp_path):
    parts = library(tmp_path)
    model = document()
    report = bom_report(model, parts=parts)
    assert [(row.part, row.colour_code, row.quantity) for row in report.rows] == [
        ("brick", 4, 2),
        ("local", 2, 1),
    ]
    assert report.coverage == Coverage.COMPLETE
    assert list(report.rows) == model.bill_of_materials(parts=parts)
    inspection = inspect_model(model, parts)
    assert inspection.occurrence_count == 3
    assert inspection.geometry_coverage == Coverage.COMPLETE
    assert parts.find_part(code="local") is None
    assert parts.with_embedded(model).part(code="local").metadata.author == "Alice"


def test_provisional_dat_boundary_keeps_known_counts(tmp_path):
    model = document()
    model.submodels["local.dat"].objects = [
        obj
        for obj in model.submodels["local.dat"].objects
        if not str(obj).startswith("0 !LDRAW_ORG")
    ]
    model.add(Piece.place("missing"))
    report = bom_report(model, parts=library(tmp_path))
    assert report.coverage == Coverage.PARTIAL
    assert {row.part for row in report.rows} == {"brick", "local", "missing"}
    assert set(report.provisional_rows) == {"local.dat", "missing.dat"}
    assert report.unresolved_contents == ("missing.dat",)


def test_physical_definition_resolves_ldr_geometry_dependencies(tmp_path):
    parts = library(tmp_path)
    (parts.library_root / "parts" / "Child.ldr").write_text(
        "0 Geometry\n2 24 0 0 0 3 5 7\n"
    )
    assert parts.part(code="Child.ldr").description == "Geometry"
    (parts.library_root / "parts" / "external.dat").write_text(
        f"0 External\n0 !LDRAW_ORG Part\n1 16 20 0 0 {IDENTITY} Child.ldr\n"
    )
    assert parts.geometry("external").bounds.max == Vector(23, 5, 7)
    model = parse_model(
        f"0 FILE main.ldr\n1 4 100 0 0 {IDENTITY} physical.dat\n"
        f"0 FILE physical.dat\n0 !LDRAW_ORG Part\n"
        f"1 16 20 0 0 {IDENTITY} child.ldr\n"
        "0 FILE child.ldr\n2 24 0 0 0 3 5 7\n"
    )
    result = inspect_model(model, parts)
    assert result.occurrence_count == 1
    assert result.geometry_coverage == Coverage.COMPLETE
    assert result.bounds.min == Vector(120, 0, 0)
    assert result.bounds.max == Vector(123, 5, 7)
    assert result.occurrences[0].connections == ()
    report = bom_report(model, parts=parts)
    assert [(row.part, row.quantity) for row in report.rows] == [("physical", 1)]
    measured = parts.with_embedded(model).measurements("physical")
    assert measured.body_bounds.max == Vector(23, 5, 7)


def test_alias_cycle_retains_sibling_counts(tmp_path):
    from ldraw import analyze_model

    parts = library(tmp_path)
    alias = parts.library_root / "parts" / "alias.dat"
    alias.write_text(
        f"0 Alias\n0 !LDRAW_ORG Part Alias\n1 16 0 0 0 {IDENTITY} brick.dat\n"
    )
    model = Model.from_pieces([Piece.place("alias", colour=4)])
    assert bom_report(model, parts=parts).rows[0].part == "brick"
    alias.write_text(
        f"0 Alias\n0 !LDRAW_ORG Part Alias\n1 16 0 0 0 {IDENTITY} alias.dat\n"
        f"1 16 0 0 0 {IDENTITY} brick.dat\n"
    )
    report = bom_report(model, parts=parts)
    assert report.rows[0].quantity == 1
    assert report.coverage == Coverage.PARTIAL
    assert report.unresolved_contents == ("alias.dat",)
    analysis = analyze_model(model, parts=parts)
    assert analysis.geometry_coverage == Coverage.PARTIAL
    assert analysis.total_occurrences is None
    assert len(analysis.diagnostics) == len(
        {item.code for item in analysis.diagnostics}
    )


def test_transformed_raw_geometry_has_no_physical_parts(tmp_path):
    model = parse_model(f"""0 FILE main.ldr
1 16 100 0 0 {IDENTITY} raw.ldr
1 16 200 0 0 {IDENTITY} raw.ldr
0 FILE raw.ldr
3 16 0 0 0 10 0 0 0 5 0
5 24 0 0 0 0 0 10 -999 -999 -999 999 999 999
""")
    result = inspect_model(model, library(tmp_path))
    assert result.occurrence_count == 0
    assert result.bounds.min.x == 100
    assert result.bounds.max.x == 210
    assert result.bounds.max.z == 10
    assert len(result.raw_geometry) == 4
    assert result.raw_geometry[2].path[0].piece_index == 1
    assert bom_report(model).rows == ()
    with pytest.warns(DeprecationWarning, match="deprecated"):
        assert result.complete == result.legacy_complete


def test_budget_reports_partial_work_and_cli_formats(tmp_path, capsys):
    parts = library(tmp_path)
    model = document()
    report = bom_report(model, parts=parts, occurrence_budget=1)
    assert report.processed_occurrences == 1
    assert report.total_occurrences is None
    assert report.coverage == Coverage.PARTIAL
    inspection = inspect_model(model, parts, occurrence_budget=0)
    assert inspection.geometry_coverage == Coverage.UNAVAILABLE
    assert inspection.occurrence_total is None
    path = tmp_path / "scene.mpd"
    model.save(path)
    assert (
        main(
            [
                "bom",
                str(path),
                "--library",
                str(parts.library_root),
                "--format",
                "json",
                "--detail",
                "full",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["rows"][0]["quantity"] == 2
    assert (
        main(
            [
                "bom",
                str(path),
                "--library",
                str(parts.library_root),
                "--occurrence-budget",
                "0",
                "--strict",
            ]
        )
        == 1
    )
    with pytest.raises(ValueError):
        bom_report(model, occurrence_budget=-1)
    with pytest.raises(ValueError):
        inspect_model(model, parts, occurrence_budget=-1)


def test_semantic_filename_spacing_newlines_and_single_mpd(tmp_path):
    model = parse_model(f"1 16 0 0 0 {IDENTITY} my  part.dat\n", name="root.ldr")
    assert model.pieces[0].reference == "my  part.dat"
    path = tmp_path / "scene.mpd"
    model.save(path, mpd=True, newline="\r\n")
    assert b"0 FILE root.ldr\r\n" in path.read_bytes()
    assert b"my  part.dat\r\n" in path.read_bytes()
    with pytest.raises(ValueError):
        model.save(path, newline="bad")
    model.save(path, atomic=False)
    assert b"\r" not in path.read_bytes()
    with pytest.raises(SubmodelNameRequiredError):
        Model().save(path, mpd=True)


def test_atomic_failure_preserves_destination(tmp_path, monkeypatch):
    path = tmp_path / "scene.ldr"
    path.write_text("original")

    def fail(self: Path, target: Path) -> None:
        message = "replacement failed"
        raise OSError(message)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        Model(objects=[Comment("replacement")]).save(path)
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_extraction_closure_and_attribution(tmp_path):
    model = document()
    result = model.extract("local.dat", namespace="copy-")
    assert result.model.name == "copy-local.dat"
    assert result.manifest[0].author == "Alice"
    assert result.manifest[0].license.startswith("Redistributable")
    result.model.objects.append(Comment("independent"))
    assert len(result.model.objects) != len(model.submodels["local.dat"].objects)
    with pytest.raises(ValueError, match="Unknown"):
        model.extract("absent.ldr")
    with pytest.raises(ValueError):
        model.extract("local.dat", namespace="../")
    cyclic = parse_model_result(
        f"0 FILE root.ldr\n1 16 0 0 0 {IDENTITY} child.ldr\n"
        f"0 FILE child.ldr\n1 16 0 0 0 {IDENTITY} root.ldr\n",
        tolerant=True,
    ).model
    with pytest.raises(ValueError, match="cycle"):
        cyclic.extract("root.ldr")


def test_assembly_checks_are_contextual_warnings(tmp_path):
    parts = library(tmp_path)
    model = parse_model(f"""0 FILE main.ldr
1 16 0 0 0 {IDENTITY} brick.dat
1 16 0 0 0 {IDENTITY} brick.dat
1 4 30 0 0 -1 0 0 0 1 0 0 0 1 brick.dat
1 4 50 0 0 {IDENTITY} stud.dat
3 24 0 0 0 0 0 0 0 0 0
4 4 0 0 0 10 0 0 10 0 10 0 1 10
0 BFC INVERTNEXT
0 FILE unused.ldr
0 Empty
""")
    issues = tuple(assembly_issues(model, parts=parts))
    codes = {item.code for item in issues}
    assert {
        "assembly.duplicate_world_placement",
        "assembly.mirrored_placement",
        "assembly.unresolved_inherited_colour",
        "assembly.nonphysical_placement",
        "assembly.surface_colour",
        "assembly.degenerate_polygon",
        "assembly.nonplanar_polygon",
        "assembly.bfc_order",
        "assembly.unreachable_section",
    } <= codes
    assert all(item.severity == "warning" for item in issues)
    with pytest.raises(ValueError):
        tuple(assembly_issues(model, matrix_tolerance=-1))
