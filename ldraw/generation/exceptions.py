"""Exception classes for library generation."""


class NoLibrarySelectedError(Exception):
    """Exception raised when no library is selected."""


class UnwritableOutputError(Exception):
    """Exception raised when output directory is not writable."""


class DuplicateSymbolError(Exception):
    """Generated symbols in a module still collide after deduplication."""

    def __init__(self, section_key: str, symbols: list[str]) -> None:
        super().__init__(
            f"Generated module {section_key!r} has colliding symbols even "
            f"after part-code suffixing: {', '.join(sorted(symbols))}",
        )
