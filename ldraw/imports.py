"""Dynamic import system for LDraw library modules."""

import importlib.util
import logging
import os
import sys

from ldraw.config import Config
from ldraw.errors import CouldNotFindModuleError, CouldNotLoadSpecError

VIRTUAL_MODULE = "ldraw.library"

logger = logging.getLogger("ldraw")


def load_lib(library_path, fullname):
    """Load a dynamically generated LDraw library module.

    Args:
        library_path (str): The root directory of the generated LDraw library.
        fullname (str): The full dotted module name to load
            (e.g., 'ldraw.library.parts.brick_2x4').

    Returns:
        module: The loaded Python module object.

    Raises:
        CouldNotFindModuleError: If the module file cannot be found.
        CouldNotLoadSpecError: If the module spec cannot be loaded.
        Exception: If execution of the module fails.

    """
    dot_split = fullname.split(".")
    dot_split.pop(0)  # Remove 'ldraw'

    # Build the path components
    lib_name = dot_split[-1]
    lib_dir = (
        os.path.join(library_path, *tuple(dot_split[:-1]))
        if len(dot_split) > 1
        else library_path
    )

    # Try directory with __init__.py first, then .py file
    init_path = os.path.join(lib_dir, lib_name, "__init__.py")
    py_path = os.path.join(lib_dir, f"{lib_name}.py")

    if os.path.exists(init_path):
        module_path = init_path
    elif os.path.exists(py_path):
        module_path = py_path
    else:
        raise CouldNotFindModuleError(fullname, init_path, py_path)

    spec = importlib.util.spec_from_file_location(fullname, module_path)
    if spec is None or spec.loader is None:
        raise CouldNotLoadSpecError(fullname)
    library_module = importlib.util.module_from_spec(spec)

    # Add to sys.modules BEFORE executing to prevent infinite recursion
    sys.modules[fullname] = library_module
    try:
        spec.loader.exec_module(library_module)
    except Exception:
        # If execution fails, remove from sys.modules
        if fullname in sys.modules:
            del sys.modules[fullname]
        raise

    return library_module


class LibraryImporter:
    """Added to sys.meta_path as an import hook."""

    @classmethod
    def valid_module(cls, fullname):
        """Check if the module name is a valid library module name."""
        if fullname.startswith(VIRTUAL_MODULE):
            rest = fullname[len(VIRTUAL_MODULE) :]
            if not rest or rest.startswith("."):
                return True
        return False

    config = None

    @classmethod
    def set_config(cls, config):
        """Set the configuration for the library importer and clean cached modules."""
        cls.config = config
        cls.clean()

    @classmethod
    def find_module(cls, fullname, path=None):  # noqa: ARG003
        """Find module for the given fullname.

        This method is called by Python if this class
        is on sys.path. fullname is the fully-qualified
        name of the module to look for, and path is either
        __path__ (for submodules and subpackages) or None (for
        a top-level module/package).

        Called every time an import
        statement is detected (or __import__ is called), before
        Python's built-in package/module-finding code kicks in.
        """
        if cls.valid_module(fullname):
            # As per PEP #302 (which implemented the sys.meta_path protocol),
            # if fullname is the name of a module/package that we want to
            # report as found, then we need to return a loader object.
            # In this simple example, that will just be self.

            return cls()

        # If we don't provide the requested module, return None, as per
        # PEP #302.

        return None

    @classmethod
    def find_spec(cls, fullname, path, target=None):  # noqa: ARG003
        """Find module spec for the given fullname.

        PEP 451: find_spec should return a ModuleSpec if the module can be handled.
        """
        if cls.valid_module(fullname):
            # Use importlib.util.spec_from_loader for compatibility
            return importlib.util.spec_from_loader(fullname, cls())
        return None

    @classmethod
    def clean(cls):
        """Clean cached library modules from sys.modules."""
        for fullname in list(sys.modules.keys()):
            if cls.valid_module(fullname):
                del sys.modules[fullname]
        if "ldraw" in sys.modules:
            ldraw_mod = sys.modules["ldraw"]
            if hasattr(ldraw_mod, "library"):
                delattr(ldraw_mod, "library")

    def get_code(self, fullname):  # noqa: ARG002
        """Get the code object for a module (not used in this implementation)."""
        return

    def load_module(self, fullname):
        """Load module if CustomImporter.find_module does not return None.

        fullname is the fully-qualified name of the module/package that was requested.
        """
        if not self.valid_module(fullname):
            # Raise ImportError as per PEP #302 if the requested module/package
            # couldn't be loaded. This should never be reached in this
            # simple example, but it's included here for completeness. :)
            raise ImportError(fullname)

        # Check if module is already loaded to prevent infinite recursion
        if fullname in sys.modules:
            return sys.modules[fullname]

        # if the library already exists and correctly generated,
        # the __hash__ will prevent re-generation
        config = self.config if self.config is not None else Config.load()
        logger.debug("loading %s from %s", fullname, config.generated_path)
        # Module is already added to sys.modules in load_lib
        return load_lib(config.generated_path, fullname)
