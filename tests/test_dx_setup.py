"""Behavioral coverage for discovery, planning, metadata, and previews."""

from __future__ import annotations

import subprocess
import threading
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import requests

from ldraw import rendering
from ldraw.config import Config
from ldraw.diagnostics import DiagnosticCode
from ldraw.errors import CouldNotDetermineLatestVersionError, EmptyPartFileError
from ldraw.library_setup import (
    DownloadPlan,
    discover_libraries,
    inspect_library,
    plan_download,
)
from ldraw.operations import CancellationToken, OperationCancelled
from ldraw.part_metadata import (
    BfcCertification,
    PartFileKind,
    PartStatus,
    parse_part_metadata,
)
from ldraw.progress import ProgressStage
from ldraw.rendering import RenderBackend, RenderView, render_preview

if TYPE_CHECKING:
    from typing import Self

_PIECE = "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WRITE_PNG = "printf '\\211PNG\\r\\n\\032\\n'"


def _write_library(root: Path, *, release: str | None = "2026-01") -> Path:
    ldraw_path = root / "ldraw"
    (ldraw_path / "parts").mkdir(parents=True)
    (ldraw_path / "p").mkdir()
    (ldraw_path / "parts.lst").write_text("3001.dat Brick\n", encoding="utf-8")
    (ldraw_path / "ldconfig.ldr").write_text("0 colours\n", encoding="utf-8")
    if release is not None:
        (ldraw_path / "_release.txt").write_text(release, encoding="utf-8")
    return ldraw_path


def _response(headers: dict[str, str]) -> object:
    return type(
        "Response",
        (),
        {"headers": headers, "raise_for_status": lambda self: None},
    )()


def _renderer(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_library_inspection_handles_direct_paths_and_unreadable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ldraw_path = _write_library(tmp_path / "release", release=None)
    direct = inspect_library(ldraw_path)

    assert direct.path == ldraw_path.parent
    assert direct.valid is True
    assert direct.release is None
    assert direct.corrupt_components == ()

    (ldraw_path / "_release.txt").write_bytes(b"\xff")
    assert inspect_library(ldraw_path).release is None

    original_open = Path.open
    permission_error = OSError("permission denied")

    def failing_open(path: Path, *args, **kwargs):  # noqa: ANN202
        if path.name == "parts.lst":
            raise permission_error
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    unreadable = inspect_library(ldraw_path)

    assert unreadable.valid is False
    assert unreadable.missing_components == ()
    assert unreadable.corrupt_components == ("parts.lst",)
    assert unreadable.diagnostics[0].code is DiagnosticCode.DISCOVERY_INVALID_LIBRARY


def test_discover_libraries_deduplicates_sorts_and_reports_progress(
    tmp_path: Path,
) -> None:
    valid = _write_library(tmp_path / "valid")
    partial = tmp_path / "partial" / "ldraw"
    (partial / "parts").mkdir(parents=True)
    events = []

    discovered = discover_libraries(
        (partial.parent, valid.parent, valid.parent, tmp_path / "missing"),
        on_progress=events.append,
    )

    assert [item.valid for item in discovered] == [True, False]
    assert {item.ldraw_path for item in discovered} == {valid, partial}
    assert events[0].stage is ProgressStage.LIBRARY_DISCOVERY
    assert events[0].current == 0
    assert events[-1].current == 3
    assert events[-1].total == 3

    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        discover_libraries((valid.parent,), cancellation=token)


def test_discover_libraries_uses_config_and_cache_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _write_library(tmp_path / "configured")
    cache = tmp_path / "cache"
    cached = _write_library(cache / "cached")
    config = Config(
        ldraw_library_path=str(configured.parent),
        generated_path=str(tmp_path / "generated"),
    )
    monkeypatch.setattr("ldraw.library_setup.Config.load", staticmethod(lambda: config))
    monkeypatch.setattr("ldraw.library_setup.get_cache_dir", lambda: cache)

    discovered = discover_libraries()

    assert {item.ldraw_path for item in discovered} >= {configured, cached}


def test_discover_libraries_tolerates_corrupt_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("ldraw_library_path: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr("ldraw.config.CONFIG_FILE", config_file)
    cache = tmp_path / "cache"
    cached = _write_library(cache / "cached")
    monkeypatch.setattr("ldraw.library_setup.get_cache_dir", lambda: cache)

    discovered = discover_libraries()

    assert cached in {item.ldraw_path for item in discovered}


def test_inspect_library_classifies_install_root_named_ldraw(tmp_path: Path) -> None:
    root = tmp_path / "ldraw"
    ldraw_path = _write_library(root)

    inspection = inspect_library(root)

    assert inspection.path == root
    assert inspection.ldraw_path == ldraw_path
    assert inspection.valid is True


def test_inspect_library_classifies_data_directory_named_ldraw(
    tmp_path: Path,
) -> None:
    direct = tmp_path / "install" / "ldraw"
    (direct / "parts").mkdir(parents=True)
    (direct / "p").mkdir()
    (direct / "ldconfig.ldr").write_text("0 colours\n", encoding="utf-8")

    inspection = inspect_library(direct)

    assert inspection.path == direct.parent
    assert inspection.ldraw_path == direct
    assert inspection.missing_components == ("parts.lst",)


def test_download_plans_cover_integrity_and_network_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with zipfile.ZipFile(tmp_path / "2018-02.zip", "w") as archive:
        archive.writestr("ldraw/parts.lst", "parts")
    (tmp_path / "2018-02.zip.part").write_bytes(b"too much cached")
    monkeypatch.setattr(
        "ldraw.library_setup.requests.head",
        lambda **kwargs: _response({"content-length": "4"}),
    )

    versioned = plan_download("2018-02", cache_path=tmp_path)

    assert versioned.release == "2018-02"
    assert versioned.cached_archive_valid is True
    assert versioned.remaining_bytes == 0
    assert versioned.resumable is False

    (tmp_path / "complete.zip").write_bytes(b"not a zip")
    monkeypatch.setattr(
        "ldraw.library_setup.requests.head",
        lambda **kwargs: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )
    monkeypatch.setattr(
        "ldraw.library_setup.get_latest_release_id",
        lambda: (_ for _ in ()).throw(CouldNotDetermineLatestVersionError()),
    )

    current = plan_download(cache_path=tmp_path)

    assert current.download_size is None
    assert current.remaining_bytes is None
    assert current.cached_archive_valid is False
    assert [diagnostic.code for diagnostic in current.diagnostics] == [
        DiagnosticCode.DOWNLOAD_INTEGRITY_FAILED,
        DiagnosticCode.DOWNLOAD_PLAN_FAILED,
        DiagnosticCode.DOWNLOAD_PLAN_FAILED,
    ]

    with pytest.raises(ValueError, match="Unsupported"):
        plan_download("bad", cache_path=tmp_path)

    direct = DownloadPlan(
        version="x",
        release=None,
        url="https://example.test/x.zip",
        archive_path=tmp_path / "x.zip",
        destination=tmp_path / "x",
        download_size=None,
        cached_bytes=0,
        resumable=False,
        cached_archive_valid=None,
    )
    assert direct.remaining_bytes is None


def test_download_plan_reports_bad_archive_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "2020-01.zip").touch()

    class CorruptArchive:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args) -> None:
            return None

        def testzip(self) -> str:
            return "parts/bad.dat"

    monkeypatch.setattr(
        "ldraw.downloads.zipfile.ZipFile",
        lambda path: CorruptArchive(),
    )
    monkeypatch.setattr(
        "ldraw.library_setup.requests.head",
        lambda **kwargs: _response({}),
    )

    plan = plan_download("2020-01", cache_path=tmp_path)

    assert plan.cached_archive_valid is False
    assert plan.diagnostics[0].code is DiagnosticCode.DOWNLOAD_INTEGRITY_FAILED
    assert plan.diagnostics[0].offending_value == "parts/bad.dat"


def test_part_metadata_preview_statuses_and_fallbacks(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.dat"
    preview_path.write_text(
        "0 Preview Part\n"
        "0 !LDRAW_ORG Shortcut (Alias) 2026-01\n"
        "0 BFC CERTIFY CW\n"
        "0 !PREVIEW 4 1 2 3 1 0 0 0 1 0 0 0 1\n"
        f"{_PIECE}\n",
        encoding="utf-8",
    )

    preview = parse_part_metadata(preview_path)

    assert preview.file_kind is PartFileKind.SHORTCUT
    assert preview.status is PartStatus.ALIAS
    assert preview.replacement == "3001.dat"
    assert preview.bfc is BfcCertification.CW
    assert preview.preview is not None
    assert preview.preview.colour_code == 4
    assert type(preview).from_dict(preview.to_dict()) == preview

    obsolete_path = tmp_path / "obsolete.dat"
    obsolete_path.write_text(
        f"0 ~Obsolete old thing\n0 BFC NOCERTIFY\n0 !HISTORY malformed\n{_PIECE}\n",
        encoding="utf-8",
    )
    obsolete = parse_part_metadata(obsolete_path)
    assert obsolete.status is PartStatus.OBSOLETE
    assert obsolete.replacement == "3001.dat"
    assert obsolete.bfc is BfcCertification.NOCERTIFY
    assert obsolete.history[0].contributor is None

    unknown_path = tmp_path / "unknown.dat"
    unknown_path.write_text(
        "0 Current\n0 !LDRAW_ORG Something_New\n0 BFC CLIP\n",
        encoding="utf-8",
    )
    unknown = parse_part_metadata(unknown_path)
    assert unknown.file_kind is PartFileKind.UNKNOWN
    assert unknown.status is PartStatus.CURRENT
    assert unknown.bfc is BfcCertification.UNKNOWN

    empty_path = tmp_path / "empty.dat"
    empty_path.touch()
    with pytest.raises(EmptyPartFileError):
        parse_part_metadata(empty_path)


def test_render_preview_reports_input_and_backend_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = render_preview(tmp_path / "missing.ldr")
    assert missing.diagnostics[0].code is DiagnosticCode.RENDER_FAILED

    model = tmp_path / "model.ldr"
    model.write_text(_PIECE, encoding="utf-8")
    with pytest.raises(ValueError, match="positive dimensions"):
        render_preview(model, size=(0, 10))

    renderer = _renderer(tmp_path / "read-ldview", "exit 0")
    read_error = OSError("cannot read source")
    with monkeypatch.context() as scoped:
        scoped.setattr(
            "ldraw.rendering.shutil.which",
            lambda name: str(renderer) if name == "ldview" else None,
        )
        scoped.setattr(
            Path,
            "read_bytes",
            lambda path: (_ for _ in ()).throw(read_error),
        )
        unreadable = render_preview(model)
    assert unreadable.complete is False
    assert unreadable.diagnostics[0].cause is read_error

    monkeypatch.setattr("ldraw.rendering.shutil.which", lambda name: None)
    unavailable = render_preview(model)
    assert unavailable.backend is None
    assert unavailable.diagnostics[0].code is DiagnosticCode.RENDER_UNAVAILABLE

    failed = _renderer(tmp_path / "ldview", "echo renderer-error >&2; exit 2")
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(failed) if name == "ldview" else None,
    )
    failure = render_preview(model, cache_path=tmp_path / "failed-cache")
    assert failure.complete is False
    assert "renderer-error" in failure.diagnostics[0].message

    monkeypatch.setattr(
        "ldraw.rendering.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cannot execute")),
    )
    error = render_preview(model, cache_path=tmp_path / "error-cache")
    assert error.diagnostics[0].cause is not None
    assert list((tmp_path / "error-cache").glob(".preview-*.png")) == []


def test_render_preview_supports_leocad_outputs_cache_copy_and_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE, encoding="utf-8")
    leocad = _renderer(
        tmp_path / "leocad",
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--image" ]; then shift; out="$1"; fi\n'
        "  shift\n"
        "done\n"
        f'{_WRITE_PNG} > "$out"',
    )
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(leocad) if name == "leocad" else None,
    )
    events = []
    first_output = tmp_path / "outputs" / "first.png"
    second_output = tmp_path / "outputs" / "second.png"

    first = render_preview(
        model,
        backend=RenderBackend.LEOCAD,
        view=RenderView.TOP,
        output=first_output,
        cache_path=tmp_path / "cache",
        on_progress=events.append,
    )
    second = render_preview(
        model,
        backend=RenderBackend.LEOCAD,
        view=RenderView.TOP,
        output=second_output,
        cache_path=tmp_path / "cache",
    )

    assert first.output == first_output
    assert first.cached is False
    assert second.output == second_output
    assert second.cached is True
    assert second_output.read_bytes() == _PNG_SIGNATURE
    assert [event.current for event in events] == [0, 1]

    slow = _renderer(tmp_path / "ldview", "sleep 2")
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(slow) if name == "ldview" else None,
    )
    token = CancellationToken()
    timer = threading.Timer(0.1, token.cancel)
    timer.start()
    try:
        with pytest.raises(OperationCancelled):
            render_preview(
                model,
                backend=RenderBackend.LDVIEW,
                cache_path=tmp_path / "cancel-cache",
                cancellation=token,
            )
    finally:
        timer.cancel()


def test_render_preview_catches_subprocess_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE, encoding="utf-8")
    renderer = _renderer(tmp_path / "ldview", "exit 0")
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(renderer) if name == "ldview" else None,
    )
    process_error = subprocess.SubprocessError("broken process")

    class BrokenProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            raise process_error

    monkeypatch.setattr("ldraw.rendering.subprocess.Popen", BrokenProcess)
    result = render_preview(model, cache_path=tmp_path / "cache")

    assert result.complete is False
    assert isinstance(result.diagnostics[0].cause, subprocess.SubprocessError)


def test_run_renderer_drains_chatty_output_and_ignores_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail fast instead of stalling the suite if pipe draining regresses.
    monkeypatch.setattr("ldraw.rendering._RENDER_TIMEOUT_SECONDS", 30)
    chatty = _renderer(
        tmp_path / "chatty",
        "head -c 200000 /dev/zero | tr '\\000' x >&2\necho rendered",
    )

    completed = rendering._run_renderer(  # noqa: SLF001
        [str(chatty)],
        cancellation=None,
    )

    assert completed.returncode == 0
    assert len(completed.stderr) >= 200_000
    assert completed.stdout.strip() == "rendered"

    prompting = _renderer(tmp_path / "prompting", "cat > /dev/null\necho done")
    completed = rendering._run_renderer(  # noqa: SLF001
        [str(prompting)],
        cancellation=None,
    )
    assert completed.stdout.strip() == "done"


def test_render_preview_timeout_reports_captured_renderer_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE, encoding="utf-8")
    slow = _renderer(tmp_path / "ldview", "echo render-progress >&2\nsleep 30")
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(slow) if name == "ldview" else None,
    )
    monkeypatch.setattr("ldraw.rendering._RENDER_TIMEOUT_SECONDS", 1)

    result = render_preview(model, cache_path=tmp_path / "cache")

    assert result.complete is False
    assert result.diagnostics[0].code is DiagnosticCode.RENDER_FAILED
    assert "timed out" in result.diagnostics[0].message
    assert "render-progress" in result.diagnostics[0].message


def test_render_preview_rejects_non_png_renderer_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(_PIECE, encoding="utf-8")
    junk = _renderer(
        tmp_path / "ldview",
        'for value in "$@"; do\n'
        '  case "$value" in -SaveSnapshot=*) out=${value#*=};; esac\n'
        "done\n"
        'printf junk-bytes > "$out"\n'
        "echo junk-warning >&2",
    )
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(junk) if name == "ldview" else None,
    )

    result = render_preview(model, cache_path=tmp_path / "cache")

    assert result.complete is False
    assert result.diagnostics[0].code is DiagnosticCode.RENDER_FAILED
    assert "not a PNG" in result.diagnostics[0].message
    assert "junk-warning" in result.diagnostics[0].message
    assert list((tmp_path / "cache").glob("*.png")) == []
