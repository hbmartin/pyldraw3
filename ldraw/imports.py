"""Dynamic import system for LDraw library modules."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import logging
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from ldraw.config import Config
from ldraw.errors import (
    CouldNotFindModuleError,
    CouldNotLoadSpecError,
    StaleModuleSpecError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

VIRTUAL_MODULE = "ldraw.library"

logger = logging.getLogger("ldraw")

_STATE_LOCK = threading.RLock()


class _StateLockedSourceFileLoader(importlib.machinery.SourceFileLoader):
    """Serialize generated-module execution against importer reconfiguration."""

    def __init__(
        self,
        fullname: str,
        path: str,
        *,
        config_generation: int,
        generation_getter: Callable[[], int],
    ) -> None:
        super().__init__(fullname, path)
        self._config_generation = config_generation
        self._generation_getter = generation_getter

    def exec_module(self, module: ModuleType) -> None:
        with _STATE_LOCK:
            if self._config_generation != self._generation_getter():
                raise StaleModuleSpecError(self.name)
            super().exec_module(module)


def _module_candidates(library_root: Path, fullname: str) -> tuple[Path, Path]:
    """Return the package and module file candidates for a library name."""
    dot_split = fullname.split(".")[1:]  # drop the leading "ldraw"
    lib_name = dot_split[-1]
    lib_dir = (
        library_root.joinpath(*dot_split[:-1]) if len(dot_split) > 1 else library_root
    )
    return lib_dir / lib_name / "__init__.py", lib_dir / f"{lib_name}.py"


def load_lib(library_path: str | Path, fullname: str) -> ModuleType:
    """Load a dynamically generated LDraw library module."""
    init_path, py_path = _module_candidates(Path(library_path), fullname)

    if init_path.exists():
        module_path = init_path
    elif py_path.exists():
        module_path = py_path
    else:
        raise CouldNotFindModuleError(fullname, str(init_path), str(py_path))

    spec = importlib.util.spec_from_file_location(fullname, module_path)
    if spec is None or spec.loader is None:
        raise CouldNotLoadSpecError(fullname)
    library_module = importlib.util.module_from_spec(spec)

    with _STATE_LOCK:
        sys.modules[fullname] = library_module
        try:
            spec.loader.exec_module(library_module)
        except Exception:
            sys.modules.pop(fullname, None)
            raise

    return library_module


class LibraryImporter:
    """Import hook added to sys.meta_path."""

    # Written by set_config (last caller wins) and read with its generation in
    # _config_snapshot so loaders can reject specs invalidated by clean().
    _default_config: ClassVar[Config | None] = None
    _config_generation: ClassVar[int] = 0
    # Shared with generated-module loaders so reconfiguration cannot evict a
    # module while its code is executing.
    _state_lock: ClassVar[threading.RLock] = _STATE_LOCK

    def __init__(self, config: Config | None = None) -> None:
        self.config = config

    @staticmethod
    def valid_module(fullname: str) -> bool:
        """Check if the module name is a valid library module name."""
        if fullname.startswith(VIRTUAL_MODULE):
            rest = fullname[len(VIRTUAL_MODULE) :]
            return not rest or rest.startswith(".")
        return False

    @classmethod
    def set_config(cls, config: Config) -> None:
        """Set the default configuration and clean cached modules."""
        cls.clean(config=config)

    def _config_snapshot(self) -> tuple[Config, int]:
        """Return one configuration and cache generation snapshot."""
        with self._state_lock:
            config = self.config or self._default_config
            generation = self._config_generation
        return (config or Config.load()), generation

    @classmethod
    def _current_config_generation(cls) -> int:
        """Return the current cache generation while the caller holds the lock."""
        return cls._config_generation

    def find_spec(
        self,
        fullname: str,
        path: object = None,  # noqa: ARG002
        target: ModuleType | None = None,  # noqa: ARG002
    ) -> importlib.machinery.ModuleSpec | None:
        """Find a real file-backed spec for a generated library module.

        Returns None for names outside ``ldraw.library`` and when no
        generated library exists at all — so probing with
        ``importlib.util.find_spec`` is truthful — and raises
        ``CouldNotFindModuleError`` for a missing submodule of an existing
        generated library. The returned spec uses a ``SourceFileLoader``
        subclass that serializes execution against reconfiguration; CPython
        still registers the module in ``sys.modules`` before executing it and
        rolls back on failure.
        Resolving the configuration may raise ``ConfigLoadError`` for a
        corrupt config file.
        """
        if not self.valid_module(fullname):
            return None
        config, config_generation = self._config_snapshot()
        library_root = Path(config.generated_path)
        if not (library_root / "library" / "__init__.py").is_file():
            return None
        init_path, py_path = _module_candidates(library_root, fullname)
        if init_path.is_file():
            module_path = init_path
        elif py_path.is_file():
            module_path = py_path
        else:
            raise CouldNotFindModuleError(fullname, str(init_path), str(py_path))
        logger.debug("loading %s from %s", fullname, config.generated_path)
        loader = _StateLockedSourceFileLoader(
            fullname,
            str(module_path),
            config_generation=config_generation,
            generation_getter=self._current_config_generation,
        )
        spec = importlib.util.spec_from_file_location(
            fullname,
            module_path,
            loader=loader,
        )
        if spec is None or spec.loader is None:
            raise CouldNotLoadSpecError(fullname)
        return spec

    @classmethod
    def clean(cls, *, config: Config | None = None) -> None:
        """Install an optional config and clean cached generated modules."""
        with cls._state_lock:
            if config is not None:
                cls._default_config = config
            cls._config_generation += 1
            initializing: list[str] = []
            for fullname, module in list(sys.modules.items()):
                if not cls.valid_module(fullname):
                    continue
                spec = getattr(module, "__spec__", None)
                if getattr(spec, "_initializing", False):
                    initializing.append(fullname)
                else:
                    del sys.modules[fullname]

        # Importing an initializing module waits on CPython's per-module import
        # lock. Do this without _state_lock so its loader can finish execution.
        for fullname in initializing:
            # A failed import removes itself from sys.modules; clean-up has
            # nothing further to do for that name.
            with suppress(Exception):
                importlib.import_module(fullname)

        with cls._state_lock:
            for fullname in initializing:
                module = sys.modules.get(fullname)
                spec = getattr(module, "__spec__", None)
                if module is not None and not getattr(spec, "_initializing", False):
                    del sys.modules[fullname]
            if "ldraw" in sys.modules:
                ldraw_mod = sys.modules["ldraw"]
                if hasattr(ldraw_mod, "library"):
                    delattr(ldraw_mod, "library")
