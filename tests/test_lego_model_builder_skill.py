"""Tests for the bundled lego-model-builder helper scripts."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

SKILL_DIR = Path(__file__).parents[1] / "skills" / "lego-model-builder"


@dataclass(frozen=True)
class PreflightOptions:
    """Environment choices for an isolated preflight invocation."""

    import_ready: bool = True
    python3_version_ok: bool = True
    uv_available: bool = False
    virtual_env: Path | None = None
    virtualenv_version_ok: bool = True


DEFAULT_PREFLIGHT_OPTIONS = PreflightOptions()


def _load_script(name: str) -> ModuleType:
    path = SKILL_DIR / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def _write_executable(path: Path, label: str, *, version_ok: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A version probe (`-c '... version_info ...'`) exits 0 when new enough and
    # is never logged, so PY_LOG records only interpreters used for real work.
    status = 0 if version_ok else 1
    path.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *version_info*) exit {status} ;;\n"
        '  *"import ldraw"*) [ -f "$PY_IMPORT_READY" ] && exit 0 || exit 1 ;;\n'
        f'  *"-m pip install"*) printf \'{label}:pip-install\\n\' >> "$PY_LOG"; '
        ': > "$PY_IMPORT_READY"; exit 0 ;;\n'
        '  *"-m pip --version"*) exit 0 ;;\n'
        "esac\n"
        f"printf '{label}\\n' >> \"$PY_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_uv(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'printf \'uv:%s\\n\' "$*" >> "$PY_LOG"\n'
        ': > "$PY_IMPORT_READY"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_preflight(
    tmp_path: Path,
    options: PreflightOptions = DEFAULT_PREFLIGHT_OPTIONS,
) -> list[str]:
    bin_dir = tmp_path / "bin"
    log = tmp_path / "python.log"
    import_marker = tmp_path / "import-ready"
    if options.import_ready:
        import_marker.touch()
    _write_executable(bin_dir / "python", "python")
    _write_executable(
        bin_dir / "python3",
        "python3",
        version_ok=options.python3_version_ok,
    )
    _write_executable(bin_dir / "ldview", "ldview")
    if options.uv_available:
        _write_uv(bin_dir / "uv")

    env = {
        "PATH": str(bin_dir),
        "PY_IMPORT_READY": str(import_marker),
        "PY_LOG": str(log),
    }
    if options.virtual_env is not None:
        _write_executable(
            options.virtual_env / "bin" / "python",
            "venv-python",
            version_ok=options.virtualenv_version_ok,
        )
        env["VIRTUAL_ENV"] = str(options.virtual_env)

    subprocess.run(
        ["/bin/bash", str(SKILL_DIR / "scripts" / "preflight.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_preflight_prefers_python3_without_virtualenv(tmp_path: Path) -> None:
    assert set(_run_preflight(tmp_path)) == {"python3"}


def test_preflight_prefers_activated_virtualenv(tmp_path: Path) -> None:
    virtual_env = tmp_path / "venv"
    options = PreflightOptions(virtual_env=virtual_env)
    assert set(_run_preflight(tmp_path, options)) == {"venv-python"}


def test_preflight_rejects_old_activated_virtualenv(tmp_path: Path) -> None:
    virtual_env = tmp_path / "venv"
    options = PreflightOptions(
        virtual_env=virtual_env,
        virtualenv_version_ok=False,
    )
    assert _run_preflight(tmp_path, options) == []


def test_preflight_falls_through_when_python3_too_old(tmp_path: Path) -> None:
    # python3 is on PATH but reports < 3.12, so py() must skip it for python.
    options = PreflightOptions(python3_version_ok=False)
    assert set(_run_preflight(tmp_path, options)) == {"python"}


def test_preflight_installs_into_selected_interpreter(tmp_path: Path) -> None:
    options = PreflightOptions(
        python3_version_ok=False,
        import_ready=False,
    )
    calls = _run_preflight(tmp_path, options)

    assert "python:pip-install" in calls
    assert not any(call.startswith("python3") for call in calls)


def test_preflight_uses_uv_with_selected_virtualenv(tmp_path: Path) -> None:
    virtual_env = tmp_path / "venv"
    options = PreflightOptions(
        virtual_env=virtual_env,
        import_ready=False,
        uv_available=True,
    )
    calls = _run_preflight(tmp_path, options)

    expected = f"uv:pip install --python {virtual_env}/bin/python pyldraw3"
    assert expected in calls
    assert not any(call.endswith(":pip-install") for call in calls)


def test_duplicate_detection_casefolds_part_names() -> None:
    geometry = _load_script("check_geometry")
    position = SimpleNamespace(x=0, y=0, z=0)
    colour = SimpleNamespace(code=4)
    pieces = [
        SimpleNamespace(part="3001.DAT", colour=colour, position=position),
        SimpleNamespace(part="3001.dat", colour=colour, position=position),
    ]

    suffix = "same piece placed on top of itself"
    expected = f"duplicate: 2x part 3001.dat colour 4 at (0, 0, 0) — {suffix}"
    assert geometry._find_duplicates(pieces) == [expected]  # noqa: SLF001


def test_supported_renderers_are_ldview_and_leocad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    probed: list[str] = []

    def available(name: str) -> str:
        probed.append(name)
        return f"/renderer/{name}"

    monkeypatch.setattr(render.shutil, "which", available)

    assert render._detect() == ["ldview", "leocad"]  # noqa: SLF001
    assert probed == ["ldview", "leocad"]


def test_run_handles_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    render = _load_script("render")
    error_message = "renderer is not executable"

    def raise_permission_error(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(error_message)

    monkeypatch.setattr(render.subprocess, "run", raise_permission_error)

    ok, error = render._run(["ldview", "model.ldr"])  # noqa: SLF001

    assert not ok
    assert error == error_message


def test_render_rejects_empty_or_invalid_views_before_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    model.touch()
    existing = tmp_path / "model.front.png"
    existing.write_text("keep me", encoding="utf-8")
    detection_calls: list[bool] = []

    def track_detection() -> list[str]:
        detection_calls.append(True)
        return []

    monkeypatch.setattr(render, "_detect", track_detection)

    for views in ("", ",", "unknown"):
        assert render.main([str(model), "--views", views]) == 1
        assert "error: no valid views specified" in capsys.readouterr().err
    assert detection_calls == []
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert not (tmp_path / "previous").exists()


def test_render_deduplicates_views_while_preserving_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    model.touch()
    rendered: list[str] = []

    def working_renderer(
        _model: Path,
        output: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        rendered.append(output.name)
        output.touch()
        return True, ""

    monkeypatch.setattr(render, "_detect", lambda: ["ldview"])
    monkeypatch.setitem(render.RENDERERS, "ldview", working_renderer)

    assert render.main([str(model), "--views", "front,iso,front,top,iso"]) == 0
    assert rendered == [
        "model.front.png",
        "model.iso.png",
        "model.top.png",
    ]
    assert "Rendered 3 view(s) with ldview." in capsys.readouterr().err


def test_render_rejects_non_positive_size_before_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    existing = tmp_path / "model.front.png"
    model.touch()
    existing.write_text("keep me", encoding="utf-8")
    detection_calls: list[bool] = []

    def track_detection() -> list[str]:
        detection_calls.append(True)
        return ["ldview"]

    monkeypatch.setattr(render, "_detect", track_detection)

    for size in ("0x768", "1024x0", "-1x768", "1024x-1"):
        assert render.main([str(model), f"--size={size}", "--views", "front"]) == 1
        assert "with positive integers" in capsys.readouterr().err

    assert detection_calls == []
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert not (tmp_path / "previous").exists()


def test_render_leaves_existing_outputs_when_no_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    existing = tmp_path / "model.front.png"
    model.touch()
    existing.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(render, "_detect", list)

    assert render.main([str(model), "--views", "front"]) == 1
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert not (tmp_path / "previous").exists()


def test_render_archives_requested_views_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    model.touch()
    for view in ("front", "iso"):
        (tmp_path / f"model.{view}.png").write_text(
            f"old-{view}",
            encoding="utf-8",
        )
    unrequested = tmp_path / "model.top.png"
    unrequested.write_text("old-top", encoding="utf-8")

    def working_renderer(
        _model: Path,
        output: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        output.write_text("new", encoding="utf-8")
        return True, ""

    stamp = "20260710T201234.123456Z"
    monkeypatch.setattr(render, "_archive_stamp", lambda: stamp)
    monkeypatch.setattr(render, "_detect", lambda: ["ldview"])
    monkeypatch.setitem(render.RENDERERS, "ldview", working_renderer)

    assert render.main([str(model), "--views", "front,iso"]) == 0

    archive_dir = tmp_path / "previous" / stamp
    assert (archive_dir / "model.front.png").read_text(encoding="utf-8") == "old-front"
    assert (archive_dir / "model.iso.png").read_text(encoding="utf-8") == "old-iso"
    assert (tmp_path / "model.front.png").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "model.iso.png").read_text(encoding="utf-8") == "new"
    assert unrequested.read_text(encoding="utf-8") == "old-top"
    assert capsys.readouterr().out.count("ARCHIVED:") == 2


def test_render_uses_suffix_when_archive_timestamp_collides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    output = tmp_path / "model.front.png"
    model.touch()
    output.write_text("original", encoding="utf-8")
    render_number = 0

    def working_renderer(
        _model: Path,
        destination: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        nonlocal render_number
        render_number += 1
        destination.write_text(f"render-{render_number}", encoding="utf-8")
        return True, ""

    stamp = "20260710T201234.123456Z"
    monkeypatch.setattr(render, "_archive_stamp", lambda: stamp)
    monkeypatch.setattr(render, "_detect", lambda: ["ldview"])
    monkeypatch.setitem(render.RENDERERS, "ldview", working_renderer)

    assert render.main([str(model), "--views", "front"]) == 0
    assert render.main([str(model), "--views", "front"]) == 0

    previous = tmp_path / "previous"
    assert (previous / stamp / output.name).read_text(encoding="utf-8") == "original"
    assert (previous / f"{stamp}-01" / output.name).read_text(
        encoding="utf-8"
    ) == "render-1"
    assert output.read_text(encoding="utf-8") == "render-2"


def test_render_removes_failed_and_missing_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    output = tmp_path / "model.front.png"
    model.touch()
    output.write_text("previous", encoding="utf-8")

    def partial_renderer(
        _model: Path,
        destination: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        destination.write_text("partial", encoding="utf-8")
        return False, "renderer failed"

    def empty_renderer(
        _model: Path,
        _destination: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        return True, ""

    stamp = "20260710T201234.123456Z"
    monkeypatch.setattr(render, "_archive_stamp", lambda: stamp)
    monkeypatch.setattr(render, "_detect", lambda: ["ldview", "leocad"])
    monkeypatch.setitem(render.RENDERERS, "ldview", partial_renderer)
    monkeypatch.setitem(render.RENDERERS, "leocad", empty_renderer)

    assert render.main([str(model), "--views", "front"]) == 1
    assert not output.exists()
    assert (tmp_path / "previous" / stamp / output.name).read_text(
        encoding="utf-8"
    ) == "previous"


def test_render_aborts_when_archiving_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    existing = tmp_path / "model.front.png"
    model.touch()
    existing.touch()
    renderer_called = False
    archive_error = PermissionError("archive is read-only")

    def working_renderer(
        _model: Path,
        _output: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        nonlocal renderer_called
        renderer_called = True
        return True, ""

    def failed_archive(_outputs: list[Path]) -> list[Path]:
        raise archive_error

    monkeypatch.setattr(render, "_detect", lambda: ["ldview"])
    monkeypatch.setattr(render, "_archive_existing", failed_archive)
    monkeypatch.setitem(render.RENDERERS, "ldview", working_renderer)

    assert render.main([str(model), "--views", "front"]) == 1
    assert not renderer_called
    assert existing.exists()


def test_render_falls_back_when_first_backend_produces_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    model.touch()
    calls: list[str] = []

    def failed_renderer(
        _model: Path,
        _output: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        calls.append("ldview")
        return False, "no display"

    def working_renderer(
        _model: Path,
        output: Path,
        _angle: tuple[int, int],
        _size: tuple[int, int],
    ) -> tuple[bool, str]:
        calls.append("leocad")
        output.touch()
        return True, ""

    monkeypatch.setattr(render, "_detect", lambda: ["ldview", "leocad"])
    monkeypatch.setitem(render.RENDERERS, "ldview", failed_renderer)
    monkeypatch.setitem(render.RENDERERS, "leocad", working_renderer)

    assert render.main([str(model), "--views", "front"]) == 0
    assert calls == ["ldview", "leocad"]
