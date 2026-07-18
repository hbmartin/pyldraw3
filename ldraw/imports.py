"""Dynamic import system for LDraw library modules."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from ldraw.config import Config
from ldraw.errors import CouldNotFindModuleError, CouldNotLoadSpecError

if TYPE_CHECKING:
    from types import ModuleType

VIRTUAL_MODULE = "ldraw.library"

logger = logging.getLogger("ldraw")


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

    sys.modules[fullname] = library_module
    try:
        spec.loader.exec_module(library_module)
    except Exception:
        sys.modules.pop(fullname, None)
        raise

    return library_module


class LibraryImporter:
    """Import hook added to sys.meta_path."""

    # Written by set_config (last caller wins) and read without the lock in
    # find_spec — a benign racy read of a single reference.
    _default_config: ClassVar[Config | None] = None
    # RLock: set_config calls clean under the same lock.
    _state_lock: ClassVar[threading.RLock] = threading.RLock()

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
        with cls._state_lock:
            cls._default_config = config
            cls.clean()

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
        generated library. The returned spec's loader is a standard
        ``SourceFileLoader``, so CPython registers the module in
        ``sys.modules`` before executing it and rolls back on failure.
        Resolving the configuration may raise ``ConfigLoadError`` for a
        corrupt config file.
        """
        if not self.valid_module(fullname):
            return None
        config = self.config or self._default_config or Config.load()
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
        spec = importlib.util.spec_from_file_location(fullname, module_path)
        if spec is None or spec.loader is None:
            raise CouldNotLoadSpecError(fullname)
        return spec

    @classmethod
    def clean(cls) -> None:
        """Clean cached library modules from sys.modules."""
        with cls._state_lock:
            for fullname in list(sys.modules):
                if cls.valid_module(fullname):
                    del sys.modules[fullname]
            if "ldraw" in sys.modules:
                ldraw_mod = sys.modules["ldraw"]
                if hasattr(ldraw_mod, "library"):
                    delattr(ldraw_mod, "library")
