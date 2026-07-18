"""Tests for generated documentation API reference macros."""

from collections.abc import Callable
from types import ModuleType

import pytest

import docs_api_reference
import ldraw


class MacroEnv:
    """Minimal macro registry for testing Zensical macro registration."""

    def __init__(self) -> None:
        self.macro_fn: Callable[..., str] | None = None

    def macro(self, fn: Callable[..., str]) -> Callable[..., str]:
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

    expected_count = len(ldraw.__all__) + len(docs_api_reference.SUPPLEMENTAL_API)
    assert len(directives) == expected_count
    assert "ldraw.generation.generate" in directives
    assert "ldraw.generate" not in directives
    assert "ldraw.config.Config" in directives
    assert "ldraw.bom.rows_to_csv" in directives
    assert "ldraw.errors.PartNotFoundError" in directives
    assert markdown.count("show_root_heading: true") == expected_count


def test_reference_markdown_deduplicates_canonical_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = ModuleType("sample_package")

    class Exported:
        pass

    Exported.__module__ = "sample_package"
    Exported.__qualname__ = "Exported"
    package.__all__ = ["First", "Second"]
    package.First = Exported
    package.Second = Exported

    monkeypatch.setattr(
        docs_api_reference.importlib,
        "import_module",
        lambda package_name: package,
    )

    env = MacroEnv()
    docs_api_reference.define_env(env)

    assert env.macro_fn is not None
    markdown = env.macro_fn("sample_package")
    directives = [
        line.removeprefix("::: ")
        for line in markdown.splitlines()
        if line.startswith("::: ")
    ]

    assert directives == ["sample_package.Exported"]
    assert markdown.count("show_root_heading: true") == 1


def test_public_api_reference_reports_stale_all_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = ModuleType("sample_package")
    package.__all__ = ["Missing"]

    monkeypatch.setattr(
        docs_api_reference.importlib,
        "import_module",
        lambda package_name: package,
    )

    env = MacroEnv()
    docs_api_reference.define_env(env)

    assert env.macro_fn is not None
    with pytest.raises(AttributeError) as exc_info:
        env.macro_fn("sample_package")

    expected = (
        "sample_package.__all__ includes 'Missing', but "
        "sample_package has no export named 'Missing'"
    )
    assert str(exc_info.value) == expected


def test_supplemental_reports_stale_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docs_api_reference,
        "SUPPLEMENTAL_API",
        (("ldraw.bom", "does_not_exist"),),
    )

    env = MacroEnv()
    docs_api_reference.define_env(env)

    assert env.macro_fn is not None
    with pytest.raises(AttributeError, match=r"does_not_exist"):
        env.macro_fn()
