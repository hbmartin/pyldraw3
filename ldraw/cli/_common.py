"""Runtime services for the common commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import BadZipFile, is_zipfile

from ldraw.catalog import catalog_db_path, load_parts
from ldraw.config import Config

if TYPE_CHECKING:
    from ldraw.diagnostics import Diagnostic
    from ldraw.parts import Parts


from ldraw.cli._selection import library_argument


def _confirm(prompt: str, *, yes: bool) -> bool:
    """Return True if the user consented (or consent is implied)."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Non-interactive session detected, proceeding without confirmation.")
        return True
    answer = input(f"{prompt} [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _parts_lst_path() -> Path:
    from ldraw.library_access import data_directory  # noqa: PLC0415

    return data_directory(Config.load().ldraw_library_path) / "parts.lst"


def _try_load_parts(
    *,
    build_index: bool = False,
    connection_shadows: tuple[Path, ...] = (),
    studio_metadata: tuple[Path, ...] = (),
) -> Parts | None:
    """Load the configured parts catalog, or None when missing."""
    if (
        library_argument.get() is not None
        or os.environ.get("LDRAW_DIR")
        or os.environ.get("LDRAWDIR")
    ):
        from ldraw.library_access import select_library  # noqa: PLC0415
        from ldraw.parts import Parts  # noqa: PLC0415

        parts = Parts.from_directory(
            select_library(library=library_argument.get()).directory
        )
        for source in connection_shadows:
            parts.add_connection_shadow(source)
        for source in studio_metadata:
            parts.add_studio_metadata(source)
        return parts
    parts_lst = _parts_lst_path()
    if not parts_lst.exists():
        from ldraw.library_access import select_library  # noqa: PLC0415
        from ldraw.parts import Parts  # noqa: PLC0415

        if (parts_lst.parent / "parts").is_dir():
            parts = Parts.from_directory(parts_lst.parent)
        else:
            try:
                selection = select_library()
            except FileNotFoundError:
                return None
            parts = Parts.from_directory(selection.directory)
        for source in connection_shadows:
            parts.add_connection_shadow(source)
        for source in studio_metadata:
            parts.add_studio_metadata(source)
        return parts
    generated_path = Config.load().generated_path
    if build_index and not catalog_db_path(generated_path).is_file():
        print("Building parts index (first run may take a while)...", file=sys.stderr)
    return load_parts(
        parts_lst,
        generated_path,
        build_index=build_index,
        connection_shadows=connection_shadows,
        studio_metadata=studio_metadata,
    )


def _load_parts(
    *,
    connection_shadows: tuple[Path, ...] = (),
    studio_metadata: tuple[Path, ...] = (),
) -> Parts | None:
    """Load the configured parts catalog, or None with a hint when missing.

    Catalog-querying commands pass through here, so a missing or stale
    index is built and persisted as a side effect.
    """
    if (
        parts := _try_load_parts(
            build_index=True,
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    ) is None:
        print(
            f"parts.lst not found at {_parts_lst_path()}; run `ldraw download` first.",
            file=sys.stderr,
        )
    return parts


def _invalid_connection_source(
    *,
    connection_shadows: tuple[Path, ...],
    studio_metadata: tuple[Path, ...],
) -> str | None:
    """Return an error message for the first unusable connection source."""
    for flag, sources in (
        ("--ldcad-shadow", connection_shadows),
        ("--studio-metadata", studio_metadata),
    ):
        for source in sources:
            path = Path(source).expanduser()
            if not path.exists():
                return f"{flag} source not found: {source}"
            if flag == "--ldcad-shadow":
                try:
                    valid = path.is_dir() or (path.is_file() and is_zipfile(path))
                except OSError:
                    valid = False
                if not valid:
                    return (
                        "--ldcad-shadow source must be a directory or ZIP/CSL "
                        f"archive: {source}"
                    )
                continue
            try:
                if not path.is_file():
                    return f"--studio-metadata source must be a JSON file: {source}"
                with path.open("rb") as source_file:
                    source_file.read(1)
            except OSError:
                return f"--studio-metadata source must be a JSON file: {source}"
    return None


def _load_parts_with_connection_sources(
    *,
    connection_shadows: tuple[Path, ...],
    studio_metadata: tuple[Path, ...],
) -> Parts | None:
    """Load parts with controlled failures for optional metadata sources."""
    try:
        return _load_parts(
            connection_shadows=connection_shadows,
            studio_metadata=studio_metadata,
        )
    except (BadZipFile, OSError) as error:
        _report_connection_source_error(error)
        return None


def _report_connection_source_error(error: BadZipFile | OSError) -> None:
    """Print one controlled failure from parts or metadata loading."""
    match error:
        case BadZipFile():
            message = f"could not load connection metadata source: {error}"
        case _:
            message = f"could not load parts or connection metadata: {error}"
    print(message, file=sys.stderr)


def _print_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
    *,
    fallback_path: Path,
) -> None:
    if not diagnostics:
        print(f"{fallback_path}: operation failed", file=sys.stderr)
        return
    for diagnostic in diagnostics:
        path = diagnostic.path or fallback_path
        section = f":{diagnostic.section}" if diagnostic.section else ""
        line = f":{diagnostic.line_number}" if diagnostic.line_number else ""
        print(
            f"{path}{section}{line}: {diagnostic.severity}: "
            f"[{diagnostic.code}] {diagnostic.message}",
            file=sys.stderr,
        )


def _write_report(text: str, *, out: Path | None, description: str) -> bool:
    rendered = text if text.endswith("\n") else f"{text}\n"
    if out is None:
        print(rendered, end="")
        return True
    try:
        out.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"Could not write {out}: {exc}", file=sys.stderr)
        return False
    print(f"Wrote {description} to {out}")
    return True


def _diagnostic_text(diagnostic: Diagnostic) -> str:
    location = diagnostic.section or "-"
    line = "-" if diagnostic.line_number is None else str(diagnostic.line_number)
    return (
        f"{diagnostic.severity}: [{diagnostic.code}] "
        f"{location}:{line}: {diagnostic.message}"
    )


def _print_report_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> None:
    if not diagnostics:
        return
    print(f"diagnostics: {len(diagnostics)}")
    for diagnostic in diagnostics:
        print(_diagnostic_text(diagnostic))
