"""Exception classes for pyldraw package."""

from typing import Self


class PartError(Exception):
    """An exception happening during Part file processing."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.source: str | None = None
        self.line_number: int | None = None

    def add_context(self, *, source: str, line_number: int) -> Self:
        """Extend the message with file/line context, at most once."""
        if self.source is None:
            self.source = source
            self.line_number = line_number
            self.message = f"{self.message} in {source} at line {line_number}"
            self.args = (self.message,)
        return self


class PartNotFoundError(PartError):
    """Part was not found as expected."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"Part {code} not found in {path}")
        self.code = code
        self.path = path


class NoGeometryError(PartError):
    """The part (including its subfiles) draws no geometry at all."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Part {code} has no drawable geometry")
        self.code = code


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
        self.line_type = line_type
        self.expected_size = size
        self.line = tuple(line)


class InvalidNumericValueError(PartError, ValueError):
    """A numeric field in a line could not be parsed."""

    def __init__(self, line_type: str, token: str, line: list[str]) -> None:
        super().__init__(
            f'Invalid numeric value {token!r} in {line_type} line "{" ".join(line)}"',
        )
        self.line_type = line_type
        self.token = token
        self.line = tuple(line)


class UnknownCommandError(PartError):
    """An unrecognized LDraw line-type command."""

    def __init__(self, command: str) -> None:
        super().__init__(f"Unknown command ({command})")
        self.command = command


class InvalidColourValueError(PartError, ValueError):
    """A colour field token is neither a colour code nor a direct colour."""

    def __init__(self, token: str) -> None:
        super().__init__(f"Invalid colour value {token!r}")
        self.token = token


class EmptyPartFileError(PartError):
    """A part file has no content to read a description from."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"Part file {path} is empty; expected a description on its first line",
        )
        self.path = path


class StructuralCommentError(PartError):
    """A comment would serialize as MPD structure and corrupt round-trips."""

    def __init__(self, text: str) -> None:
        super().__init__(
            f"Comment {text!r} would serialize as MPD structure (0 FILE / 0 NOFILE) "
            "and be consumed as a section boundary when re-parsed; "
            "rename it or use Model.add_submodel",
        )
        self.text = text


class MisplacedNofileError(PartError):
    """A 0 NOFILE line appeared before any 0 FILE section."""

    def __init__(self, *, source: str, line_number: int) -> None:
        super().__init__(
            f"0 NOFILE before any 0 FILE section in {source} at line {line_number}",
        )


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


class UnknownSubmodelError(PartError):
    """The requested submodel name is not in this model's submodel table."""

    def __init__(self, name: str) -> None:
        super().__init__(f"No submodel named {name!r} in this model")


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
    """Could not build an import spec for a generated library module."""

    def __init__(self, fullname: str) -> None:
        super().__init__(f"Could not build an import spec for {fullname}.")


class StaleModuleSpecError(ModuleImportError):
    """A generated-module spec was invalidated before it could execute."""

    def __init__(self, fullname: str) -> None:
        super().__init__(
            f"Discarded stale import spec for {fullname} after library "
            "reconfiguration; retry the import.",
        )


class ConfigLoadError(Exception):
    """The pyldraw config file could not be read or parsed."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"Could not load config {path}: {reason}")
        self.path = path
        self.reason = reason


class CouldNotFindModuleError(ModuleImportError):
    """Could not find a module."""

    def __init__(self, fullname: str, init_path: str, py_path: str) -> None:
        super().__init__(
            f"Could not find module {fullname} at {init_path} or {py_path}.",
        )
