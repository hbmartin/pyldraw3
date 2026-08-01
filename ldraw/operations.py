"""Cooperative cancellation primitives for synchronous public operations."""

from __future__ import annotations

from threading import Event


class OperationCancelled(Exception):  # noqa: N818 - public action/state spelling
    """A caller requested cancellation of an in-progress operation.

    Deliberately derives from ``Exception`` rather than ``RuntimeError``:
    setup helpers such as ``ensure_library`` wrap genuine failures in
    ``RuntimeError``, so a caller's ``except RuntimeError`` must not
    misreport a user-requested cancel as a failure.
    """

    def __init__(self) -> None:
        super().__init__("operation cancelled")


class CancellationToken:
    """Thread-safe cancellation token shared by library operations."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation; safe to call repeatedly from any thread."""
        self._event.set()

    def raise_if_cancelled(self) -> None:
        """Raise ``OperationCancelled`` when cancellation was requested."""
        if self.cancelled:
            raise OperationCancelled


def check_cancelled(cancellation: CancellationToken | None) -> None:
    """Check an optional token without duplicating guards at every call site."""
    if cancellation is not None:
        cancellation.raise_if_cancelled()


__all__ = ["CancellationToken", "OperationCancelled"]
