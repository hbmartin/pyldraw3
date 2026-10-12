"""Executable adoption workflows and failure-mode contracts."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from ldraw import LDrawSession, Parts, api_inventory, doctor
from ldraw.cli import main
from ldraw.config import Config
from ldraw.library_access import data_directory, select_library

FIXTURE = Path(__file__).parent / "test_ldraw" / "ldraw"


def test_inventory_without_library(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("LDRAW_DIR", str(tmp_path / "absent"))
    result = api_inventory("Model.save", limit=1)
    assert result.total == 1
    assert "path" in result.items[0].signature
    assert api_inventory("STUD_PITCH").items[0].value == "20"
    assert main(["api", "Model.save", "--format", "json", "--limit", "0"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 1
    assert data["items"] == []
    with pytest.raises(ValueError):
        api_inventory(offset=-1)


def test_directory_without_index_is_read_only(tmp_path):
    source = tmp_path / "installation" / "ldraw"
    shutil.copytree(FIXTURE, source)
    (source / "parts.lst").unlink()
    original = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    parts = Parts.from_directory(source.parent, cache=tmp_path / "cache")
    assert parts.part(code="3001").path == source / "parts" / "3001.dat"
    assert parts.library_root == source
    assert parts.bounding_box("3001").size.y > 0
    assert (
        LDrawSession(library=source).load().part(code="3001").path
        == source / "parts" / "3001.dat"
    )
    assert original == {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert not (source / "parts.lst").exists()
    again = Parts.from_directory(source, cache=tmp_path / "cache")
    assert again.search("3001").items[0].code == "3001"


def test_ranked_search_filters_pages_and_literal_queries(tmp_path, capsys):
    parts = Parts.from_directory(FIXTURE, cache=tmp_path)
    result = parts.search("brick", limit=0)
    assert result.total >= 1
    assert result.items == ()
    assert parts.search("300", limit=1).items[0].code == "3001"
    assert parts.search("3001", category="plate").total == 0
    assert parts.search('" OR *').total == 0
    assert parts.resolve_symbol("Brick2X4").code == "3001"
    assert parts.resolve_symbol("unknown") is None
    with sqlite3.connect(parts.search_index) as connection:
        connection.execute("DROP TABLE parts_fts")
    fallback = parts.search("3001")
    assert fallback.items[0].code == "3001"
    assert fallback.diagnostics[-1].code == "catalog.search_fallback"
    with pytest.raises(ValueError):
        parts.search(limit=-1)
    assert (
        main(["parts", "search", "3001", "--library", str(FIXTURE), "--format", "json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_unwritable_cache_still_searches(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    parts = Parts.from_directory(FIXTURE, cache=blocked)
    result = parts.search("3001")
    assert result.total == 1
    assert len(result.diagnostics) == 2


def test_selection_precedence_and_invalid_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("LDRAW_DIR", str(tmp_path / "invalid"))
    assert select_library(library=FIXTURE).source == "argument"
    assert (
        select_library(Config(ldraw_library_path=str(FIXTURE))).source
        == "configuration"
    )
    with pytest.raises(FileNotFoundError, match="LDRAW_DIR"):
        select_library()
    with pytest.raises(FileNotFoundError, match="explicit"):
        LDrawSession(library=tmp_path / "missing")
    monkeypatch.setenv("LDRAW_DIR", str(FIXTURE))
    monkeypatch.setenv("LDRAWDIR", str(tmp_path / "other"))
    assert select_library().source == "LDRAW_DIR"
    assert data_directory(FIXTURE.parent) == data_directory(FIXTURE)


def test_doctor_does_not_prepare_cache(tmp_path, capsys):
    source = tmp_path / "ldraw"
    shutil.copytree(FIXTURE, source)
    (source / "parts.lst").unlink()
    before = list(source.rglob("*"))
    report = doctor(library=source)
    assert report.capabilities["geometry"]
    assert not report.capabilities["parts.lst"]
    assert report.cache["state"] == "unprepared"
    assert before == list(source.rglob("*"))
    assert main(["doctor", "--library", str(source), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["selection"]["source"] == "argument"
    assert doctor(library=tmp_path / "absent").diagnostics


def test_executable_python_walkthrough(tmp_path):
    from examples.adoption import workflows

    result = workflows(FIXTURE, tmp_path / "scene.ldr")
    assert result["bom"][0].quantity == 1
    assert result["inspection"].bounds is not None
    assert result["validation"] == ()
