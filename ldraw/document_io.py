"""Atomic semantic writing and dependency-closed document extraction."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from ldraw.lines import Comment
from ldraw.model import Model
from ldraw.pieces import Piece
from ldraw.utils import normalize_ref, split_reference

if TYPE_CHECKING:
    from ldraw.part import ParsedObject


@dataclass(frozen=True, slots=True)
class ExtractionAttribution:
    """Source section, rewritten name, author, and licence of a copied definition."""

    source_name: str
    name: str
    author: str | None
    license: str | None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Dependency closure plus deterministic renames and retained attribution."""

    model: Model
    manifest: tuple[ExtractionAttribution, ...]


def save_document(
    model: Model, *, path: Path, newline: str, mpd: bool | None, atomic: bool
) -> None:
    """Write through a sibling file so failed replacements preserve the old file."""
    if newline not in {"\n", "\r\n", "\r"}:
        message = "newline must be LF, CRLF, or CR"
        raise ValueError(message)
    text = model.to_ldraw(mpd=mpd)
    text = f"{text}\n" if text else ""
    if not atomic:
        path.write_text(text, encoding="utf-8", newline=newline)
        return
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _closure(
    root: Model, section: Model, visiting: frozenset[str], result: dict[str, Model]
) -> None:
    key = normalize_ref(section.name)
    if key in visiting:
        message = f"Invalid extraction graph: cycle at {section.name!r}"
        raise ValueError(message)
    if key in result:
        return
    result[key] = section
    for piece in section.pieces:
        target = (
            root
            if normalize_ref(piece.reference) == normalize_ref(root.name)
            else root.submodel_for(piece)
        )
        if target is not None:
            _closure(root, target, visiting | {key}, result)
        elif piece.suffix.casefold() in {".ldr", ".mpd"}:
            message = f"Invalid extraction graph: missing section {piece.reference!r}"
            raise ValueError(message)


def _validate_names(root: Model, *, namespace: str) -> None:
    if namespace and (
        namespace in {".", ".."} or any(char in namespace for char in '\\/\r\n:*?<>|"')
    ):
        message = "namespace must be a single safe filename prefix"
        raise ValueError(message)
    if any(
        key != normalize_ref(value.name) or key == normalize_ref(root.name)
        for key, value in root.submodels.items()
    ):
        message = "Invalid extraction graph: duplicate or inconsistent section names"
        raise ValueError(message)


def extract_document(root: Model, *, section: str, namespace: str) -> ExtractionResult:
    """Copy a closure, preserving header records and rewriting only internal names."""
    _validate_names(root, namespace=namespace)
    selected = (
        root
        if normalize_ref(section) == normalize_ref(root.name)
        else root.submodels.get(normalize_ref(section))
    )
    if selected is None:
        message = f"Unknown extraction section {section!r}"
        raise ValueError(message)
    closure: dict[str, Model] = {}
    _closure(root, selected, frozenset(), closure)
    renames = {key: f"{namespace}{source.name}" for key, source in closure.items()}
    copies: dict[str, Model] = {}
    for key, source in closure.items():
        objects = [
            _copy_record(obj, renames=renames, own_name=renames[key])
            for obj in copy.deepcopy(source.objects)
        ]
        copies[key] = Model(name=renames[key], objects=objects)
    model = copies[normalize_ref(selected.name)]
    model.submodels = {
        key: value
        for value in copies.values()
        if value is not model
        for key in (normalize_ref(value.name),)
    }
    manifest = tuple(
        ExtractionAttribution(
            source_name=source.name,
            name=renames[key],
            author=source.author,
            license=source.license,
        )
        for key, source in closure.items()
    )
    return ExtractionResult(model=model, manifest=manifest)


def _copy_record(
    obj: ParsedObject, *, renames: dict[str, str], own_name: str
) -> ParsedObject:
    copied = obj
    if isinstance(copied, Piece) and (
        name := renames.get(normalize_ref(copied.reference))
    ):
        copied.part, copied.suffix = split_reference(name)
    if isinstance(copied, Comment) and copied.text.startswith("Name:"):
        return Comment(f"Name: {own_name}")
    return copied
