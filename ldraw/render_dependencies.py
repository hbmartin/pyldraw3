"""Bring local sidecar documents into a render-only dependency closure."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ldraw.model import Model, read_model
from ldraw.utils import normalize_ref, split_reference

if TYPE_CHECKING:
    from pathlib import Path


def include_local_dependencies(model: Model, *, source: Path) -> None:
    """Embed local files with deterministic names without modifying their sources."""
    locations = {source.resolve(): model.name}
    pending = [(section, source) for section in (model, *model.submodels.values())]
    while pending:
        section, location = pending.pop()
        for piece in section.pieces:
            if normalize_ref(piece.reference) in {
                normalize_ref(model.name),
                *model.submodels,
            }:
                continue
            local = (location.parent / piece.reference.replace("\\", "/")).resolve()
            if not local.is_file():
                continue
            if local not in locations:
                dependency = read_model(local)
                sections = (dependency, *dependency.submodels.values())
                prefix = hashlib.sha256(str(local).encode()).hexdigest()[:16]
                renames = {
                    normalize_ref(item.name): f"__pyldraw__/{prefix}-{item.name}"
                    for item in sections
                }
                locations[local] = renames[normalize_ref(dependency.name)]
                for item in sections:
                    item.name = renames[normalize_ref(item.name)]
                    for reference in item.pieces:
                        if name := renames.get(normalize_ref(reference.reference)):
                            reference.part, reference.suffix = split_reference(name)
                    model.submodels[normalize_ref(item.name)] = item
                    pending.append((item, local))
            piece.part, piece.suffix = split_reference(locations[local])
