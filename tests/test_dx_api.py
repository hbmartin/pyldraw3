"""Tests for the report-oriented DX and inspection APIs added in 1.5."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from ldraw.catalog import load_catalog, save_catalog
from ldraw.diagnostics import DiagnosticCode
from ldraw.library_setup import inspect_library, plan_download
from ldraw.model import parse_model_result
from ldraw.operations import CancellationToken, OperationCancelled
from ldraw.part import Part
from ldraw.part_metadata import (
    BfcCertification,
    LibraryOrigin,
    PartFileKind,
    PartStatus,
)
from ldraw.parts import CatalogEntry, CatalogSearchField, PartCategory, PartsCatalog
from ldraw.rendering import RenderBackend, RenderView, render_preview

if TYPE_CHECKING:
    from pathlib import Path

_PIECE = "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat"


def test_tolerant_parse_keeps_valid_pieces_around_bad_lines() -> None:
    result = parse_model_result(
        f"0 Demo\n{_PIECE}\n2 24 bad 0 0 1 1 1\n{_PIECE}\n",
        name="demo.ldr",
    )

    assert result.model is not None
    assert len(result.model.pieces) == 2
    assert result.complete is False
    assert result.valid is False
    assert result.diagnostics[0].code is DiagnosticCode.PARSE_INVALID_NUMERIC
    assert result.diagnostics[0].line_number == 3
    assert result.diagnostics[0].offending_value == "bad"


def test_tolerant_misplaced_nofile_does_not_hide_later_content() -> None:
    result = parse_model_result(f"0 NOFILE\n{_PIECE}\n", name="demo.ldr")

    assert result.model is not None
    assert len(result.model.pieces) == 1
    assert result.diagnostics[0].code is DiagnosticCode.MPD_MISPLACED_NOFILE


def test_mpd_structure_diagnostics_have_stable_codes() -> None:
    text = "\n".join(  # noqa: FLY002 - tuple keeps MPD source lines legible
        (
            "0 FILE main.ldr",
            "1 16 0 0 0 1 0 0 0 1 0 0 0 1 sub.ldr",
            "1 16 0 0 0 1 0 0 0 1 0 0 0 1 missing.ldr",
            "0 NOFILE",
            "0 FILE sub.ldr",
            "1 16 0 0 0 1 0 0 0 1 0 0 0 1 main.ldr",
            "0 NOFILE",
            "0 FILE sub.ldr",
            _PIECE,
            "0 NOFILE",
        ),
    )

    result = parse_model_result(text, source="structure.mpd")
    codes = {diagnostic.code for diagnostic in result.diagnostics}

    assert DiagnosticCode.MPD_DUPLICATE_SECTION in codes
    assert DiagnosticCode.MPD_UNRESOLVED_SUBMODEL in codes
    assert DiagnosticCode.MPD_CYCLE in codes


def test_occurrence_path_retains_outer_and_leaf_placement_context() -> None:
    text = "\n".join(  # noqa: FLY002 - tuple keeps MPD source lines legible
        (
            "0 FILE main.ldr",
            "0 STEP",
            "1 4 10 0 0 1 0 0 0 1 0 0 0 1 sub.ldr",
            "0 NOFILE",
            "0 FILE sub.ldr",
            "0 STEP",
            _PIECE,
            "0 NOFILE",
        ),
    )
    result = parse_model_result(text)
    assert result.model is not None

    occurrence = next(result.model.iter_occurrences())

    assert tuple(item.model.name for item in occurrence.path) == (
        "main.ldr",
        "sub.ldr",
    )
    assert tuple(item.source_line for item in occurrence.path) == (3, 7)
    assert tuple(item.local_step for item in occurrence.path) == (2, 2)
    assert tuple(item.effective_step for item in occurrence.path) == (2, 2)
    assert occurrence.position.x == 10


def test_catalog_search_fields_scope_and_ranking() -> None:
    exact = CatalogEntry("3001", "Brick 2 x 4", PartCategory.BRICK)
    prefix = CatalogEntry("30010", "Tyre", PartCategory.TYRE)
    keyword = CatalogEntry(
        "973",
        "Minifig Torso",
        PartCategory.MINIFIG,
        keywords=("brick costume",),
    )
    catalog = PartsCatalog()
    for entry in (keyword, prefix, exact):
        catalog.add(entry)

    assert catalog.search("  3001 ") == (exact, prefix)
    assert catalog.search("brick  costume") == (keyword,)
    assert catalog.search(
        "brick",
        fields=(CatalogSearchField.CATEGORY,),
    ) == (exact,)
    assert catalog.search("", within=(prefix,)) == (prefix,)


def test_part_metadata_parses_relationships_and_provenance(tmp_path: Path) -> None:
    path = tmp_path / "old.dat"
    path.write_text(
        "0 ~Moved to 3001\n"
        "0 Name: old.dat\n"
        "0 Author: Example Person [example]\n"
        "0 !LDRAW_ORG Unofficial_Part (Alias) 2026-01\n"
        "0 !LICENSE Redistributable under CC BY 4.0 : see CAreadme.txt\n"
        "0 BFC CERTIFY CCW\n"
        "0 !CATEGORY Brick\n"
        "0 !KEYWORDS old, redirect\n"
        "0 !HISTORY 2026-01-02 [reviewer] Redirected\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n",
        encoding="utf-8",
    )

    metadata = Part(path).metadata

    assert metadata.file_kind is PartFileKind.PART
    assert metadata.origin is LibraryOrigin.UNOFFICIAL
    assert metadata.status is PartStatus.MOVED
    assert metadata.replacement == "3001"
    assert metadata.author == "Example Person"
    assert metadata.author_username == "example"
    assert metadata.bfc is BfcCertification.CCW
    assert metadata.category == "Brick"
    assert metadata.keywords == ("old", "redirect")
    assert metadata.history[0].contributor == "reviewer"
    assert type(metadata).from_dict(metadata.to_dict()) == metadata

    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(
            code="old",
            description=metadata.description,
            category=PartCategory.BRICK,
            metadata=metadata,
        ),
    )
    database = tmp_path / "catalog.sqlite"
    save_catalog(
        database,
        md5="parts-md5",
        catalog=catalog,
        library_root=tmp_path,
        tree_fingerprint="tree",
    )
    restored = load_catalog(
        database,
        md5="parts-md5",
        library_root=tmp_path,
        tree_fingerprint="tree",
    )
    assert restored is not None
    assert restored.by_code["old"].metadata == metadata

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE parts SET metadata_json = ? WHERE code = 'old'",
            ('{"preview": {}}',),
        )
        connection.commit()
    finally:
        connection.close()
    assert (
        load_catalog(
            database,
            md5="parts-md5",
            library_root=tmp_path,
            tree_fingerprint="tree",
        )
        is None
    )


def test_library_inspection_reports_missing_and_valid_components(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release"
    (root / "ldraw" / "parts").mkdir(parents=True)
    partial = inspect_library(root)
    assert partial.valid is False
    assert set(partial.missing_components) == {"p", "parts.lst", "ldconfig.ldr"}

    (root / "ldraw" / "p").mkdir()
    (root / "ldraw" / "parts.lst").write_text("3001.dat Brick\n")
    (root / "ldraw" / "ldconfig.ldr").write_text("0 colours\n")
    (root / "ldraw" / "_release.txt").write_text("2026-01\n")
    valid = inspect_library(root)
    assert valid.valid is True
    assert valid.release == "2026-01"


def test_download_plan_reports_exact_size_release_and_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = tmp_path / "complete.zip.part"
    partial.write_bytes(b"partial")
    response = type(
        "Response",
        (),
        {
            "headers": {"content-length": "1234", "accept-ranges": "bytes"},
            "raise_for_status": lambda self: None,
        },
    )()
    monkeypatch.setattr("ldraw.library_setup.requests.head", lambda **kwargs: response)
    monkeypatch.setattr(
        "ldraw.library_setup.get_latest_release_id",
        lambda: "2026-01",
    )

    plan = plan_download(cache_path=tmp_path)

    assert plan.release == "2026-01"
    assert plan.download_size == 1_234
    assert plan.cached_bytes == len(b"partial")
    assert plan.resumable is True
    assert plan.remaining_bytes == 1_227


def test_download_plan_honours_pre_cancelled_token(tmp_path: Path) -> None:
    token = CancellationToken()
    token.cancel()

    with pytest.raises(OperationCancelled):
        plan_download(cache_path=tmp_path, cancellation=token)


def test_render_preview_detects_backend_and_uses_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE)
    renderer = tmp_path / "ldview"
    renderer.write_text(
        "#!/bin/sh\n"
        'for value in "$@"; do\n'
        '  case "$value" in -SaveSnapshot=*) out=${value#*=};; esac\n'
        "done\n"
        'printf png > "$out"\n',
        encoding="utf-8",
    )
    renderer.chmod(0o755)
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(renderer) if name == "ldview" else None,
    )

    first = render_preview(
        model,
        backend=RenderBackend.LDVIEW,
        view=RenderView.FRONT,
        cache_path=tmp_path / "cache",
    )
    second = render_preview(
        model,
        backend=RenderBackend.LDVIEW,
        view=RenderView.FRONT,
        cache_path=tmp_path / "cache",
    )

    assert first.complete is True
    assert first.cached is False
    assert second.output == first.output
    assert second.cached is True


def test_render_preview_reports_unavailable_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE)
    monkeypatch.setattr("ldraw.rendering.shutil.which", lambda name: None)

    result = render_preview(model, backend=RenderBackend.LEOCAD)

    assert result.complete is False
    assert result.diagnostics[0].code is DiagnosticCode.RENDER_UNAVAILABLE
