"""Dynamic import system for LDraw library modules."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from ldraw.config import Config
from ldraw.errors import CouldNotFindModuleError, CouldNotLoadSpecError

if TYPE_CHECKING:
    from types import ModuleType

VIRTUAL_MODULE = "ldraw.library"

logger = logging.getLogger("ldraw")


def load_lib(library_path: str | Path, fullname: str) -> ModuleType:
    """Load a dynamically generated LDraw library module."""
    dot_split = fullname.split(".")
    dot_split.pop(0)

    lib_name = dot_split[-1]
    library_root = Path(library_path)
    lib_dir = (
        library_root.joinpath(*dot_split[:-1]) if len(dot_split) > 1 else library_root
    )

    init_path = lib_dir / lib_name / "__init__.py"
    py_path = lib_dir / f"{lib_name}.py"

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

    _default_config: ClassVar[Config | None] = None

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
        cls._default_config = config
        cls.clean()

    def find_module(
        self,
        fullname: str,
        path: object = None,  # noqa: ARG002
    ) -> LibraryImporter | None:
        """Find module for the given fullname."""
        if self.valid_module(fullname):
            return self
        return None

    def find_spec(
        self,
        fullname: str,
        path: object,  # noqa: ARG002
        target: ModuleType | None = None,  # noqa: ARG002
    ) -> importlib.machinery.ModuleSpec | None:
        """Find module spec for the given fullname."""
        if self.valid_module(fullname):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    @classmethod
    def clean(cls) -> None:
        """Clean cached library modules from sys.modules."""
        for fullname in list(sys.modules):
            if cls.valid_module(fullname):
                del sys.modules[fullname]
        if "ldraw" in sys.modules:
            ldraw_mod = sys.modules["ldraw"]
            if hasattr(ldraw_mod, "library"):
                delattr(ldraw_mod, "library")

    def get_code(self, fullname: str) -> None:
        """Get the code object for a module."""

    def load_module(self, fullname: str) -> ModuleType:
        """Load the requested dynamic library module."""
        if not self.valid_module(fullname):
            raise ImportError(fullname)

        if fullname in sys.modules:
            return sys.modules[fullname]

        config = self.config or self._default_config or Config.load()
        logger.debug("loading %s from %s", fullname, config.generated_path)
        return load_lib(config.generated_path, fullname)
