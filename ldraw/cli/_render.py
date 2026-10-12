"""Runtime services for the render commands."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from ldraw.cli._common import _print_diagnostics
from ldraw.cli._defaults import _SAFE_RENDER_PREFIX, DEFAULT_RENDER_VIEWS
from ldraw.rendering import RenderBackend, RenderResult, RenderView, render_preview


@dataclass(frozen=True, slots=True)
class _RenderPlan:
    """Validated paths and options for one atomic render operation."""

    source: Path
    views: tuple[RenderView, ...]
    dimensions: tuple[int, int]
    backend: RenderBackend | None
    destination: Path
    outputs: tuple[Path, ...]
    refresh: bool
    overwrite: bool


def render_command(  # noqa: PLR0913 - explicit CLI controls
    *,
    file: Path,
    views: list[RenderView] | None,
    size: str,
    backend: str,
    output_dir: Path | None,
    prefix: str | None,
    refresh: bool,
    overwrite: bool,
) -> int:
    """Render a safe, deterministic standard-view set."""
    source = file.expanduser().resolve()
    if not source.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    try:
        plan = _build_render_plan(
            source=source,
            views=views,
            size=size,
            backend=backend,
            output_dir=output_dir,
            prefix=prefix,
            refresh=refresh,
            overwrite=overwrite,
        )
        staged_results = _execute_render_plan(plan)
    except (OSError, ValueError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1
    if staged_results is None:
        return 1

    _report_render_results(results=staged_results, outputs=plan.outputs)
    return 0


def _parse_render_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.casefold().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        message = f"bad size {value!r}; expected WIDTHxHEIGHT"
        raise ValueError(message) from exc
    if width <= 0 or height <= 0:
        message = "render width and height must be positive"
        raise ValueError(message)
    return width, height


def _build_render_plan(  # noqa: PLR0913 - mirrors explicit CLI controls
    *,
    source: Path,
    views: list[RenderView] | None,
    size: str,
    backend: str,
    output_dir: Path | None,
    prefix: str | None,
    refresh: bool,
    overwrite: bool,
) -> _RenderPlan:
    """Validate a render request and resolve all output paths up front."""
    dimensions = _parse_render_size(size)
    requested_views = tuple(views) if views is not None else DEFAULT_RENDER_VIEWS
    if len(set(requested_views)) != len(requested_views):
        message = "render views must be unique"
        raise ValueError(message)

    output_prefix = prefix if prefix is not None else source.stem
    if not _SAFE_RENDER_PREFIX.fullmatch(output_prefix):
        message = (
            "render prefix must start with an alphanumeric character and contain "
            "only alphanumerics, '.', '_', or '-'"
        )
        raise ValueError(message)

    destination = (
        output_dir.expanduser().resolve() if output_dir is not None else source.parent
    )
    outputs = tuple(
        destination / f"{output_prefix}.{view.value}.png" for view in requested_views
    )
    if conflicts := tuple(output for output in outputs if output.exists()):
        names = ", ".join(str(output) for output in conflicts)
        if not overwrite:
            message = f"output already exists: {names}"
            raise FileExistsError(message)

    selected_backend = None if backend == "auto" else RenderBackend(backend)
    return _RenderPlan(
        source=source,
        views=requested_views,
        dimensions=dimensions,
        backend=selected_backend,
        destination=destination,
        outputs=outputs,
        refresh=refresh,
        overwrite=overwrite,
    )


def _execute_render_plan(plan: _RenderPlan) -> tuple[RenderResult, ...] | None:
    """Stage every view and atomically promote the complete render set."""
    plan.destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".pyldraw-render-",
        dir=plan.destination,
    ) as tmp:
        temporary = Path(tmp)
        staged_results: list[RenderResult] = []
        for view, output in zip(plan.views, plan.outputs, strict=True):
            result = render_preview(
                plan.source,
                view=view,
                size=plan.dimensions,
                backend=plan.backend,
                output=temporary / output.name,
                refresh=plan.refresh,
            )
            if not result.complete:
                _print_diagnostics(result.diagnostics, fallback_path=plan.source)
                return None
            staged_results.append(result)
        results = tuple(staged_results)
        _promote_render_outputs(
            results,
            outputs=plan.outputs,
            temporary=temporary,
            overwrite=plan.overwrite,
        )
    return results


def _report_render_results(
    *,
    results: tuple[RenderResult, ...],
    outputs: tuple[Path, ...],
) -> None:
    """Print the final location and cache status of each rendered view."""
    for result, output in zip(results, outputs, strict=True):
        status = "CACHED" if result.cached else "RENDERED"
        print(f"{status}: {output}")


def _promote_render_outputs(
    results: tuple[RenderResult, ...],
    *,
    outputs: tuple[Path, ...],
    temporary: Path,
    overwrite: bool,
) -> None:
    """Promote a complete staged view set, rolling back destination changes."""
    backups_dir = temporary / ".backups"
    backups: dict[Path, Path] = {}
    promoted: set[Path] = set()
    try:
        for index, (result, output) in enumerate(zip(results, outputs, strict=True)):
            staged = _render_result_output(result)
            backup = _backup_render_output(
                output,
                backup=backups_dir / f"{index}-{output.name}",
                overwrite=overwrite,
            )
            if backup is not None:
                backups[output] = backup
            staged.replace(output)
            promoted.add(output)
    except OSError as exc:
        rollback_errors = _rollback_render_outputs(
            outputs,
            promoted=promoted,
            backups=backups,
        )
        if rollback_errors:
            message = (
                f"{exc}; additionally could not restore {'; '.join(rollback_errors)}"
            )
            raise OSError(message) from exc
        raise


def _render_result_output(result: RenderResult) -> Path:
    if result.output is None:
        message = f"render result for {result.view.value} has no output"
        raise OSError(message)
    return result.output


def _backup_render_output(
    output: Path,
    *,
    backup: Path,
    overwrite: bool,
) -> Path | None:
    if not output.exists():
        return None
    if not overwrite:
        message = f"output already exists: {output}"
        raise FileExistsError(message)
    backup.parent.mkdir(exist_ok=True)
    output.replace(backup)
    return backup


def _rollback_render_outputs(
    outputs: tuple[Path, ...],
    *,
    promoted: set[Path],
    backups: dict[Path, Path],
) -> list[str]:
    errors: list[str] = []
    for output in reversed(outputs):
        try:
            if output in promoted:
                output.unlink(missing_ok=True)
            if (backup := backups.get(output)) is not None and backup.exists():
                backup.replace(output)
        except OSError as exc:
            errors.append(f"{output}: {exc}")
    return errors
