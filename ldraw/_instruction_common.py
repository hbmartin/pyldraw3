"""Lightweight classification shared by instruction resolution and expansion."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ldraw.model import Model


def _is_instruction_model(model: Model) -> bool:
    return not model.name.casefold().endswith(".dat")
