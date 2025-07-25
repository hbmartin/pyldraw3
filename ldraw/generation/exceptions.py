"""Exception classes for library generation."""


class NoLibrarySelected(Exception):
    """Exception raised when no library is selected."""


class UnwritableOutput(Exception):
    """Exception raised when output directory is not writable."""
