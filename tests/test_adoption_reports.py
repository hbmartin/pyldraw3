"""Qualified report and portable cache workflows, exercised through public APIs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from ldraw import (
    Coverage,
    LDrawSession,
    Model,
    Parts,
    api_inventory,
    inspect_model,
)
from ldraw.assembly_validation import assembly_issues
from ldraw.cli import main
from ldraw.config import Config
from ldraw.connection_types import ConnectionResidual, ConnectionStatus
from ldraw.diagnosis import doctor
from ldraw.geometry import Vector
from ldraw.inspection import ConnectionGraphEdge, ConnectionMultigraph
from ldraw.library_access import select_library
from ldraw.library_setup import discover_libraries
from ldraw.render_document import (
    camera_options,
    prepare_render_document,
    render_document,
)
from ldraw.validation import iter_ldr_issues

IDENTITY = "1 0 0 0 1 0 0 0 1"


@pytest.fixture
def portable(tmp_path: Path) -> Parts:
    root = tmp_path / "installed" / "ldraw"
    (root / "parts").mkdir(parents=True)
    (root / "p").mkdir()
    for code, role in (("pin", "M"), ("hole", "F")):
        (root / "parts" / f"{code}.dat").write_text(
            f"0 {code}\n0 !LDRAW_ORG Part\n"
            f"0 !LDCAD SNAP_CYL [gender={role}] [secs=R 6 20] [center=true]\n"
            "2 24 -6 -10 -6 6 10 6\n",
            encoding="utf-8",
        )
    return Parts.from_directory(root, cache=tmp_path / "cache")


def test_missing_index_session_is_portable_and_read_only(
    portable: Parts, tmp_path: Path
) -> None:
    root = portable.library_root
    assert not (root / "parts.lst").exists()
    cfg = Config(
        ldraw_library_path=str(root.parent), generated_path=str(tmp_path / "generated")
    )
    session = LDrawSession(cfg)
    result = session.prepare_catalog()
    assert result.complete
    assert result.final_state.ready
    assert result.parts.geometry("pin").bounds.max.y == 10
    assert not (root / "parts.lst").exists()
    assert LDrawSession(library=root).load().search("pin").total == 1
    state = doctor(cfg)
    assert state.capabilities["geometry"]
    assert state.cache["state"] == "ready"


def test_inventory_output_and_documented_constants(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    constant = api_inventory("STUD_PITCH").items[0]
    assert "20 LDraw units" in constant.docstring
    assert main(["api", "Model.save", "--format", "table"]) == 0
    assert "atomic" in capsys.readouterr().out
    out = tmp_path / "api.json"
    assert (
        main(
            [
                "api",
                "--format",
                "json",
                "--limit",
                "1",
                "--offset",
                "1",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text())
    assert len(data["items"]) == 1
    assert data["total"] > 1


def test_ambiguous_discovery_requires_selection(
    portable: Parts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    (other / "parts").mkdir(parents=True)
    (other / "p").mkdir()
    monkeypatch.delenv("LDRAW_DIR", raising=False)
    monkeypatch.delenv("LDRAWDIR", raising=False)
    monkeypatch.setattr(
        "ldraw.library_access.get_config", lambda: tmp_path / "absent-config"
    )
    monkeypatch.setattr(
        "ldraw.config.get_cache_dir", lambda: str(tmp_path / "absent-cache")
    )
    candidates = discover_libraries([other, portable.library_root])
    monkeypatch.setattr("ldraw.library_access.discover_libraries", lambda: candidates)
    with pytest.raises(ValueError, match="Multiple"):
        select_library()
    monkeypatch.setattr(
        "ldraw.library_access.discover_libraries", lambda: candidates[:1]
    )
    assert select_library().source == "discovery"
    monkeypatch.setenv("LDRAWDIR", str(other))
    assert select_library().source == "LDRAWDIR"


def test_contact_and_snap_budgets_are_qualified(portable: Parts) -> None:
    model = Model.from_pieces([])
    from ldraw import Piece

    model.add(Piece.place("pin"))
    model.add(Piece.place("hole"))
    result = inspect_model(model, portable)
    report = result.connection_report(feature_pair_budget=0)
    assert report.coverage == Coverage.PARTIAL
    assert report.total_pairs is None
    report = result.connection_report(feature_pair_budget=10)
    assert report.coverage == Coverage.COMPLETE
    assert len(report.contacts) == 1
    snap = result.snap_report(moving=0, feature_pair_budget=0)
    assert snap.examined_pairs == 0
    assert snap.total_pairs == 1
    assert "examined pairs only" in snap.diagnostics[0].message
    assert result.snap_report(moving=0, fixed=1).candidates == result.snap_candidates(
        moving=0, fixed=1
    )
    assert result.snap_report(moving=0, fixed=0).total_pairs == 0
    assert result.snap_report(moving=0, limit=0).candidates == ()
    with pytest.raises(ValueError):
        result.connection_report(feature_pair_budget=-1)
    bounded = inspect_model(model, portable, feature_pair_budget=0)
    assert bounded.pair_budget_exhausted
    assert bounded.connection_coverage == Coverage.PARTIAL


def test_multigraph_components_include_isolates_and_parallel_edges() -> None:
    graph = ConnectionMultigraph(
        nodes=(3, 1, 2, 0),
        edges=(
            ConnectionGraphEdge(
                0, 1, "a", "b", ConnectionStatus.CONFIRMED, ConnectionResidual(0, 0, 1)
            ),
            ConnectionGraphEdge(
                0, 1, "a", "b", ConnectionStatus.CONFIRMED, ConnectionResidual(0, 0, 1)
            ),
        ),
    )
    assert graph.components() == ((0, 1), (2,), (3,))
    with pytest.raises(ValueError, match="node"):
        ConnectionMultigraph(
            nodes=(0,),
            edges=(
                ConnectionGraphEdge(
                    0,
                    1,
                    "a",
                    "b",
                    ConnectionStatus.CONFIRMED,
                    ConnectionResidual(0, 0, 1),
                ),
            ),
        ).components()


def test_section_render_exports_embedded_geometry_and_frames_camera(
    portable: Parts, tmp_path: Path
) -> None:
    path = tmp_path / "model.mpd"
    path.write_text(
        f"0 FILE root.ldr\n1 4 0 0 0 {IDENTITY} local.dat\n"
        "0 FILE local.dat\n0 !LDRAW_ORG Part\n2 24 0 0 0 10 8 10\n"
    )
    original = path.read_bytes()
    with prepare_render_document(
        path, section=None, parts=portable, library=None
    ) as context:
        assert (context.source.parent / "local.dat").is_file()
        assert context.bounds.max == Vector(10, 8, 10)
        token = render_document.set(context)
        try:
            assert any(
                arg.startswith("-ModelCenter=")
                for arg in camera_options(
                    backend="ldview", latitude=0, longitude=0, size=(800, 600)
                )
            )
            assert "--camera-position-ldraw" in camera_options(
                backend="leocad", latitude=89, longitude=0, size=(600, 800)
            )
        finally:
            render_document.reset(token)
    assert not context.source.exists()
    with prepare_render_document(
        path, section="local.dat", parts=portable, library=None
    ) as selected:
        assert "0 FILE local.dat" in selected.source.read_text()
    assert path.read_bytes() == original
    with prepare_render_document(
        path, section=None, parts=None, library=portable.library_root
    ) as again:
        assert again.library == portable.library_root


def test_assembly_profile_reports_unrun_checks_and_tolerance(
    portable: Parts, tmp_path: Path
) -> None:
    path = tmp_path / "bad.ldr"
    path.write_text(
        "0 Name: different.ldr\n3 4 0 0 0 10 0 0 0 0 10\n"
        "0 BFC CERTIFY CCW\n0 BFC INVERTNEXT\n0 BFC INVERTNEXT\n"
        "3 24 0 0 0 10 0 0 0 0 10\n"
    )
    result = tuple(iter_ldr_issues(path, profile="assembly", matrix_tolerance=1e-4))
    codes = {item.code for item in result}
    assert "assembly.bfc_order" in codes
    assert "assembly.header_name" in codes
    assert "assembly.check_not_run" in codes
    model = Model.from_pieces([])
    assert {item.code for item in assembly_issues(model, connectivity=True)} == {
        "assembly.check_not_run"
    }
    assert {
        item.code for item in assembly_issues(model, parts=portable, connectivity=True)
    } == {"assembly.check_not_run"}
    with pytest.raises(ValueError, match="profile"):
        tuple(iter_ldr_issues(path, profile="unknown"))
    with pytest.raises(ValueError, match="finite"):
        tuple(assembly_issues(model, matrix_tolerance=float("nan")))
