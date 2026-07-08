"""Command-line interface for the pyldraw3 package.

Provides subcommands to download the LDraw parts library, generate the
ldraw.library Python modules, query the parts catalog, validate LDraw
files, show the configuration, and print the version.
"""

import sys
from argparse import ArgumentParser
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from zipfile import BadZipFile

import requests
import yaml

from ldraw import generate as do_generate
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.errors import LibraryNotGeneratedError
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.parts import CatalogEntry, PartCategory, Parts
from ldraw.stubs import write_stub_package
from ldraw.utils import camel, clean
from ldraw.validation import iter_ldr_issues

PACKAGE_NAME = "pyldraw3"
DEFAULT_SEARCH_LIMIT = 25


def build_parser() -> ArgumentParser:
    """Build the argument parser for the ldraw CLI."""
    parser = ArgumentParser(
        prog="ldraw",
        description=(
            "Download the LDraw parts library and generate the "
            "ldraw.library Python modules."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    download_parser = subparsers.add_parser(
        "download",
        help="Download and unpack an LDraw parts library release.",
    )
    download_parser.add_argument(
        "--version",
        default=COMPLETE_VERSION,
        help=f"LDraw library release, e.g. 2018-02 (default: {COMPLETE_VERSION}).",
    )
    download_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Do not ask for confirmation.",
    )

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate the ldraw.library modules from the downloaded library.",
    )
    generate_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Do not ask for confirmation.",
    )
    generate_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Regenerate even if the generated library is already up to date.",
    )

    parts_parser = subparsers.add_parser("parts", help="Query the parts catalog.")
    parts_subparsers = parts_parser.add_subparsers(
        dest="parts_command",
        metavar="subcommand",
        required=True,
    )
    search_parser = parts_subparsers.add_parser(
        "search",
        help="Search parts by description or code.",
    )
    search_parser.add_argument("term", help="Case-insensitive substring to match.")
    search_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SEARCH_LIMIT,
        help=f"Maximum matches to print (default: {DEFAULT_SEARCH_LIMIT}).",
    )
    info_parser = parts_subparsers.add_parser(
        "info",
        help="Show details for one part code.",
    )
    info_parser.add_argument("code", help="LDraw part code, e.g. 3001.")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate an LDraw file (.ldr, .mpd, or .dat).",
    )
    validate_parser.add_argument(
        "file",
        type=Path,
        help="Path to the file to validate.",
    )

    stubs_parser = subparsers.add_parser(
        "stubs",
        help="Write a type-stub package for ldraw.library into your project.",
    )
    stubs_parser.add_argument(
        "--out",
        type=Path,
        default=Path(),
        help="Directory to write ldraw-stubs into (default: current directory).",
    )

    subparsers.add_parser("config", help="Print the current configuration.")
    subparsers.add_parser("version", help="Print the installed pyldraw3 version.")
    return parser


def _confirm(prompt: str, *, yes: bool) -> bool:
    """Return True if the user consented (or consent is implied)."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Non-interactive session detected, proceeding without confirmation.")
        return True
    answer = input(f"{prompt} [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def download_command(*, version: str, yes: bool) -> int:
    """Download an LDraw library release and point the config at it."""
    prompt = (
        f"This will download the {version!r} LDraw library release "
        f"(~80 MB for {COMPLETE_VERSION!r}). Continue?"
    )
    if not _confirm(prompt, yes=yes):
        print("Aborted.")
        return 1

    try:
        release_id = do_download(version=version, show_progress=sys.stderr.isatty())
    except (requests.RequestException, ValueError, BadZipFile) as exc:
        print(f"Download failed: {exc}")
        return 1

    config = Config.load()
    config.ldraw_library_path = str(cache_ldraw / version)
    config.write()

    print(f"Downloaded LDraw library release {release_id}.")
    print(f"Configured ldraw_library_path: {config.ldraw_library_path}")
    return 0


def generate_command(*, yes: bool, force: bool) -> int:
    """Generate the ldraw.library modules after confirmation."""
    config = Config.load()
    prompt = f"This will delete and regenerate {config.generated_path}. Continue?"
    if not _confirm(prompt, yes=yes):
        print("Aborted.")
        return 1

    try:
        do_generate(config=config, force=force)
    except UnwritableOutputError:
        print(f"{config.generated_path} is unwritable, select another out directory")
        return 1
    return 0


def _parts_lst_path() -> Path:
    return Path(Config.load().ldraw_library_path) / "ldraw" / "parts.lst"


def _load_parts() -> Parts | None:
    """Load the configured parts catalog, or None with a hint when missing."""
    parts_lst = _parts_lst_path()
    if not parts_lst.exists():
        print(f"parts.lst not found at {parts_lst}; run `ldraw download` first.")
        return None
    return Parts.get(parts_lst)


def _suggested_import(entry: CatalogEntry) -> str | None:
    """Return the generated-library import statement for a catalog entry."""
    class_name = clean(camel(entry.description))
    if entry.minifig_section is not None:
        module = f"ldraw.library.parts.minifig.{entry.minifig_section.value}"
    elif entry.category is not PartCategory.OTHER:
        module = f"ldraw.library.parts.{entry.category.module_name}"
    else:
        return None
    return f"from {module} import {class_name}"


def parts_search_command(*, term: str, limit: int) -> int:
    """Search the parts catalog by description or code substring."""
    if (parts := _load_parts()) is None:
        return 1
    needle = term.lower()
    matches = sorted(
        (
            entry
            for entry in parts.catalog.by_code.values()
            if needle in entry.description.lower() or needle in entry.code.lower()
        ),
        key=lambda entry: entry.description,
    )
    if not matches:
        print(f"No parts found matching {term!r}.")
        return 1
    for entry in matches[:limit]:
        print(f"{entry.code:<12} {entry.category.value:<20} {entry.description}")
    if len(matches) > limit:
        print(f"... and {len(matches) - limit} more (use --limit).")
    return 0


def parts_info_command(*, code: str) -> int:
    """Show catalog details for one part code."""
    if (parts := _load_parts()) is None:
        return 1
    entry = parts.get_entry_by_code(code)
    if entry is None:
        print(f"No part with code {code!r}.")
        return 1
    print(f"code: {entry.code}")
    print(f"description: {entry.description}")
    print(f"category: {entry.category.value}")
    if entry.minifig_section is not None:
        print(f"minifig section: {entry.minifig_section.value}")
    if entry.part is not None:
        print(f"file: {entry.part.path}")
    if (import_line := _suggested_import(entry)) is not None:
        print(f"import: {import_line}")
    return 0


def validate_command(*, file: Path) -> int:
    """Validate an LDraw file, reporting issues with line numbers."""
    if not file.is_file():
        print(f"{file}: not found")
        return 1
    parts_lst = _parts_lst_path()
    parts = Parts.get(parts_lst) if parts_lst.exists() else None
    if parts is None:
        print("note: no parts library found; skipping unknown-part checks")
    issues = list(iter_ldr_issues(file, parts))
    for issue in issues:
        print(f"{file}:{issue.line_number}: {issue.message}")
    if issues:
        plural = "s" if len(issues) != 1 else ""
        print(f"{file}: {len(issues)} issue{plural} found")
        return 1
    print(f"{file}: OK")
    return 0


def stubs_command(*, out: Path) -> int:
    """Write the ldraw-stubs package for IDE autocomplete and type checking."""
    try:
        stubs_dir = write_stub_package(Config.load().generated_path, out)
    except LibraryNotGeneratedError as exc:
        print(exc)
        return 1
    print(f"Wrote stub package to {stubs_dir}")
    return 0


def config_command() -> int:
    """Print the current pyldraw configuration as YAML."""
    print(yaml.dump(Config.load().to_dict()))
    return 0


def version_command() -> int:
    """Print the installed pyldraw3 package version."""
    try:
        print(package_version(PACKAGE_NAME))
    except PackageNotFoundError:
        print("unknown (not installed)")
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911 - one return per subcommand
    """Run the ldraw CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    match args.command:
        case "download":
            return download_command(version=args.version, yes=args.yes)
        case "generate":
            return generate_command(yes=args.yes, force=args.force)
        case "parts" if args.parts_command == "search":
            return parts_search_command(term=args.term, limit=args.limit)
        case "parts":
            return parts_info_command(code=args.code)
        case "validate":
            return validate_command(file=args.file)
        case "stubs":
            return stubs_command(out=args.out)
        case "config":
            return config_command()
        case "version":
            return version_command()
        case _:
            parser.print_help()
            return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
