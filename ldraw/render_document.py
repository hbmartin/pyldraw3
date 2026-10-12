"""Isolated render documents, dependency identity, and resolved camera framing."""

from __future__ import annotations

import hashlib
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ldraw.utils import ldraw_file_name, normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ldraw.part_geometry_types import BoundingBox
    from ldraw.parts import Parts


@dataclass(frozen=True, slots=True)
class RenderDocument:
    """A stable cache identity and optional local-library camera context."""

    source: Path
    identity: bytes
    library: Path | None = None
    bounds: BoundingBox | None = None


render_document: ContextVar[RenderDocument | None] = ContextVar(
    "render_document", default=None
)


def _selected_parts(parts: Parts | None, library: str | Path | None) -> Parts | None:
    from ldraw.parts import Parts  # noqa: PLC0415

    if library is not None:
        return Parts.from_directory(library)
    if parts is not None:
        return parts
    from ldraw.library_access import select_library  # noqa: PLC0415
    from ldraw.session import LDrawSession  # noqa: PLC0415

    try:
        selected = select_library()
    except FileNotFoundError:
        if os.environ.get("LDRAW_DIR") or os.environ.get("LDRAWDIR"):
            raise
        return None
    return LDrawSession(library=selected.directory).load()


def _dependency_digest(source: Path, *, parts: Parts | None) -> bytes:
    from ldraw.part import parse_ldraw_line  # noqa: PLC0415
    from ldraw.pieces import Piece  # noqa: PLC0415

    digest = hashlib.sha256()
    pending = [source]
    seen: set[Path] = set()
    embedded = {
        normalize_ref(name)
        for line in source.read_text(encoding="utf-8-sig").splitlines()
        if (name := ldraw_file_name(line)) is not None
    }
    if parts is not None:
        digest.update(str(parts.library_root.resolve()).encode())
        pending.extend(
            path
            for path in parts.library_root.iterdir()
            if path.name.casefold() == "ldconfig.ldr"
        )
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        text = path.read_bytes()
        digest.update(str(path).encode())
        digest.update(text)
        for line in text.decode("utf-8-sig", errors="replace").splitlines():
            try:
                obj = parse_ldraw_line(line)
            except ValueError:
                continue
            if not isinstance(obj, Piece):
                continue
            if normalize_ref(obj.reference) in embedded:
                continue
            local = path.parent / obj.reference.replace("\\", "/")
            if local.is_file():
                pending.append(local)
            elif (
                parts is not None
                and (part := parts.find_part(code=obj.part)) is not None
            ):
                pending.append(part.path)
    return digest.digest()


@contextmanager
def prepare_render_document(
    source: Path,
    *,
    section: str | None,
    parts: Parts | None,
    library: str | Path | None,
) -> Iterator[RenderDocument]:
    """Export embedded definitions into an isolated temporary workspace."""
    from ldraw.model import read_model  # noqa: PLC0415
    from ldraw.model_summary import ModelSummary  # noqa: PLC0415

    parts = _selected_parts(parts, library)
    model = read_model(source)
    identity = _dependency_digest(source, parts=parts)
    from ldraw.render_dependencies import include_local_dependencies  # noqa: PLC0415

    include_local_dependencies(model, source=source)
    if section is not None:
        model = model.extract(section).model
    identity += normalize_ref(section or model.name).encode()
    bounds = ModelSummary.from_model(model, parts=parts).bounds
    if not model.submodels and section is None:
        yield RenderDocument(
            source=source,
            identity=identity,
            library=parts.library_root if parts else None,
            bounds=bounds,
        )
        return
    with TemporaryDirectory(prefix="pyldraw-render-document-") as directory:
        workspace = Path(directory).resolve()
        render_source = workspace / "scene.mpd"
        model.save(render_source, mpd=True)
        for definition in model.submodels.values():
            if not definition.name.casefold().endswith(".dat"):
                continue
            path = workspace / definition.name.replace("\\", "/")
            if not path.resolve().is_relative_to(workspace) or path.name in {
                "",
                ".",
                "..",
            }:
                message = f"Unsafe embedded render name {definition.name!r}"
                raise ValueError(message)
            path.parent.mkdir(parents=True, exist_ok=True)
            definition.save(path, mpd=False)
        yield RenderDocument(
            source=render_source,
            identity=identity,
            library=parts.library_root if parts else None,
            bounds=bounds,
        )


def camera_options(
    *, backend: str, latitude: int, longitude: int, size: tuple[int, int]
) -> list[str]:
    """Frame the resolved bounding sphere with margin in either renderer."""
    context = render_document.get()
    if context is None:
        return []
    result = []
    if context.library is not None:
        result = (
            [f"-LDrawDir={context.library}"]
            if backend == "ldview"
            else ["--libpath", str(context.library)]
        )
    if context.bounds is None:
        return result
    bounds = context.bounds
    center = 0.5 * (bounds.min + bounds.max)
    radius = max(abs(bounds.size) / 2, 1.0)
    field = math.radians(25)
    aspect = size[0] / size[1]
    half_angle = min(field / 2, math.atan(math.tan(field / 2) * aspect))
    distance = 1.1 * radius / math.sin(half_angle)
    if backend == "ldview":
        return [
            *result,
            f"-ModelCenter={center.x},{center.y},{center.z}",
            f"-CameraGlobe={latitude},{longitude},{distance}",
            "-FOV=25",
        ]
    lat, lon = math.radians(latitude), math.radians(longitude)
    from ldraw.geometry import Vector  # noqa: PLC0415

    direction = Vector(
        math.sin(lon) * math.cos(lat), -math.sin(lat), math.cos(lon) * math.cos(lat)
    )
    eye = center + distance * direction
    up = Vector(0, -1, 0)
    if abs(direction.dot(up)) > 0.99:
        up = Vector(0, 0, 1)
    coordinates = (eye.x, eye.y, eye.z, center.x, center.y, center.z, up.x, up.y, up.z)
    return [
        *result,
        "--camera-position-ldraw",
        *(str(value) for value in coordinates),
        "--fov",
        "25",
    ]
