"""Exception classes for library generation."""


class NoLibrarySelected(Exception):
    """Exception raised when no library is selected."""

    pass


class UnwritableOutput(Exception):
    """Exception raised when output directory is not writable."""

    pass
