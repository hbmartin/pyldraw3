"""Portable selection, dependency isolation, and qualified failure regressions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Self

from ldraw import Colour, Coverage, Model, Parts, Piece, bom_report, parse_model
from ldraw.assembly_validation import assembly_issues
from ldraw.cli import main
from ldraw.config import Config
from ldraw.diagnosis import doctor
from ldraw.geometry import Identity, Vector
from ldraw.pieces import Group
from ldraw.render_document import (
    camera_options,
    prepare_render_document,
    render_document,
)

IDENTITY = "1 0 0 0 1 0 0 0 1"


@pytest.fixture
def portable(tmp_path: Path) -> Parts:
    root = tmp_path / "installed"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    (root / "parts" / "brick.dat").write_text(
        "0 Brick\n0 !LDRAW_ORG Part\n2 24 0 0 0 20 8 20\n"
    )
    return Parts.from_directory(root, cache=tmp_path / "cache")


@pytest.mark.parametrize("selection", ["argument", "LDRAW_DIR", "LDRAWDIR"])
def test_generation_uses_selected_read_only_library(
    portable: Parts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    monkeypatch.delenv("LDRAW_DIR", raising=False)
    monkeypatch.delenv("LDRAWDIR", raising=False)
    saved = Config(
        ldraw_library_path=str(tmp_path / "ignored"),
        generated_path=str(tmp_path / "generated"),
    )
    args = ["generate", "--yes"]
    if selection == "argument":
        args += ["--library", str(portable.library_root)]
    else:
        monkeypatch.setenv(selection, str(portable.library_root))
    with patch("ldraw.cli._generate.Config.load", return_value=saved):
        assert main(args) == 0
    assert (tmp_path / "generated" / "library" / "__init__.py").is_file()
    assert not (portable.library_root / "parts.lst").exists()
    assert saved.ldraw_library_path.endswith("ignored")


def test_cached_indexes_rebuild_schema_and_doctor_only_observes(
    portable: Parts, tmp_path: Path
) -> None:
    import sqlite3

    database = portable.search_index
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=0")
    rebuilt = Parts.from_directory(portable.library_root, cache=tmp_path / "cache")
    assert rebuilt.search("brick").total == 1
    config = Config(ldraw_library_path=str(portable.library_root))
    from ldraw.library_access import index_directory

    normal = index_directory(portable.library_root)
    with patch("ldraw.diagnosis.index_directory", return_value=database.parent):
        assert doctor(config).cache["state"] == "ready"
        database.write_bytes(b"corrupt SQLite")
        assert doctor(config).cache["state"] == "stale-or-unreadable"
        assert database.read_bytes() == b"corrupt SQLite"
    assert normal != database.parent


def test_missing_index_with_unwritable_cache_uses_ephemeral_index(
    portable: Parts, tmp_path: Path
) -> None:
    blocked = tmp_path / "unwritable"
    blocked.write_text("file")
    parts = Parts.from_directory(portable.library_root, cache=blocked)
    assert parts.search("brick").total == 1
    assert parts.geometry("brick").bounds.max.y == 8
    assert {item.code for item in parts.diagnostics} >= {"catalog.persist_failed"}
    assert not (portable.library_root / "parts.lst").exists()


def test_actual_read_only_source_remains_usable(
    portable: Parts, tmp_path: Path
) -> None:
    root = portable.library_root
    paths = (root, *root.rglob("*"))
    modes = {path: path.stat().st_mode for path in paths}
    try:
        for path in paths:
            path.chmod(0o555 if path.is_dir() else 0o444)
        result = Parts.from_directory(root, cache=tmp_path / "fresh-cache")
        assert result.search("brick").total == 1
        assert result.geometry("brick").bounds.max.y == 8
        assert result.part(code="brick").path == root / "parts" / "brick.dat"
        assert not (root / "parts.lst").exists()
    finally:
        for path, mode in modes.items():
            path.chmod(mode)


def test_runtime_without_fts5_retains_catalog_and_reports_fallback(
    portable: Parts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from ldraw.catalog_search import fts5_available

    connect = sqlite3.connect

    class WithoutFTS5:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.connection = connect(*args, **kwargs)

        def __enter__(self) -> Self:
            self.connection.__enter__()
            return self

        def __exit__(self, *args: object) -> None:
            self.connection.__exit__(*args)

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
            if "using fts5" in sql.casefold():
                message = "no such module: fts5"
                raise sqlite3.OperationalError(message)
            return self.connection.execute(sql, *args)

    monkeypatch.setattr(sqlite3, "connect", WithoutFTS5)
    assert not fts5_available()
    parts = Parts.from_directory(portable.library_root, cache=tmp_path / "without-fts")
    result = parts.search("brick")
    assert result.items[0].code == "brick"
    assert result.diagnostics[-1].code == "catalog.search_fallback"
    assert parts.geometry("brick").bounds is not None


def test_code_prefix_ranking_uses_code_before_description_length(
    portable: Parts, tmp_path: Path
) -> None:
    root = portable.library_root / "parts"
    (root / "3001.dat").write_text(
        "0 Brick with a long descriptive name and many extra searchable words\n"
        "0 !LDRAW_ORG Part\n2 24 0 0 0 1 1 1\n"
    )
    (root / "3002.dat").write_text("0 Brick\n0 !LDRAW_ORG Part\n2 24 0 0 0 1 1 1\n")
    (root / "alias.dat").write_text(
        f"0 Brick Alias\n0 !LDRAW_ORG Part Alias\n1 16 0 0 0 {IDENTITY} brick.dat\n"
    )
    parts = Parts.from_directory(portable.library_root, cache=tmp_path / "rank-cache")
    assert [item.code for item in parts.search("300").items] == ["3001", "3002"]
    assert "alias" not in {
        item.code for item in parts.search("brick", physical_only=True).items
    }


def test_moved_header_target_and_empty_alias_are_qualified(portable: Parts) -> None:
    root = portable.library_root / "parts"
    (root / "moved.dat").write_text("0 ~Moved to brick\n0 !LDRAW_ORG Part\n")
    result = bom_report(
        Model.from_pieces([Piece.place("moved", colour=4)]), parts=portable
    )
    assert [(row.part, row.colour_code, row.quantity) for row in result.rows] == [
        ("brick", 4, 1)
    ]
    assert result.coverage == Coverage.COMPLETE
    (root / "empty.dat").write_text("0 Empty\n0 !LDRAW_ORG Part Alias\n")
    result = bom_report(Model.from_pieces([Piece.place("empty")]), parts=portable)
    assert result.coverage == Coverage.UNAVAILABLE
    assert result.unresolved_contents == ("empty.dat",)
    assert result.diagnostics[-1].code == "document.unresolved_alias"


def test_reference_names_in_headers_and_metadata_preserve_spaces(
    portable: Parts,
) -> None:
    from ldraw import read_model

    target = portable.library_root / "parts" / "my  part.dat"
    target.write_text(
        "0 Brick\n0 Name: my  part.dat\n0 !LDRAW_ORG Part\n2 24 0 0 0 1 1 1\n"
    )
    assert portable.part(code="my  part").metadata.name == "my  part.dat"
    (portable.library_root / "parts" / "moved.dat").write_text(
        "0 ~Moved to my  part\n0 !LDRAW_ORG Part\n"
    )
    model = parse_model(
        f"0 FILE my  model.ldr\n0 Name: my  model.ldr\n1 4 0 0 0 {IDENTITY} moved.dat\n"
        "0 !LDCAD SNAP_INCL [ref=my  part.dat]\n"
    )
    assert model.header_name == model.name == "my  model.ldr"
    assert "[ref=my  part.dat]" in model.objects[-1].to_ldraw()
    result = bom_report(model, parts=portable)
    assert result.rows[0].part == "my  part"
    output = portable.library_root.parent / "scene.mpd"
    model.save(output, mpd=True)
    assert read_model(output).header_name == "my  model.ldr"


def test_document_overlay_catalog_and_sources_are_isolated(portable: Parts) -> None:
    model = parse_model(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} brick.dat\n"
        "0 FILE brick.dat\n0 Replacement\n0 !LDRAW_ORG Part\n"
        "2 24 0 0 0 1 1 1\n"
    )
    overlay = portable.with_embedded(model)
    assert overlay.search("Replacement").items[0].description == "Replacement"
    assert overlay.description_for("absent") is None
    assert overlay.part(code="brick.dat").description == "Replacement"
    overlay.set_connection_overrides("brick", (), replace_existing=True)
    assert portable.connections("brick") == ()
    assert "brick" not in portable._connection_overrides  # noqa: SLF001
    assert overlay.diagnostics[-1].code == "document.library_shadowing"
    assert portable.part(code="brick").description == "Brick"


def test_embedded_ldr_kind_and_metadata_take_document_precedence(
    portable: Parts, tmp_path: Path
) -> None:
    from ldraw import inspect_model

    shadow = tmp_path / "shadow"
    (shadow / "parts").mkdir(parents=True)
    (shadow / "parts" / "brick.dat").write_text(
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 20]\n"
    )
    portable.add_connection_shadow(shadow)
    assert portable.connections("brick")
    model = parse_model(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} physical.ldr\n"
        "0 FILE physical.ldr\n0 !LDRAW_ORG Part\n2 24 0 0 0 3 5 7\n"
    )
    overlay = portable.with_embedded(model)
    assert overlay.part(code="physical.ldr").metadata.file_kind == "part"
    inspection = inspect_model(model, portable)
    assert inspection.occurrence_count == 1
    assert inspection.bounds.max == Vector(3, 5, 7)
    model = parse_model(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} brick.dat\n"
        "0 FILE brick.dat\n0 Replacement\n0 !LDRAW_ORG Part\n"
        "2 24 0 0 0 1 1 1\n"
    )
    assert portable.with_embedded(model).connections("brick") == ()


def test_extraction_retains_group_identity_and_rejects_inconsistent_graphs() -> None:
    group = Group(position=Vector(10, 0, 0), matrix=Identity())
    root = Model.from_pieces(
        [Piece.place("brick", group=group), Piece.place("brick", group=group)]
    )
    root.name = "main.ldr"
    extracted = root.extract("main.ldr", namespace="copy-").model
    assert extracted.pieces[0].group is extracted.pieces[1].group
    assert extracted.pieces[0].group is not group
    child = parse_model("0 Name: child.ldr\n0 Author: Alice\n", name="child.ldr")
    root.add_submodel(child)
    root.add(Piece.place("child.ldr"))
    result = root.extract("main.ldr", namespace="copy-")
    assert result.model.pieces[-1].reference == "copy-child.ldr"
    assert result.model.submodels["copy-child.ldr"].header_name == "copy-child.ldr"
    root.submodels["child.ldr"].name = "wrong.ldr"
    with pytest.raises(ValueError, match="inconsistent"):
        root.extract("main.ldr")
    root = Model(name="main.ldr", objects=[Piece.place("missing.ldr")])
    with pytest.raises(ValueError, match="missing section"):
        root.extract("main.ldr")


def test_render_export_closes_sidecars_and_hashes_dependencies(
    portable: Parts, tmp_path: Path
) -> None:
    source = tmp_path / "main.mpd"
    sidecar = tmp_path / "child.ldr"
    sidecar.write_text(f"1 4 0 0 0 {IDENTITY} brick.dat\n")
    source.write_text(
        f"0 FILE main.ldr\n1 4 10 0 0 {IDENTITY} child.ldr\n"
        "0 FILE unused.dat\n0 !LDRAW_ORG Part\n2 24 0 0 0 1 1 1\n"
    )
    with prepare_render_document(
        source, section=None, parts=portable, library=None
    ) as first:
        text = first.source.read_text()
        assert "0 FILE __pyldraw__/" in text
        assert first.bounds.max.x == 30
        first_identity = first.identity
    sidecar.write_text(f"1 4 20 0 0 {IDENTITY} brick.dat\n")
    with prepare_render_document(
        source, section=None, parts=portable, library=None
    ) as second:
        assert second.identity != first_identity
        assert second.bounds.max.x == 50
    assert "__pyldraw__" not in source.read_text()


def test_render_shadowed_library_does_not_invalidate_cache(
    portable: Parts, tmp_path: Path
) -> None:
    source = tmp_path / "main.mpd"
    source.write_text(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} brick.dat\n"
        "0 FILE brick.dat\n0 !LDRAW_ORG Part\n2 24 0 0 0 1 1 1\n"
    )
    with prepare_render_document(
        source, section=None, parts=portable, library=None
    ) as first:
        identity = first.identity
    (portable.library_root / "parts" / "brick.dat").write_text("0 Changed\n")
    with prepare_render_document(
        source, section=None, parts=portable, library=None
    ) as second:
        assert second.identity == identity


def test_render_selection_raw_bounds_and_unsafe_names(
    portable: Parts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "raw.ldr"
    source.write_text("2 24 0 0 0 10 10 10\n")
    monkeypatch.setenv("LDRAW_DIR", str(tmp_path / "missing"))
    with (
        pytest.raises(FileNotFoundError, match="LDRAW_DIR"),
        prepare_render_document(source, section=None, parts=None, library=None),
    ):
        pass
    monkeypatch.delenv("LDRAW_DIR")
    with (
        patch("ldraw.library_access.select_library", side_effect=FileNotFoundError),
        prepare_render_document(
            source, section=None, parts=None, library=None
        ) as context,
    ):
        assert context.bounds.max == Vector(10, 10, 10)
        token = render_document.set(context)
        try:
            assert camera_options(
                backend="ldview", latitude=0, longitude=0, size=(20, 20)
            )[0].startswith("-ModelCenter")
        finally:
            render_document.reset(token)
    source.write_text("0 FILE main.ldr\n0 FILE ../unsafe.dat\n")
    with (
        pytest.raises(ValueError, match="Unsafe"),
        prepare_render_document(source, section=None, parts=portable, library=None),
    ):
        pass


def test_assembly_line_bfc_and_missing_colour_checks(portable: Parts) -> None:
    model = parse_model(
        "0 BFC INVERTNEXT\n2 24 0 0 0 1 1 1\n0 BFC CERTIFY CCW\n",
        name="main.ldr",
    )
    issues = tuple(assembly_issues(model, parts=portable))
    assert sum(issue.code == "assembly.bfc_order" for issue in issues) == 2
    assert any("LDConfig" in issue.message for issue in issues)


def test_analysis_budget_does_not_build_unbounded_instruction_inventories(
    portable: Parts, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ldraw import analyze_model

    model = Model.from_pieces([Piece.place("brick") for _ in range(10)])

    def unexpected(self: Model, **kwargs: object) -> None:
        message = "instruction inventories must not traverse unvisited occurrences"
        raise AssertionError(message)

    monkeypatch.setattr(Model, "instruction_document", unexpected)
    result = analyze_model(model, parts=portable, occurrence_budget=1)
    assert result.processed_occurrences == 1
    assert result.total_occurrences is None
    assert result.instruction_steps == ()
    assert result.bom_coverage == Coverage.PARTIAL
    assert result.geometry_coverage == Coverage.PARTIAL
    assert result.connection_coverage == Coverage.UNAVAILABLE
    snap = result.inspection.snap_report(moving=0)
    assert snap.total_pairs is None
    assert snap.coverage == Coverage.PARTIAL
    assert snap.geometry_coverage == Coverage.PARTIAL
    contacts = result.inspection.connection_report(feature_pair_budget=1)
    assert contacts.total_pairs is None
    assert contacts.coverage == Coverage.PARTIAL


def test_analysis_without_library_qualifies_geometry_and_unknown_totals() -> None:
    from ldraw import analyze_model

    raw = parse_model("2 24 0 0 0 1 1 1\n")
    result = analyze_model(raw)
    assert result.geometry_coverage == Coverage.COMPLETE
    assert result.connection_coverage == Coverage.UNAVAILABLE
    raw.add(Piece.place("missing"))
    result = analyze_model(raw)
    assert result.geometry_coverage == Coverage.PARTIAL
    assert result.total_occurrences is None
    assert result.bom_coverage == Coverage.PARTIAL
    assert bom_report(raw).total_occurrences is None
    result = analyze_model(Model.from_pieces([Piece.place("missing")]))
    assert result.geometry_coverage == Coverage.UNAVAILABLE


def test_assembly_resolves_raw_inherited_colours_across_placements() -> None:
    model = parse_model(
        f"0 FILE main.ldr\n1 4 0 0 0 {IDENTITY} raw.ldr\n"
        "0 FILE raw.ldr\n3 16 0 0 0 1 0 0 0 1 0\n"
    )
    assert not any(
        item.code == "assembly.unresolved_inherited_colour"
        for item in assembly_issues(model)
    )
    model.pieces[0].colour = Colour(16)
    assert any(
        item.code == "assembly.unresolved_inherited_colour"
        for item in assembly_issues(model)
    )


def test_measurement_cli_missing_part_and_report_output(
    portable: Parts, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["parts", "measurements", "absent", "--library", str(portable.library_root)]
    assert main(args) == 1
    assert "absent" in capsys.readouterr().err
    output = tmp_path / "measurements.json"
    args[2] = "brick"
    assert main([*args, "--format", "json", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["stack_height"] is None
    assert main([*args, "--format", "table"]) == 0
    assert "measurement.unsupported" in capsys.readouterr().out


def test_executable_document_workflow_matches_cli(
    portable: Parts, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.adoption_reports import document_workflows

    source = tmp_path / "scene.mpd"
    result = document_workflows(portable, source)
    assert result["bom"].rows[0].quantity == 2
    assert result["inspection"].occurrence_count == 2
    assert result["bounded_bom"].coverage == Coverage.PARTIAL
    target, manifest = tmp_path / "copy.mpd", tmp_path / "manifest.json"
    args = [
        "extract",
        str(source),
        "local.dat",
        "--namespace",
        "reuse-",
        "--output",
        str(target),
    ]
    assert main([*args, "--manifest", str(manifest)]) == 0
    assert json.loads(manifest.read_text())[0]["author"] == "Example author"
    assert parse_model(target.read_text()).author == "Example author"
    assert main([*args, "--manifest", str(target)]) == 1
    assert "different output paths" in capsys.readouterr().err
    args[2] = "absent.ldr"
    assert main(args) == 1
    args[2] = "local.dat"
    args[-1] = str(tmp_path / "missing-parent" / "copy.mpd")
    assert main(args) == 1
    assert "Could not write" in capsys.readouterr().err
    args[-1] = str(target)
    assert main([*args, "--manifest", str(tmp_path / "absent" / "manifest.json")]) == 1
    source.write_text("1 invalid\n")
    assert main(args) == 1


def test_executable_connection_workflow_matches_qualified_cli(
    portable: Parts, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.adoption_reports import connection_workflows

    (portable.library_root / "parts" / "brick.dat").write_text(
        "0 Brick\n0 !LDRAW_ORG Part\n"
        "0 !LDCAD SNAP_CYL [gender=M] [secs=R 6 20] [center=true] [caps=none]\n"
        "0 !LDCAD SNAP_CYL [gender=F] [secs=R 6 20] [center=true] [caps=none]\n"
        "2 24 -6 -10 -6 6 10 6\n"
    )
    source = tmp_path / "stack.ldr"
    result = connection_workflows(portable, source, code="brick", height=20)
    assert result["snap"].candidates
    original = source.read_bytes()
    args = [
        "snap",
        str(source),
        "--moving",
        "1",
        "--fixed",
        "0",
        "--library",
        str(portable.library_root),
    ]
    assert main([*args, "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["examined_pairs"] == report["total_pairs"]
    assert report["candidates"][0]["contact_supported"]
    assert "collisions" in report["unsupported_checks"]
    assert main([*args, "--feature-pair-budget", "0", "--strict"]) == 1
    assert "examined pairs only" in capsys.readouterr().out
    assert main([*args, "--moving", "99"]) == 1
    assert "no occurrence" in capsys.readouterr().err
    assert main([*args, "--ldcad-shadow", str(tmp_path / "absent")]) == 1
    assert main([*args, "--output", str(tmp_path / "absent" / "report.json")]) == 1
    source.write_text("1 invalid\n")
    assert main(args) == 1
    assert original != source.read_bytes()
    with patch(
        "ldraw.cli._document_reports._load_parts_with_connection_sources",
        return_value=None,
    ):
        assert main(args) == 1
