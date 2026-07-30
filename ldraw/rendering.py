"""Deterministic, shell-free LeoCAD render orchestration."""

from __future__ import annotations

import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ldraw.serialization import format_ldraw_number

DEFAULT_RENDER_WIDTH = 1_024
DEFAULT_RENDER_HEIGHT = 768
DEFAULT_RENDER_TIMEOUT = 240.0
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MACOS_LEOCAD = Path("/Applications/LeoCAD.app/Contents/MacOS/leocad")

__all__ = [
    "DEFAULT_RENDER_HEIGHT",
    "DEFAULT_RENDER_TIMEOUT",
    "DEFAULT_RENDER_VIEWS",
    "DEFAULT_RENDER_WIDTH",
    "LeoCADRenderError",
    "RenderView",
    "RenderedView",
    "build_leocad_command",
    "find_leocad",
    "render_leocad",
]


@dataclass(frozen=True, slots=True)
class RenderView:
    """A named LeoCAD camera latitude/longitude pair in degrees."""

    name: str
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not _SAFE_NAME.fullmatch(self.name):
            msg = (
                "view name must start with an alphanumeric character and contain "
                "only alphanumerics, '.', '_', or '-'"
            )
            raise ValueError(msg)
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            msg = "view latitude must be finite and between -90 and 90 degrees"
            raise ValueError(msg)
        if not math.isfinite(self.longitude):
            msg = "view longitude must be finite"
            raise ValueError(msg)


DEFAULT_RENDER_VIEWS = (
    RenderView("front", 0, 0),
    RenderView("iso", 30, 45),
    RenderView("top", 89, 0),
)


@dataclass(frozen=True, slots=True)
class RenderedView:
    """A completed render and the exact shell-free command that produced it."""

    view: RenderView
    output: Path
    command: tuple[str, ...]


class LeoCADRenderError(RuntimeError):
    """LeoCAD could not render the complete requested view set."""

    def __init__(
        self,
        message: str,
        *,
        command: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.command = command


def find_leocad(executable: str | Path | None = None) -> Path | None:
    """Resolve an executable override, ``PATH``, or the standard macOS app."""
    if executable is not None:
        return (
            Path(resolved).resolve()
            if (resolved := shutil.which(str(executable))) is not None
            else None
        )
    if (resolved := shutil.which("leocad")) is not None:
        return Path(resolved).resolve()
    if _MACOS_LEOCAD.is_file():
        return _MACOS_LEOCAD
    return None


def build_leocad_command(  # noqa: PLR0913 - command fields stay explicit
    executable: Path,
    model: Path,
    output: Path,
    view: RenderView,
    *,
    width: int,
    height: int,
    xvfb_run: Path | None = None,
) -> tuple[str, ...]:
    """Build the exact argv used for one non-interactive LeoCAD render."""
    command = (
        str(executable),
        str(model),
        "--image",
        str(output),
        "--width",
        str(width),
        "--height",
        str(height),
        "--camera-angles",
        format_ldraw_number(view.latitude),
        format_ldraw_number(view.longitude),
    )
    if xvfb_run is None:
        return command
    return (
        str(xvfb_run),
        "-a",
        "-s",
        "-screen 0 1600x1200x24",
        *command,
    )


def render_leocad(  # noqa: C901, PLR0913 - render controls stay explicit
    model: str | Path,
    *,
    output_dir: str | Path | None = None,
    views: tuple[RenderView, ...] = DEFAULT_RENDER_VIEWS,
    prefix: str | None = None,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
    executable: str | Path | None = None,
    overwrite: bool = False,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
    use_xvfb: bool | None = None,
) -> tuple[RenderedView, ...]:
    """Render a complete deterministic view set with LeoCAD.

    Every view is rendered to a temporary directory first. Final files are
    replaced only after all renderer processes succeed and create an image, so
    a failed view never leaves a mixture of old, partial, and new outputs.
    Output names are ``PREFIX.VIEW.png`` in caller-supplied view order.

    ``use_xvfb=None`` automatically wraps LeoCAD on Linux when ``xvfb-run`` is
    available. Pass ``True`` to require it or ``False`` to run LeoCAD directly.
    """
    model_path = Path(model).resolve()
    if not model_path.is_file():
        message = f"model not found: {model_path}"
        raise LeoCADRenderError(message)
    if width <= 0 or height <= 0:
        msg = "render width and height must be positive"
        raise ValueError(msg)
    if timeout <= 0:
        msg = "render timeout must be positive"
        raise ValueError(msg)
    if not views:
        msg = "at least one render view is required"
        raise ValueError(msg)
    names = tuple(view.name for view in views)
    if len(set(names)) != len(names):
        msg = "render view names must be unique"
        raise ValueError(msg)

    output_prefix = prefix if prefix is not None else model_path.stem
    if not _SAFE_NAME.fullmatch(output_prefix):
        msg = (
            "render prefix must start with an alphanumeric character and contain "
            "only alphanumerics, '.', '_', or '-'"
        )
        raise ValueError(msg)
    destination = (
        Path(output_dir).resolve() if output_dir is not None else model_path.parent
    )
    outputs = tuple(destination / f"{output_prefix}.{name}.png" for name in names)
    conflicts = tuple(output for output in outputs if output.exists())
    if conflicts and not overwrite:
        rendered = ", ".join(str(output) for output in conflicts)
        message = f"output already exists: {rendered}"
        raise LeoCADRenderError(message)

    if (leocad := find_leocad(executable)) is None:
        requested = str(executable) if executable is not None else "leocad"
        message = f"LeoCAD executable not found: {requested}"
        raise LeoCADRenderError(message)
    xvfb_run = _find_xvfb(use_xvfb=use_xvfb)

    destination.mkdir(parents=True, exist_ok=True)
    completed: list[tuple[RenderView, Path, tuple[str, ...]]] = []
    with tempfile.TemporaryDirectory(prefix=".pyldraw-render-", dir=destination) as tmp:
        temporary_dir = Path(tmp)
        for view, output in zip(views, outputs, strict=True):
            temporary_output = temporary_dir / output.name
            command = build_leocad_command(
                leocad,
                model_path,
                temporary_output,
                view,
                width=width,
                height=height,
                xvfb_run=xvfb_run,
            )
            _run_leocad(command, output=temporary_output, timeout=timeout)
            completed.append((view, temporary_output, command))

        results: list[RenderedView] = []
        for view, temporary_output, command in completed:
            output = destination / temporary_output.name
            temporary_output.replace(output)
            results.append(RenderedView(view=view, output=output, command=command))
    return tuple(results)


def _find_xvfb(*, use_xvfb: bool | None) -> Path | None:
    if use_xvfb is False or (use_xvfb is None and platform.system() != "Linux"):
        return None
    resolved = shutil.which("xvfb-run")
    if resolved is not None:
        return Path(resolved).resolve()
    if use_xvfb:
        message = "xvfb-run was required but was not found"
        raise LeoCADRenderError(message)
    return None


def _run_leocad(
    command: tuple[str, ...],
    *,
    output: Path,
    timeout: float,
) -> None:
    environment = os.environ.copy()
    environment.update({"LANG": "C", "LC_ALL": "C"})
    try:
        process = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        message = f"LeoCAD timed out after {format_ldraw_number(timeout)} seconds"
        raise LeoCADRenderError(
            message,
            command=command,
        ) from error
    except OSError as error:
        raise LeoCADRenderError(str(error), command=command) from error
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        message = f"LeoCAD exited with status {process.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise LeoCADRenderError(message, command=command)
    if not output.is_file():
        message = "LeoCAD exited successfully without producing an image"
        raise LeoCADRenderError(
            message,
            command=command,
        )
