"""Optional, feature-detected single-view preview rendering."""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile

from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.dirs import get_cache_dir
from ldraw.operations import CancellationToken, OperationCancelled, check_cancelled
from ldraw.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    ProgressUnit,
    emit_progress,
)

_RENDER_TIMEOUT_SECONDS = 240


class RenderBackend(StrEnum):
    """Supported optional command-line renderers, in preference order."""

    LDVIEW = "ldview"
    LEOCAD = "leocad"


class RenderView(StrEnum):
    """Stable named preview viewpoints."""

    FRONT = "front"
    ISOMETRIC = "isometric"
    TOP = "top"


_VIEW_ANGLES: dict[RenderView, tuple[int, int]] = {
    RenderView.FRONT: (0, 0),
    RenderView.ISOMETRIC: (30, 45),
    RenderView.TOP: (89, 0),
}


@dataclass(frozen=True, slots=True)
class RenderCapability:
    """Availability and executable path for one optional backend."""

    backend: RenderBackend
    available: bool
    executable: Path | None


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Output or diagnostics from one preview request."""

    source: Path
    view: RenderView
    size: tuple[int, int]
    backend: RenderBackend | None
    output: Path | None
    cached: bool
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def complete(self) -> bool:
        """Return whether a usable image was produced."""
        return self.output is not None and self.output.is_file()


def render_capabilities() -> tuple[RenderCapability, ...]:
    """Detect optional renderers without invoking them."""
    return tuple(
        RenderCapability(
            backend=backend,
            available=(resolved := shutil.which(backend.value)) is not None,
            executable=Path(resolved) if resolved is not None else None,
        )
        for backend in RenderBackend
    )


def render_preview(  # noqa: PLR0913 - public render options are explicit
    source: str | Path,
    *,
    view: RenderView = RenderView.ISOMETRIC,
    size: tuple[int, int] = (800, 600),
    backend: RenderBackend | None = None,
    output: str | Path | None = None,
    cache_path: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
    cancellation: CancellationToken | None = None,
) -> RenderResult:
    """Render one view, using a content-addressed PNG cache when possible."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        return _render_error_result(
            source=source_path,
            view=view,
            size=size,
            backend=None,
            message=f"Render source does not exist: {source_path}",
        )
    width, height = size
    if width <= 0 or height <= 0:
        message = "render size must contain positive dimensions"
        raise ValueError(message)
    check_cancelled(cancellation)
    available = _available_renderers()
    selected = backend or next(iter(available), None)
    if selected is None or selected not in available:
        return _render_error_result(
            source=source_path,
            view=view,
            size=size,
            backend=selected,
            message=(
                f"Renderer {selected.value!r} is unavailable"
                if selected is not None
                else "No supported preview renderer is available"
            ),
            severity=Severity.WARNING,
            code=DiagnosticCode.RENDER_UNAVAILABLE,
            offending_value=selected.value if selected is not None else None,
        )
    try:
        cache_root, cached_path, requested_output = _render_paths(
            source=source_path,
            backend=selected,
            view=view,
            size=size,
            output=output,
            cache_path=cache_path,
        )
        if cached := _cached_result(
            source=source_path,
            view=view,
            size=size,
            backend=selected,
            cached_path=cached_path,
            requested_output=requested_output,
        ):
            return cached
    except OSError as exc:
        return _render_error_result(
            source=source_path,
            view=view,
            size=size,
            backend=selected,
            message=f"Could not read or write preview cache: {exc}",
            offending_value=selected.value,
            cause=exc,
        )
    return _render_uncached(
        source=source_path,
        view=view,
        size=size,
        backend=selected,
        executable=available[selected].executable,
        cache_root=cache_root,
        cached_path=cached_path,
        requested_output=requested_output,
        on_progress=on_progress,
        cancellation=cancellation,
    )


def _available_renderers() -> dict[RenderBackend, RenderCapability]:
    return {
        capability.backend: capability
        for capability in render_capabilities()
        if capability.available
    }


def _render_paths(  # noqa: PLR0913 - cache identity inputs are explicit
    *,
    source: Path,
    backend: RenderBackend,
    view: RenderView,
    size: tuple[int, int],
    output: str | Path | None,
    cache_path: str | Path | None,
) -> tuple[Path, Path, Path]:
    cache_root = (
        Path(cache_path).expanduser()
        if cache_path is not None
        else Path(get_cache_dir()) / "previews"
    )
    width, height = size
    digest = hashlib.sha256()
    digest.update(source.read_bytes())
    digest.update(f"\0{backend.value}\0{view.value}\0{width}x{height}".encode())
    cached_path = cache_root / f"{digest.hexdigest()}.png"
    requested_output = Path(output).expanduser() if output is not None else cached_path
    return cache_root, cached_path, requested_output


def _cached_result(  # noqa: PLR0913 - result identity fields are explicit
    *,
    source: Path,
    view: RenderView,
    size: tuple[int, int],
    backend: RenderBackend,
    cached_path: Path,
    requested_output: Path,
) -> RenderResult | None:
    if not cached_path.is_file() or not cached_path.stat().st_size:
        return None
    if requested_output != cached_path:
        requested_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached_path, requested_output)
    return RenderResult(
        source=source,
        view=view,
        size=size,
        backend=backend,
        output=requested_output,
        cached=True,
    )


def _render_uncached(  # noqa: PLR0913 - renderer operation state is explicit
    *,
    source: Path,
    view: RenderView,
    size: tuple[int, int],
    backend: RenderBackend,
    executable: Path | None,
    cache_root: Path,
    cached_path: Path,
    requested_output: Path,
    on_progress: ProgressCallback | None,
    cancellation: CancellationToken | None,
) -> RenderResult:
    temporary_path: Path | None = None
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.RENDER,
                message=f"Rendering {view.value} preview",
                current=0,
                total=1,
                path=source,
                unit=ProgressUnit.VIEWS,
            ),
        )
        with NamedTemporaryFile(
            dir=cache_root,
            prefix=".preview-",
            suffix=".png",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        command = _render_command(
            backend=backend,
            executable=executable,
            source=source,
            output=temporary_path,
            view=view,
            size=size,
        )
        completed = _run_renderer(command, cancellation=cancellation)
        if (
            completed.returncode != 0
            or not temporary_path.is_file()
            or not temporary_path.stat().st_size
        ):
            detail = (completed.stderr or completed.stdout or "").strip()
            message = detail or "renderer exited without producing an image"
            return _render_error_result(
                source=source,
                view=view,
                size=size,
                backend=backend,
                message=f"Preview rendering failed: {message}",
                offending_value=backend.value,
            )
        temporary_path.replace(cached_path)
        temporary_path = None
        if requested_output != cached_path:
            requested_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_path, requested_output)
        emit_progress(
            on_progress,
            ProgressEvent(
                stage=ProgressStage.RENDER,
                message=f"Rendered {view.value} preview",
                current=1,
                total=1,
                path=requested_output,
                unit=ProgressUnit.VIEWS,
            ),
        )
        return RenderResult(
            source=source,
            view=view,
            size=size,
            backend=backend,
            output=requested_output,
            cached=False,
        )
    except OperationCancelled:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        return _render_error_result(
            source=source,
            view=view,
            size=size,
            backend=backend,
            message=f"Preview rendering failed: {exc}",
            offending_value=backend.value,
            cause=exc,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _render_error_result(  # noqa: PLR0913 - diagnostic context is explicit
    *,
    source: Path,
    view: RenderView,
    size: tuple[int, int],
    backend: RenderBackend | None,
    message: str,
    severity: Severity = Severity.ERROR,
    code: DiagnosticCode = DiagnosticCode.RENDER_FAILED,
    offending_value: str | None = None,
    cause: BaseException | None = None,
) -> RenderResult:
    diagnostic = Diagnostic(
        line_number=None,
        message=message,
        severity=severity,
        code=code,
        path=source,
        offending_value=offending_value,
        cause=cause,
    )
    return RenderResult(
        source=source,
        view=view,
        size=size,
        backend=backend,
        output=None,
        cached=False,
        diagnostics=(diagnostic,),
    )


def _render_command(  # noqa: PLR0913 - renderer command fields are explicit
    *,
    backend: RenderBackend,
    executable: Path | None,
    source: Path,
    output: Path,
    view: RenderView,
    size: tuple[int, int],
) -> list[str]:
    if executable is None:
        message = f"No executable for {backend.value}"
        raise FileNotFoundError(message)
    latitude, longitude = _VIEW_ANGLES[view]
    width, height = size
    match backend:
        case RenderBackend.LDVIEW:
            return [
                str(executable),
                str(source),
                f"-SaveSnapshot={output}",
                f"-SaveWidth={width}",
                f"-SaveHeight={height}",
                f"-DefaultLatLong={latitude},{longitude}",
                "-AutoCrop=1",
                "-SaveAlpha=0",
            ]
        case RenderBackend.LEOCAD:
            command = [
                str(executable),
                str(source),
                "--image",
                str(output),
                "--width",
                str(width),
                "--height",
                str(height),
                "--camera-angles",
                str(latitude),
                str(longitude),
            ]
            if platform.system() == "Linux" and (xvfb := shutil.which("xvfb-run")):
                return [xvfb, "-a", "-s", "-screen 0 1600x1200x24", *command]
            return command


def _run_renderer(
    command: list[str],
    *,
    cancellation: CancellationToken | None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    deadline = time.monotonic() + _RENDER_TIMEOUT_SECONDS
    while process.poll() is None:
        try:
            check_cancelled(cancellation)
        except OperationCancelled:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            raise subprocess.TimeoutExpired(command, _RENDER_TIMEOUT_SECONDS)
        time.sleep(0.05)
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


__all__ = [
    "RenderBackend",
    "RenderCapability",
    "RenderResult",
    "RenderView",
    "render_capabilities",
    "render_preview",
]
