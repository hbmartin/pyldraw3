"""Emit a PEP 561 stub package for the generated ldraw.library modules."""

from __future__ import annotations

from pathlib import Path

from ldraw.errors import LibraryNotGeneratedError


def write_stub_package(generated_path: Path | str, out_dir: Path | str) -> Path:
    """Mirror the generated library into ``<out_dir>/ldraw-stubs``.

    The generated modules are plain assignments, so their source doubles as
    valid stub content. The resulting ``ldraw-stubs`` directory is a PEP 561
    partial stub package: type checkers resolve ``ldraw.library.*`` from it
    and fall back to the installed package for everything else.
    """
    library_dir = Path(generated_path) / "library"
    if not (library_dir / "__init__.py").is_file():
        raise LibraryNotGeneratedError(str(generated_path))
    stubs_dir = Path(out_dir) / "ldraw-stubs"
    library_stubs = stubs_dir / "library"
    for source in sorted(library_dir.rglob("*.py")):
        target = library_stubs / source.relative_to(library_dir).with_suffix(".pyi")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (stubs_dir / "py.typed").write_text("partial\n")
    return stubs_dir
