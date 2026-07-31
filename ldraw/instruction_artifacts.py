"""JSON manifests and renderer-neutral instruction snapshot bundles."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ldraw.errors import PartError, SubmodelCycleError
from ldraw.geometry import Identity, Matrix, Vector
from ldraw.lines import (
    Comment,
    Line,
    MetaCommand,
    OptionalLine,
    Quadrilateral,
    Triangle,
)
from ldraw.pieces import MAIN_COLOUR_CODE, Piece
from ldraw.utils import normalize_ref

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ldraw.colour import Colour
    from ldraw.instructions import (
        CameraState,
        InstructionDocument,
        InstructionSection,
        InstructionStep,
    )
    from ldraw.model import Model, ModelOccurrence
    from ldraw.part import ParsedObject
    from ldraw.parts import Parts

PACKAGE_NAME = "pyldraw3"
MANIFEST_NAME = "instructions.json"
SCHEMA_VERSION = 1
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_GEOMETRY_TYPES = (Piece, Line, Triangle, Quadrilateral, OptionalLine)


def instruction_manifest(
    document: InstructionDocument,
    *,
    parts: Parts,
    source: Path | str | None = None,
    artifact_paths: dict[tuple[str, int], dict[str, str]] | None = None,
    generated_files: Iterable[str] = (),
) -> dict[str, object]:
    """Return a deterministic schema-v1 instruction manifest."""
    paths = artifact_paths or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": PACKAGE_NAME, "version": _package_version()},
        "source": None if source is None else str(source),
        "root_section": document.root.name,
        "generated_files": list(generated_files),
        "sections": [
            _section_manifest(section, parts=parts, artifact_paths=paths)
            for section in document.sections
        ],
        "orphan_sections": [section.name for section in document.orphan_sections],
    }


def manifest_json(manifest: dict[str, object]) -> str:
    """Serialize an instruction manifest with stable formatting."""
    return f"{json.dumps(manifest, indent=2, ensure_ascii=False)}\n"


def write_instruction_manifest(
    document: InstructionDocument,
    *,
    parts: Parts,
    output: Path,
    source: Path | str | None = None,
    force: bool = False,
) -> None:
    """Atomically write a standalone instruction manifest."""
    if output.exists() and not force:
        msg = f"Output already exists: {output}"
        raise FileExistsError(msg)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = instruction_manifest(document, parts=parts, source=source)
    temporary_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.",
            dir=output.parent,
        )
    )
    temporary = temporary_dir / output.name
    try:
        temporary.write_text(manifest_json(manifest), encoding="utf-8")
        temporary.replace(output)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def write_instruction_snapshots(  # noqa: PLR0913 - artifact options are explicit
    document: InstructionDocument,
    *,
    parts: Parts,
    output: Path,
    source: Path | str | None = None,
    section_name: str | None = None,
    force: bool = False,
) -> Path:
    """Write MPD and flattened-LDR snapshots plus a manifest."""
    selected = (
        document.sections if section_name is None else (document.section(section_name),)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    old_owned = _prepare_output(output, force=force)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-",
            dir=output.parent,
        )
    )
    try:
        paths: dict[tuple[str, int], dict[str, str]] = {}
        generated: list[str] = []
        for index, section in enumerate(selected, start=1):
            section_dir = f"{index:03d}-{_slug(section.name)}"
            for step in section.steps:
                stem = f"step-{step.number:04d}"
                mpd_relative = f"{section_dir}/{stem}.mpd"
                ldr_relative = f"{section_dir}/{stem}.ldr"
                paths[(normalize_ref(section.name), step.number)] = {
                    "mpd": mpd_relative,
                    "ldr": ldr_relative,
                }
                _write_snapshot_mpd(
                    document,
                    section=section,
                    step=step,
                    path=stage / mpd_relative,
                )
                sidecars = _write_snapshot_ldr(
                    document,
                    section=section,
                    step=step,
                    path=stage / ldr_relative,
                )
                generated.extend((mpd_relative, ldr_relative, *sidecars))
        generated = list(dict.fromkeys((*generated, MANIFEST_NAME)))
        manifest = instruction_manifest(
            document,
            parts=parts,
            source=source,
            artifact_paths=paths,
            generated_files=generated,
        )
        (stage / MANIFEST_NAME).write_text(manifest_json(manifest), encoding="utf-8")
        _commit_staged_output(
            stage=stage,
            output=output,
            old_owned=old_owned,
            generated=generated,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return output / MANIFEST_NAME


def _package_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"


def _section_manifest(
    section: InstructionSection,
    *,
    parts: Parts,
    artifact_paths: dict[tuple[str, int], dict[str, str]],
) -> dict[str, object]:
    return {
        "name": section.name,
        "is_root": section.is_root,
        "references": list(section.references),
        "steps": [
            _step_manifest(
                step,
                parts=parts,
                artifacts=artifact_paths.get(
                    (normalize_ref(section.name), step.number),
                    {},
                ),
            )
            for step in section.steps
        ],
    }


def _step_manifest(
    step: InstructionStep,
    *,
    parts: Parts,
    artifacts: dict[str, str],
) -> dict[str, object]:
    added = step.added_occurrences()
    cumulative = step.cumulative_occurrences()
    bounds, geometry_warnings = _occurrence_bounds(cumulative, parts=parts)
    return {
        "number": step.number,
        "source_lines": [step.source_start_line, step.source_end_line],
        "suppressed": step.suppressed,
        "page_break_before": step.page_break_before,
        "multi_step_group": step.multi_step_group,
        "rotation": _rotation_manifest(step),
        "camera": _camera_manifest(step.camera),
        "callouts": [
            {
                "mode": callout.mode.value,
                "references": list(callout.references),
                "source_line": callout.source_line,
            }
            for callout in step.callouts
        ],
        "direct_placements": [
            _piece_manifest(
                piece,
                parts=parts,
                source_section=step.section_name,
                source_line=step.source_line_for(piece),
            )
            for piece in step.added_pieces
        ],
        "added_occurrences": [
            _occurrence_manifest(occurrence, parts=parts) for occurrence in added
        ],
        "added_bom": [asdict(row) for row in step.added_bill_of_materials(parts=parts)],
        "cumulative_occurrence_count": len(cumulative),
        "cumulative_bom": [
            asdict(row) for row in step.cumulative_bill_of_materials(parts=parts)
        ],
        "bounds": bounds,
        "geometry_warnings": geometry_warnings,
        "directives": [directive.to_dict() for directive in step.directives],
        "artifacts": artifacts,
    }


def _rotation_manifest(step: InstructionStep) -> dict[str, object] | None:
    if step.rotation is None:
        return None
    return {
        "mode": step.rotation.mode.value,
        "angles": step.rotation.angles,
        "command_matrix": step.rotation.command_matrix.rows,
        "effective_matrix": step.rotation.effective_matrix.rows,
        "source_line": step.rotation.source_line,
    }


def _camera_manifest(camera: CameraState) -> dict[str, object]:
    return {
        "angles": camera.angles,
        "angle_preset": camera.angle_preset,
        "position": camera.position,
        "target": camera.target,
        "up_vector": camera.up_vector,
        "distance": camera.distance,
        "fov": camera.fov,
        "name": camera.name,
        "orthographic": camera.orthographic,
        "z_near": camera.z_near,
        "z_far": camera.z_far,
    }


def _piece_manifest(
    piece: Piece,
    *,
    parts: Parts,
    source_section: str,
    source_line: int | None,
) -> dict[str, object]:
    position, matrix = piece._transformed()  # noqa: SLF001 - serialization view
    return {
        "part": piece.part,
        "reference": piece.reference,
        "description": parts.description_for(piece.part),
        "colour": _colour_manifest(piece.colour, parts=parts),
        "position": [position.x, position.y, position.z],
        "matrix": matrix.rows,
        "source_section": source_section,
        "source_line": source_line,
    }


def _occurrence_manifest(
    occurrence: ModelOccurrence,
    *,
    parts: Parts,
) -> dict[str, object]:
    return {
        "part": occurrence.part_code,
        "reference": occurrence.reference,
        "description": parts.description_for(occurrence.part_code),
        "colour": _colour_manifest(occurrence.colour, parts=parts),
        "position": [
            occurrence.position.x,
            occurrence.position.y,
            occurrence.position.z,
        ],
        "matrix": occurrence.matrix.rows,
        "source_section": occurrence.source_model.name,
        "source_line": occurrence.source_line,
    }


def _colour_manifest(colour: Colour, *, parts: Parts) -> dict[str, object]:
    catalogued = (
        parts.colours_by_code.get(colour.code) if colour.code is not None else None
    )
    return {
        "code": colour.code,
        "rgb": colour.rgb,
        "name": colour.name or (catalogued.name if catalogued is not None else None),
    }


def _occurrence_bounds(
    occurrences: Iterable[ModelOccurrence],
    *,
    parts: Parts,
) -> tuple[dict[str, list[float]] | None, list[dict[str, object]]]:
    minimum: list[float] | None = None
    maximum: list[float] | None = None
    warnings: list[dict[str, object]] = []
    for occurrence in occurrences:
        try:
            box = parts.bounding_box(occurrence.part_code)
        except PartError as error:
            warnings.append(
                {
                    "part": occurrence.part_code,
                    "source_section": occurrence.source_model.name,
                    "source_line": occurrence.source_line,
                    "message": error.message,
                }
            )
            continue
        for corner in box.corners():
            point = occurrence.position + occurrence.matrix * corner
            values = [float(point.x), float(point.y), float(point.z)]
            if minimum is None or maximum is None:
                minimum, maximum = values.copy(), values.copy()
            else:
                minimum = [
                    min(old, new) for old, new in zip(minimum, values, strict=True)
                ]
                maximum = [
                    max(old, new) for old, new in zip(maximum, values, strict=True)
                ]
    bounds = (
        None if minimum is None or maximum is None else {"min": minimum, "max": maximum}
    )
    return bounds, warnings


def _slug(name: str) -> str:
    stem = Path(name.replace("\\", "/")).stem.casefold()
    return _SLUG_RE.sub("-", stem).strip("-") or "section"


def _is_instruction_directive(obj: ParsedObject) -> bool:
    if isinstance(obj, MetaCommand) and obj.type.casefold() in {"lpub", "pyldraw"}:
        return True
    if isinstance(obj, Comment):
        upper = obj.text.strip().upper()
        return upper == "STEP" or upper.startswith(("ROTSTEP", "LPUB "))
    return False


def _snapshot_objects(objects: Iterable[ParsedObject]) -> list[ParsedObject]:
    return [obj for obj in objects if not _is_instruction_directive(obj)]


def _dependency_closure(
    root: Model,
    objects: Iterable[ParsedObject],
) -> list[Model]:
    result: list[Model] = []
    seen: set[str] = set()
    pending = [obj for obj in objects if isinstance(obj, Piece)]
    while pending:
        piece = pending.pop(0)
        target = root.submodel_for(piece)
        if target is None or target is root:
            continue
        key = normalize_ref(target.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
        pending.extend(obj for obj in target.objects if isinstance(obj, Piece))
    return result


def _write_snapshot_mpd(
    document: InstructionDocument,
    *,
    section: InstructionSection,
    step: InstructionStep,
    path: Path,
) -> None:
    root_objects = _snapshot_objects(step.cumulative_objects)
    dependencies = _dependency_closure(document.model, root_objects)
    sections = [(section.name, root_objects)] + [
        (dependency.name, _snapshot_objects(dependency.objects))
        for dependency in dependencies
    ]
    lines: list[str] = []
    for name, objects in sections:
        lines.extend(
            (
                f"0 FILE {name}",
                *(obj.to_ldraw() for obj in objects),
                "0 NOFILE",
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{'\n'.join(lines)}\n", encoding="utf-8")


def _write_snapshot_ldr(
    document: InstructionDocument,
    *,
    section: InstructionSection,
    step: InstructionStep,
    path: Path,
) -> list[str]:
    embedded_parts: dict[str, Model] = {}
    flattened = list(
        _flatten_objects(
            root=document.model,
            model=section.model,
            objects=_snapshot_objects(step.cumulative_objects),
            position=Vector(0, 0, 0),
            matrix=Identity(),
            inherited_colour=None,
            visiting=frozenset(),
            embedded_parts=embedded_parts,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{'\n'.join(obj.to_ldraw() for obj in flattened)}\n" if flattened else "",
        encoding="utf-8",
    )
    sidecars: list[str] = []
    for name, model in _embedded_dependency_closure(
        document.model,
        embedded_parts,
    ).items():
        relative = _safe_reference_path(name)
        destination = path.parent / relative
        sidecars.append(destination.relative_to(path.parents[1]).as_posix())
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(obj.to_ldraw() for obj in _snapshot_objects(model.objects))
        destination.write_text(f"{text}\n" if text else "", encoding="utf-8")
    return sidecars


def _embedded_dependency_closure(
    root: Model,
    initial: dict[str, Model],
) -> dict[str, Model]:
    result = dict(initial)
    seen = {normalize_ref(name) for name in result}
    pending = list(result.values())
    while pending:
        model = pending.pop(0)
        for piece in model.pieces:
            target = root.submodel_for(piece)
            if target is None or not target.name.casefold().endswith(".dat"):
                continue
            key = normalize_ref(target.name)
            if key in seen:
                continue
            seen.add(key)
            result[target.name] = target
            pending.append(target)
    return result


def _flatten_objects(  # noqa: PLR0913 - explicit traversal state
    *,
    root: Model,
    model: Model,
    objects: Iterable[ParsedObject],
    position: Vector,
    matrix: Matrix,
    inherited_colour: Colour | None,
    visiting: frozenset[str],
    embedded_parts: dict[str, Model],
) -> Iterable[ParsedObject]:
    key = normalize_ref(model.name)
    if key in visiting:
        raise SubmodelCycleError(model.name)
    visiting = visiting | {key}
    for obj in objects:
        if isinstance(obj, Piece):
            piece_position, piece_matrix = obj._transformed()  # noqa: SLF001
            world_position = position + matrix * piece_position
            world_matrix = matrix * piece_matrix
            colour = _effective_colour(obj.colour, inherited_colour)
            target = root.submodel_for(obj)
            if target is not None and not target.name.casefold().endswith(".dat"):
                yield from _flatten_objects(
                    root=root,
                    model=target,
                    objects=_snapshot_objects(target.objects),
                    position=world_position,
                    matrix=world_matrix,
                    inherited_colour=colour,
                    visiting=visiting,
                    embedded_parts=embedded_parts,
                )
            else:
                if target is not None:
                    embedded_parts[target.name] = target
                yield Piece(
                    colour=colour,
                    position=world_position,
                    matrix=world_matrix,
                    part=obj.part,
                    suffix=obj.suffix,
                )
        elif isinstance(obj, Line):
            yield Line(
                _effective_colour(obj.colour, inherited_colour),
                position + matrix * obj.point1,
                position + matrix * obj.point2,
            )
        elif isinstance(obj, Triangle):
            yield Triangle(
                _effective_colour(obj.colour, inherited_colour),
                position + matrix * obj.point1,
                position + matrix * obj.point2,
                position + matrix * obj.point3,
            )
        elif isinstance(obj, Quadrilateral):
            yield Quadrilateral(
                _effective_colour(obj.colour, inherited_colour),
                position + matrix * obj.point1,
                position + matrix * obj.point2,
                position + matrix * obj.point3,
                position + matrix * obj.point4,
            )
        elif isinstance(obj, OptionalLine):
            yield OptionalLine(
                _effective_colour(obj.colour, inherited_colour),
                position + matrix * obj.point1,
                position + matrix * obj.point2,
                position + matrix * obj.point3,
                position + matrix * obj.point4,
            )


def _effective_colour(colour: Colour, inherited: Colour | None) -> Colour:
    if colour.code == MAIN_COLOUR_CODE and inherited is not None:
        return inherited
    return colour


def _safe_reference_path(reference: str) -> Path:
    pure = PurePosixPath(reference.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        msg = f"Unsafe embedded part path: {reference}"
        raise ValueError(msg)
    return Path(*pure.parts)


def _prepare_output(output: Path, *, force: bool) -> set[str]:
    if not output.exists() or not any(output.iterdir()):
        return set()
    if not force:
        msg = f"Output directory is not empty: {output}"
        raise FileExistsError(msg)
    manifest_path = output / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"Cannot force overwrite without a valid {MANIFEST_NAME}"
        raise ValueError(msg) from error
    generator = manifest.get("generator", {})
    if not isinstance(generator, dict) or generator.get("name") != PACKAGE_NAME:
        msg = f"Refusing to overwrite an output not owned by {PACKAGE_NAME}"
        raise ValueError(msg)
    files = manifest.get("generated_files", [])
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        msg = "Existing manifest has an invalid generated_files list"
        raise ValueError(msg)
    return {str(item) for item in files}


def _commit_staged_output(
    *,
    stage: Path,
    output: Path,
    old_owned: set[str],
    generated: list[str],
) -> None:
    if not output.exists():
        stage.replace(output)
        return
    for relative in generated:
        destination = output / _safe_reference_path(relative)
        if destination.exists() and relative not in old_owned:
            msg = f"Refusing to overwrite unrelated file: {destination}"
            raise FileExistsError(msg)
    for source in sorted(output.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(output)
        if relative.as_posix() in old_owned:
            continue
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    backup_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-backup-", dir=output.parent)
    )
    backup = backup_root / output.name
    output.replace(backup)
    try:
        stage.replace(output)
    except OSError:
        backup.replace(output)
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)
