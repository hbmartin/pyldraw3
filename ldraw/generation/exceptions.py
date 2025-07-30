"""Exception classes for library generation."""


class NoLibrarySelectedError(Exception):
    """Exception raised when no library is selected."""


class UnwritableOutputError(Exception):
    """Exception raised when output directory is not writable."""
