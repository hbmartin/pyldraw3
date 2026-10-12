"""Invocation-local explicit library selection."""

from contextvars import ContextVar

library_argument: ContextVar[str | None] = ContextVar("library_argument", default=None)
