"""Tests for generated documentation API reference macros."""

from collections.abc import Callable

import docs_api_reference
import ldraw


class MacroEnv:
    """Minimal macro registry for testing Zensical macro registration."""

    def __init__(self) -> None:
        self.macro_fn: Callable[[], str] | None = None

    def macro(self, fn: Callable[[], str]) -> Callable[[], str]:
        """Register a macro function."""
        self.macro_fn = fn
        return fn


def test_public_api_reference_uses_canonical_public_exports() -> None:
    env = MacroEnv()
    docs_api_reference.define_env(env)

    assert env.macro_fn is not None
    markdown = env.macro_fn()
    directives = [
        line.removeprefix("::: ")
        for line in markdown.splitlines()
        if line.startswith("::: ")
    ]

    assert len(directives) == len(ldraw.__all__)
    assert "ldraw.generation.generate" in directives
    assert "ldraw.generate" not in directives
    assert markdown.count("show_root_heading: true") == len(ldraw.__all__)
