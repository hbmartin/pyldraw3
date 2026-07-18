"""Exception classes for library generation."""


class UnwritableOutputError(Exception):
    """The generated-library output directory cannot be created or replaced."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Cannot write generated library at {path}")
        self.path = path


class GeneratedModuleSyntaxError(Exception):
    """A generated module failed to compile — a generator bug."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Generated module does not compile: {path}")
        self.path = path


class DuplicateSymbolError(Exception):
    """Generated symbols in a module still collide after deduplication."""

    def __init__(self, section_key: str, symbols: list[str]) -> None:
        super().__init__(
            f"Generated module {section_key!r} has colliding symbols even "
            f"after part-code suffixing: {', '.join(sorted(symbols))}",
        )
