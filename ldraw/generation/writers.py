"""Shared helpers for generated Python modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def write_module(path: Path, content: str) -> None:
    """Write a generated module and an identical .pyi stub beside it."""
    path.write_text(content, encoding="utf-8")
    path.with_suffix(".pyi").write_text(content, encoding="utf-8")
