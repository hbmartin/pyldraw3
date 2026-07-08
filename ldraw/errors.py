"""Exception classes for pyldraw package."""


class PartError(Exception):
    """An exception happening during Part file processing."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PartNotFoundError(PartError):
    """Part was not found as expected."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"Part {code} not found in {path}")
        self.code = code
        self.path = path


class PartRequiresPathXorFileError(PartError, ValueError):
    """Part must have one and only one of path or file to init."""

    def __init__(self) -> None:
        super().__init__("Part must have one and only one of path or file to init.")


class InvalidLineDataError(PartError, ValueError):
    """Line was invalid and could not be parsed."""

    def __init__(self, line_type: str, size: int, line: list[str]) -> None:
        super().__init__(
            f"Line type {line_type} must have {size} parameters:\n{' '.join(line)}",
        )


class InvalidNumericValueError(PartError, ValueError):
    """A numeric field in a line could not be parsed."""

    def __init__(self, line_type: str, token: str, line: list[str]) -> None:
        super().__init__(
            f'Invalid numeric value {token!r} in {line_type} line "{" ".join(line)}"',
        )


class UnknownCommandError(PartError):
    """An unrecognized LDraw line-type command."""

    def __init__(self, command: str) -> None:
        super().__init__(f"Unknown command ({command})")


class DuplicateSubmodelError(PartError):
    """Two 0 FILE sections share the same (case-insensitive) name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Duplicate 0 FILE section named {name!r}")


class SubmodelCycleError(PartError):
    """Submodel references form a cycle."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Submodel reference cycle detected at {name!r}")


class SubmodelNameRequiredError(PartError):
    """A multi-part document section has no name to emit after 0 FILE."""

    def __init__(self) -> None:
        super().__init__(
            "Every model in a multi-part document needs a name to emit after 0 FILE",
        )


class LibraryNotGeneratedError(Exception):
    """The ldraw.library modules have not been generated yet."""

    def __init__(self, generated_path: str) -> None:
        super().__init__(
            f"No generated library found at {generated_path}; "
            "run `ldraw generate` first.",
        )


class CouldNotDetermineLatestVersionError(Exception):
    """Could not determine the latest parts list version."""

    def __init__(self) -> None:
        super().__init__("Could not determine the latest parts list version.")


class ModuleImportError(ImportError):
    """Could not import a module."""


class CouldNotLoadSpecError(ModuleImportError):
    """Could not determine the latest parts list version."""

    def __init__(self, fullname: str) -> None:
        super().__init__(
            f"Could not determine the latest parts list version for {fullname}.",
        )


class CouldNotFindModuleError(ModuleImportError):
    """Could not find a module."""

    def __init__(self, fullname: str, init_path: str, py_path: str) -> None:
        super().__init__(
            f"Could not find module {fullname} at {init_path} or {py_path}.",
        )


class InvalidConfigFileError(AssertionError):
    """The config file is invalid."""

    def __init__(self, config_file: str) -> None:
        super().__init__(f"The config file {config_file} is invalid.")
