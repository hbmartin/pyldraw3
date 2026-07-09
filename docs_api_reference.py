"""Zensical macros for API reference pages."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


class MacroEnvironment(Protocol):
    """Subset of the Zensical macro environment used here."""

    def macro(self, fn: Callable[..., str]) -> Callable[..., str]:
        """Register a macro function."""


def _public_names(package: ModuleType) -> list[str]:
    """Return public export names from a package."""
    names = getattr(package, "__all__", None)
    if not isinstance(names, list | tuple):
        msg = f"{package.__name__} must define __all__ as a list or tuple"
        raise TypeError(msg)
    if not all(isinstance(name, str) for name in names):
        msg = f"{package.__name__}.__all__ must contain only strings"
        raise TypeError(msg)
    return list(names)


def _object_identifier(package: ModuleType, name: str) -> str:
    """Return the canonical mkdocstrings identifier for an exported object."""
    exported = getattr(package, name)
    module = getattr(exported, "__module__", package.__name__)
    qualname = getattr(exported, "__qualname__", name)

    if not isinstance(module, str):
        module = package.__name__
    if not isinstance(qualname, str):
        qualname = name

    return f"{module}.{qualname}"


def _mkdocstrings_directive(identifier: str) -> str:
    """Return a mkdocstrings directive for one API object."""
    return "\n".join(
        (
            f"::: {identifier}",
            "    options:",
            "      show_root_heading: true",
            "",
        )
    )


def _reference_markdown(package_name: str) -> str:
    """Return mkdocstrings directives for a package public API."""
    package = importlib.import_module(package_name)
    return "\n".join(
        _mkdocstrings_directive(_object_identifier(package, name))
        for name in _public_names(package)
    )


def define_env(env: MacroEnvironment) -> None:
    """Register documentation macros with Zensical."""

    @env.macro
    def public_api_reference(package_name: str = "ldraw") -> str:
        """Return generated public API reference directives."""
        return _reference_markdown(package_name)
