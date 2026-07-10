"""Tests for the bundled lego-model-builder helper scripts."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

SKILL_DIR = Path(__file__).parents[1] / "skills" / "lego-model-builder"


def _load_script(name: str) -> ModuleType:
    path = SKILL_DIR / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_executable(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!/bin/sh\nprintf '{label}\\n' >> \"$PY_LOG\"\nexit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_preflight(tmp_path: Path, *, virtual_env: Path | None = None) -> list[str]:
    bin_dir = tmp_path / "bin"
    log = tmp_path / "python.log"
    _write_executable(bin_dir / "python", "python")
    _write_executable(bin_dir / "python3", "python3")
    _write_executable(bin_dir / "ldview", "ldview")

    env = {"PATH": str(bin_dir), "PY_LOG": str(log)}
    if virtual_env is not None:
        _write_executable(virtual_env / "bin" / "python", "venv-python")
        env["VIRTUAL_ENV"] = str(virtual_env)

    subprocess.run(
        ["/bin/bash", str(SKILL_DIR / "scripts" / "preflight.sh")],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return log.read_text(encoding="utf-8").splitlines()


def test_preflight_prefers_python3_without_virtualenv(tmp_path: Path) -> None:
    assert set(_run_preflight(tmp_path)) == {"python3"}


def test_preflight_prefers_activated_virtualenv(tmp_path: Path) -> None:
    virtual_env = tmp_path / "venv"
    assert set(_run_preflight(tmp_path, virtual_env=virtual_env)) == {"venv-python"}


def test_duplicate_detection_casefolds_part_names() -> None:
    geometry = _load_script("check_geometry")
    position = SimpleNamespace(x=0, y=0, z=0)
    colour = SimpleNamespace(code=4)
    pieces = [
        SimpleNamespace(part="3001.DAT", colour=colour, position=position),
        SimpleNamespace(part="3001.dat", colour=colour, position=position),
    ]

    assert geometry._find_duplicates(pieces) == [  # noqa: SLF001
        "duplicate: 2x part 3001.dat colour 4 at "
        "(0, 0, 0) — same piece placed on top of itself"
    ]


def test_povray_removes_intermediate_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = _load_script("render")
    model = tmp_path / "model.ldr"
    output = tmp_path / "model.iso.png"
    model.touch()

    monkeypatch.setattr(render.shutil, "which", lambda name: name == "ldview")

    def fake_run(cmd: list[str]) -> tuple[bool, str]:
        if cmd[0] == "ldview":
            output.with_suffix(".pov").touch()
        else:
            output.touch()
        return True, ""

    monkeypatch.setattr(render, "_run", fake_run)

    assert render._render_povray(  # noqa: SLF001
        model, output, (30, 45), (640, 480)
    )[0]
    assert not output.with_suffix(".pov").exists()


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
