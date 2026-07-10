#!/usr/bin/env python3
"""Render an LDraw model to PNGs from several camera angles.

Auto-detects a renderer on PATH in the order ldview -> leocad and produces
<prefix>.front.png, <prefix>.iso.png, <prefix>.top.png.

Usage:
    python render.py MODEL.ldr [--prefix NAME] [--size WxH] [--views front,iso,top]

Existing requested-view images move to previous/<UTC timestamp>/ before
replacement. Prints `ARCHIVED: <path>` and `RENDERED: <path>` lines plus a final
summary. Exits 0 if at least one image was written, 1 if none.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# (latitude, longitude) in degrees for each named view.
VIEWS: dict[str, tuple[int, int]] = {
    "front": (0, 0),
    "iso": (30, 45),
    "top": (89, 0),
}

RENDER_TIMEOUT_S = 240
RENDERER_PRIORITY = ("ldview", "leocad")


@dataclass(frozen=True)
class RenderRequest:
    """Validated inputs and output paths for one render invocation."""

    model: Path
    outputs: dict[str, Path]
    renderers: list[str]
    size: tuple[int, int]
    views: list[str]


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        # Renderer arguments are passed directly; shell execution is disabled.
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=RENDER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {RENDER_TIMEOUT_S}s: {' '.join(cmd)}"
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()
    return True, ""


def _detect() -> list[str]:
    return [renderer for renderer in RENDERER_PRIORITY if shutil.which(renderer)]


def _render_ldview(
    model: Path,
    out: Path,
    angle: tuple[int, int],
    size: tuple[int, int],
) -> tuple[bool, str]:
    lat, lon = angle
    width, height = size
    return _run(
        [
            "ldview",
            str(model),
            f"-SaveSnapshot={out}",
            f"-SaveWidth={width}",
            f"-SaveHeight={height}",
            f"-DefaultLatLong={lat},{lon}",
            "-AutoCrop=1",
            "-SaveAlpha=0",
        ]
    )


def _render_leocad(
    model: Path,
    out: Path,
    angle: tuple[int, int],
    size: tuple[int, int],
) -> tuple[bool, str]:
    lat, lon = angle
    width, height = size
    cmd = [
        "leocad",
        str(model),
        "--image",
        str(out),
        "--width",
        str(width),
        "--height",
        str(height),
        "--camera-angles",
        str(lat),
        str(lon),
    ]
    # LeoCAD renders through OpenGL; on headless Linux wrap it in Xvfb.
    if platform.system() == "Linux" and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1600x1200x24", *cmd]
    return _run(cmd)


RENDERERS = {
    "ldview": _render_ldview,
    "leocad": _render_leocad,
}


def _parse_views(value: str) -> list[str]:
    views: list[str] = []
    for view in (item.strip() for item in value.split(",") if item.strip()):
        if view not in VIEWS:
            print(f"skipping unknown view {view!r}", file=sys.stderr)
            continue
        views.append(view)
    return views


def _archive_stamp() -> str:
    """Return a sortable UTC timestamp for a render-history directory."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _create_archive_dir(out_dir: Path) -> Path:
    """Create a unique directory for one prior render set."""
    archive_root = out_dir / "previous"
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = _archive_stamp()
    suffix = 0
    while True:
        name = stamp if suffix == 0 else f"{stamp}-{suffix:02d}"
        candidate = archive_root / name
        try:
            candidate.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def _archive_existing(outputs: list[Path]) -> list[Path]:
    """Move existing requested outputs into one timestamped history directory."""
    existing = [output for output in outputs if output.is_file()]
    if not existing:
        return []

    archive_dir = _create_archive_dir(existing[0].parent)
    archived: list[Path] = []
    for output in existing:
        destination = archive_dir / output.name
        output.replace(destination)
        archived.append(destination)
    return archived


def _remove_partial_output(output: Path) -> str | None:
    """Remove a failed renderer's output and return any cleanup error."""
    try:
        output.unlink(missing_ok=True)
    except OSError as exc:
        return str(exc)
    return None


def _prepare_request(args: argparse.Namespace) -> RenderRequest | None:
    """Validate CLI arguments without changing existing render files."""
    model: Path = args.model
    if not model.is_file():
        print(f"error: model not found: {model}", file=sys.stderr)
        return None

    try:
        width_s, height_s = args.size.lower().split("x", 1)
        size = (int(width_s), int(height_s))
    except ValueError:
        print(
            f"error: bad --size {args.size!r}; expected WxH like 1024x768",
            file=sys.stderr,
        )
        return None

    views = _parse_views(args.views)
    if not views:
        print("error: no valid views specified", file=sys.stderr)
        return None

    renderers = _detect()
    if not renderers:
        print(
            "renderer: NONE — no ldview/leocad on PATH; cannot render. "
            "Run preflight.sh or install LDView.",
            file=sys.stderr,
        )
        return None

    prefix = args.prefix or model.stem
    out_dir = model.resolve().parent
    outputs = {view: out_dir / f"{prefix}.{view}.png" for view in views}
    return RenderRequest(
        model=model,
        outputs=outputs,
        renderers=renderers,
        size=size,
        views=views,
    )


def _render_with_backend(request: RenderRequest, renderer: str) -> list[Path]:
    """Render all requested views with one backend."""
    print(f"renderer: {renderer}", file=sys.stderr)
    render_fn = RENDERERS[renderer]
    produced: list[Path] = []
    for view in request.views:
        out = request.outputs[view]
        if cleanup_error := _remove_partial_output(out):
            message = f"could not remove stale output: {cleanup_error}"
            print(f"failed {view} view: {message}", file=sys.stderr)
            continue

        ok, err = render_fn(request.model, out, VIEWS[view], request.size)
        if ok and out.is_file():
            produced.append(out)
            print(f"RENDERED: {out}")
            continue

        cleanup_error = _remove_partial_output(out)
        if not err:
            err = "renderer exited without producing an image"
        if cleanup_error:
            err = f"{err}; could not remove partial output: {cleanup_error}"
        print(f"failed {view} view: {err}", file=sys.stderr)
    return produced


def main(argv: list[str] | None = None) -> int:
    """Render requested model views and return whether any image was produced."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="path to the .ldr/.mpd model")
    parser.add_argument(
        "--prefix",
        default=None,
        help="output name stem (default: model stem)",
    )
    parser.add_argument(
        "--size",
        default="1024x768",
        help="image size WxH (default 1024x768)",
    )
    parser.add_argument(
        "--views",
        default="front,iso,top",
        help="comma-separated subset of: " + ",".join(VIEWS),
    )
    args = parser.parse_args(argv)
    request = _prepare_request(args)
    if request is None:
        return 1

    try:
        archived = _archive_existing(list(request.outputs.values()))
    except OSError as exc:
        print(f"error: could not archive previous renders: {exc}", file=sys.stderr)
        return 1
    for path in archived:
        print(f"ARCHIVED: {path}")

    for renderer in request.renderers:
        produced = _render_with_backend(request, renderer)
        if produced:
            print(
                f"Rendered {len(produced)} view(s) with {renderer}.",
                file=sys.stderr,
            )
            return 0
        print(f"{renderer} produced no images; trying next renderer.", file=sys.stderr)

    print("No images produced.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
