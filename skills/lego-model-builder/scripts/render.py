#!/usr/bin/env python3
"""Render an LDraw model to PNGs from several camera angles.

Auto-detects a renderer on PATH in the order ldview -> leocad -> povray and
produces <prefix>.front.png, <prefix>.iso.png, <prefix>.top.png.

Usage:
    python render.py MODEL.ldr [--prefix NAME] [--size WxH] [--views front,iso,top]

Prints one `RENDERED: <path>` line per image produced and a final summary.
Exits 0 if at least one image was written, 1 if none (e.g. no renderer).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

# (latitude, longitude) in degrees for each named view.
VIEWS: dict[str, tuple[int, int]] = {
    "front": (0, 0),
    "iso": (30, 45),
    "top": (89, 0),
}

RENDER_TIMEOUT_S = 240
RENDERER_PRIORITY = ("ldview", "leocad", "povray")


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
    except FileNotFoundError as exc:
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


def _render_povray(
    model: Path,
    out: Path,
    angle: tuple[int, int],
    size: tuple[int, int],
) -> tuple[bool, str]:
    # Convert LDraw -> POV first (needs ldview -ExportFile or l3p), then raytrace.
    lat, lon = angle
    width, height = size
    pov = out.with_suffix(".pov")
    try:
        if shutil.which("ldview"):
            ok, err = _run(
                [
                    "ldview",
                    str(model),
                    f"-ExportFile={pov}",
                    f"-DefaultLatLong={lat},{lon}",
                ]
            )
        elif shutil.which("l3p"):
            ok, err = _run(["l3p", str(model), str(pov), f"-cg{lat},{lon}"])
        else:
            return (
                False,
                "povray needs 'ldview' or 'l3p' to convert LDraw to .pov first",
            )
        if not ok:
            return False, f"LDraw->POV conversion failed: {err}"
        return _run(
            [
                "povray",
                f"+I{pov}",
                f"+O{out}",
                f"+W{width}",
                f"+H{height}",
                "-D",
                "+A0.3",
                "+UA",
            ]
        )
    finally:
        with suppress(OSError):
            pov.unlink(missing_ok=True)


RENDERERS = {
    "ldview": _render_ldview,
    "leocad": _render_leocad,
    "povray": _render_povray,
}


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

    model: Path = args.model
    if not model.is_file():
        print(f"error: model not found: {model}", file=sys.stderr)
        return 1

    try:
        width_s, height_s = args.size.lower().split("x", 1)
        width, height = int(width_s), int(height_s)
    except ValueError:
        print(
            f"error: bad --size {args.size!r}; expected WxH like 1024x768",
            file=sys.stderr,
        )
        return 1

    renderers = _detect()
    if not renderers:
        print(
            "renderer: NONE — no ldview/leocad/povray on PATH; cannot render. "
            "Run preflight.sh or install LDView.",
            file=sys.stderr,
        )
        return 1

    prefix = args.prefix or model.stem
    out_dir = model.resolve().parent
    views: list[str] = []
    for view in (value.strip() for value in args.views.split(",") if value.strip()):
        if view not in VIEWS:
            print(f"skipping unknown view {view!r}", file=sys.stderr)
            continue
        views.append(view)

    for renderer in renderers:
        print(f"renderer: {renderer}", file=sys.stderr)
        render_fn = RENDERERS[renderer]
        produced: list[Path] = []
        for view in views:
            out = out_dir / f"{prefix}.{view}.png"
            ok, err = render_fn(model, out, VIEWS[view], (width, height))
            if ok and out.is_file():
                produced.append(out)
                print(f"RENDERED: {out}")
            else:
                print(f"failed {view} view: {err}", file=sys.stderr)

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
