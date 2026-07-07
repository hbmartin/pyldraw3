"""Command-line interface for the pyldraw3 package.

Provides subcommands to download the LDraw parts library, generate the
ldraw.library Python modules, show the configuration, and print the version.
"""

import sys
from argparse import ArgumentParser
from importlib.metadata import version as package_version

import yaml

from ldraw import generate as do_generate
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.generation.exceptions import UnwritableOutputError

PACKAGE_NAME = "pyldraw3"


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

    release_id = do_download(version=version, show_progress=sys.stderr.isatty())

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


def config_command() -> int:
    """Print the current pyldraw configuration as YAML."""
    print(yaml.dump(Config.load().__dict__))
    return 0


def version_command() -> int:
    """Print the installed pyldraw3 package version."""
    print(package_version(PACKAGE_NAME))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the ldraw CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    match args.command:
        case "download":
            return download_command(version=args.version, yes=args.yes)
        case "generate":
            return generate_command(yes=args.yes, force=args.force)
        case "config":
            return config_command()
        case "version":
            return version_command()
        case _:
            parser.print_help()
            return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
