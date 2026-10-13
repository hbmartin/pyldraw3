"""Platform-independent checks for unsafe ZIP member paths."""

from pathlib import PurePosixPath, PureWindowsPath


def is_unsafe_zip_member(filename: str) -> bool:
    """Reject absolute paths and parent traversal using either path syntax."""
    posix_path = PurePosixPath(filename)
    windows_path = PureWindowsPath(filename)
    return (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    )
