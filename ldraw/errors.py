"""Exception classes for pyldraw package."""


class PartError(Exception):
    """An exception happening during Part file processing."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PartNotFoundError(PartError):
    """Part was not found as expected."""

    def __init__(self, code: str, path: str):
        super().__init__(f"Part {code} not found in {path}")
        self.code = code
        self.path = path


class PartRequiresPathXorFileError(PartError, ValueError):
    """Part must have one and only one of path or file to init."""

    def __init__(self):
        super().__init__("Part must have one and only one of path or file to init.")


class InvalidLineDataError(PartError, ValueError):
    """Line was invalid and could not be parsed."""

    def __init__(self, line_type: str, size: int, line: list):
        super().__init__(
            f"Line type {line_type} must have {size} parameters:\n{" ".join(line)}",
        )


class CouldNotDetermineLatestVersionError(Exception):
    """Could not determine the latest parts list version."""

    def __init__(self):
        super().__init__("Could not determine the latest parts list version.")


class ModuleImportError(ImportError):
    """Could not import a module."""


class CouldNotLoadSpecError(ModuleImportError):
    """Could not determine the latest parts list version."""

    def __init__(self, fullname: str):
        super().__init__(
            f"Could not determine the latest parts list version for {fullname}.",
        )


class CouldNotFindModuleError(ModuleImportError):
    """Could not find a module."""

    def __init__(self, fullname: str, init_path: str, py_path: str):
        super().__init__(
            f"Could not find module {fullname} at {init_path} or {py_path}.",
        )


class InvalidConfigFileError(AssertionError):
    """The config file is invalid."""

    def __init__(self, config_file: str):
        super().__init__(f"The config file {config_file} is invalid.")
