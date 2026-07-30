"""Tests for deterministic LeoCAD render orchestration."""

import subprocess
from pathlib import Path

import pytest

from ldraw.rendering import (
    LeoCADRenderError,
    RenderView,
    _find_xvfb,
    build_leocad_command,
    render_leocad,
)


def test_build_leocad_command_has_stable_camera_and_xvfb_arguments() -> None:
    command = build_leocad_command(
        Path("/opt/leocad"),
        Path("/models/scout.mpd"),
        Path("/renders/scout.iso.png"),
        RenderView("iso", 30, 45),
        width=1_024,
        height=768,
        xvfb_run=Path("/usr/bin/xvfb-run"),
    )

    assert command == (
        "/usr/bin/xvfb-run",
        "-a",
        "-s",
        "-screen 0 1600x1200x24",
        "/opt/leocad",
        "/models/scout.mpd",
        "--image",
        "/renders/scout.iso.png",
        "--width",
        "1024",
        "--height",
        "768",
        "--camera-angles",
        "30",
        "45",
    )


def test_render_leocad_writes_named_views_after_complete_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    output_dir = tmp_path / "renders"

    monkeypatch.setattr(
        "ldraw.rendering.find_leocad",
        lambda _executable=None: Path("/opt/leocad"),
    )

    def successful_run(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--image") + 1])
        output.write_text(output.name, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("ldraw.rendering.subprocess.run", successful_run)
    views = (RenderView("front", 0, 0), RenderView("rear", 0, 180))

    results = render_leocad(
        model,
        output_dir=output_dir,
        views=views,
        prefix="baseline",
        use_xvfb=False,
    )

    assert [result.output.name for result in results] == [
        "baseline.front.png",
        "baseline.rear.png",
    ]
    assert all(result.output.is_file() for result in results)
    assert "--camera-angles" in results[1].command
    assert results[1].command[-2:] == ("0", "180")


def test_render_failure_preserves_every_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    output_dir = tmp_path / "renders"
    output_dir.mkdir()
    front = output_dir / "baseline.front.png"
    rear = output_dir / "baseline.rear.png"
    front.write_text("old front", encoding="utf-8")
    rear.write_text("old rear", encoding="utf-8")

    monkeypatch.setattr(
        "ldraw.rendering.find_leocad",
        lambda _executable=None: Path("/opt/leocad"),
    )
    call_number = 0

    def partially_successful_run(
        command,
        **_kwargs,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal call_number
        call_number += 1
        if call_number == 1:
            output = Path(command[command.index("--image") + 1])
            output.write_text("new front", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="bad camera")

    monkeypatch.setattr("ldraw.rendering.subprocess.run", partially_successful_run)

    with pytest.raises(LeoCADRenderError, match="status 2"):
        render_leocad(
            model,
            output_dir=output_dir,
            views=(RenderView("front", 0, 0), RenderView("rear", 0, 180)),
            prefix="baseline",
            overwrite=True,
            use_xvfb=False,
        )

    assert front.read_text(encoding="utf-8") == "old front"
    assert rear.read_text(encoding="utf-8") == "old rear"
    assert not tuple(output_dir.glob(".pyldraw-render-*"))


def test_existing_output_is_rejected_before_renderer_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    (tmp_path / "vehicle.front.png").write_text("keep", encoding="utf-8")
    detected = False

    def find_renderer(_executable=None) -> Path:
        nonlocal detected
        detected = True
        return Path("/opt/leocad")

    monkeypatch.setattr("ldraw.rendering.find_leocad", find_renderer)

    with pytest.raises(LeoCADRenderError, match="already exists"):
        render_leocad(
            model,
            views=(RenderView("front", 0, 0),),
            use_xvfb=False,
        )

    assert not detected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"width": 0}, "positive"),
        ({"timeout": 0}, "positive"),
        ({"views": ()}, "at least one"),
        (
            {
                "views": (
                    RenderView("same", 0, 0),
                    RenderView("same", 10, 10),
                ),
            },
            "unique",
        ),
        ({"prefix": "../escape"}, "prefix"),
    ],
)
def test_render_leocad_validates_the_complete_request_before_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    detected = False

    def find_renderer(_executable=None) -> Path:
        nonlocal detected
        detected = True
        return Path("/opt/leocad")

    monkeypatch.setattr("ldraw.rendering.find_leocad", find_renderer)

    with pytest.raises(ValueError, match=message):
        render_leocad(model, use_xvfb=False, **kwargs)

    assert not detected


def test_render_leocad_reports_missing_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    monkeypatch.setattr("ldraw.rendering.find_leocad", lambda _executable=None: None)

    with pytest.raises(LeoCADRenderError, match="not found"):
        render_leocad(model, executable="missing-leocad", use_xvfb=False)


def test_find_leocad_checks_override_path_and_macos_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "leocad"
    executable.touch(mode=0o755)
    monkeypatch.setattr(
        "ldraw.rendering.shutil.which",
        lambda name: str(executable) if name in {"custom", "leocad"} else None,
    )

    from ldraw.rendering import find_leocad

    assert find_leocad("custom") == executable.resolve()
    assert find_leocad("missing") is None
    assert find_leocad() == executable.resolve()

    monkeypatch.setattr("ldraw.rendering.shutil.which", lambda _name: None)
    monkeypatch.setattr("ldraw.rendering._MACOS_LEOCAD", executable)
    assert find_leocad() == executable
    executable.unlink()
    assert find_leocad() is None


def test_render_leocad_rejects_missing_model(tmp_path: Path) -> None:
    with pytest.raises(LeoCADRenderError, match="model not found"):
        render_leocad(tmp_path / "missing.mpd")


def test_xvfb_detection_supports_auto_required_and_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xvfb = tmp_path / "xvfb-run"
    xvfb.touch()
    monkeypatch.setattr("ldraw.rendering.platform.system", lambda: "Linux")
    monkeypatch.setattr("ldraw.rendering.shutil.which", lambda _name: str(xvfb))

    assert _find_xvfb(use_xvfb=None) == xvfb.resolve()
    assert _find_xvfb(use_xvfb=True) == xvfb.resolve()
    assert _find_xvfb(use_xvfb=False) is None

    monkeypatch.setattr("ldraw.rendering.shutil.which", lambda _name: None)
    assert _find_xvfb(use_xvfb=None) is None
    with pytest.raises(LeoCADRenderError, match="required"):
        _find_xvfb(use_xvfb=True)


def test_render_leocad_reports_timeout_and_missing_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tmp_path / "vehicle.mpd"
    model.write_text("0 vehicle\n", encoding="utf-8")
    monkeypatch.setattr(
        "ldraw.rendering.find_leocad",
        lambda _executable=None: Path("/opt/leocad"),
    )

    def timeout_run(command, **_kwargs) -> None:
        raise subprocess.TimeoutExpired(command, 2)

    monkeypatch.setattr("ldraw.rendering.subprocess.run", timeout_run)
    with pytest.raises(LeoCADRenderError, match="timed out"):
        render_leocad(
            model,
            views=(RenderView("front", 0, 0),),
            timeout=2,
            use_xvfb=False,
        )

    def empty_run(command, **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("ldraw.rendering.subprocess.run", empty_run)
    with pytest.raises(LeoCADRenderError, match="without producing"):
        render_leocad(
            model,
            views=(RenderView("front", 0, 0),),
            use_xvfb=False,
        )

    def os_error_run(command, **_kwargs) -> None:
        message = "not executable"
        raise PermissionError(message)

    monkeypatch.setattr("ldraw.rendering.subprocess.run", os_error_run)
    with pytest.raises(LeoCADRenderError, match="not executable"):
        render_leocad(
            model,
            views=(RenderView("front", 0, 0),),
            use_xvfb=False,
        )


@pytest.mark.parametrize(
    ("name", "latitude", "longitude"),
    [("../escape", 0, 0), ("top", 91, 0), ("top", 0, float("nan"))],
)
def test_render_view_rejects_unsafe_or_invalid_values(
    name: str,
    latitude: float,
    longitude: float,
) -> None:
    with pytest.raises(ValueError):
        RenderView(name, latitude, longitude)
