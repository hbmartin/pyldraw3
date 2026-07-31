"""Command-line interface for the pyldraw3 package.

Provides subcommands to download the LDraw parts library, generate the
ldraw.library Python modules, query the parts catalog, validate LDraw
files, show the configuration, and print the version.
"""

import sys
from argparse import ArgumentParser, Namespace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from zipfile import BadZipFile

import requests
import yaml

from ldraw import generate as do_generate
from ldraw.bom import BomRow, rows_to_csv, rows_to_json
from ldraw.catalog import catalog_db_path, load_parts
from ldraw.config import Config
from ldraw.diagnostics import DiagnosticCode
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.errors import (
    ConfigLoadError,
    CouldNotDetermineLatestVersionError,
    LibraryNotGeneratedError,
    PartError,
)
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.instruction_artifacts import (
    instruction_manifest,
    manifest_json,
    write_instruction_manifest,
    write_instruction_snapshots,
)
from ldraw.instructions import (
    CameraState,
    InstructionDocument,
    InstructionIssue,
    InstructionStep,
    iter_instruction_issues,
)
from ldraw.model import read_model
from ldraw.parts import CatalogEntry, Parts
from ldraw.snippets import suggested_import
from ldraw.stubs import write_stub_package
from ldraw.validation import Severity, iter_ldr_issues

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
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )

    bom_parser = subparsers.add_parser(
        "bom",
        help="Print a bill of materials for an LDraw model file.",
    )
    bom_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    bom_parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format (default: table).",
    )
    bom_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write output to a file instead of stdout.",
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

    instructions_parser = subparsers.add_parser(
        "instructions",
        help="Inspect, validate, and export renderer-neutral instructions.",
    )
    instruction_subparsers = instructions_parser.add_subparsers(
        dest="instructions_command",
        metavar="subcommand",
        required=True,
    )
    inspect_parser = instruction_subparsers.add_parser(
        "inspect",
        help="Print section-local instruction step summaries.",
    )
    inspect_parser.add_argument("file", type=Path, help="LDraw model file.")
    inspect_parser.add_argument("--section", help="Inspect one reachable section.")
    inspect_parser.add_argument(
        "--parts",
        action="store_true",
        help="Show each step's added parts tray.",
    )
    instruction_validate_parser = instruction_subparsers.add_parser(
        "validate",
        help="Run LDraw and instruction-structure validation.",
    )
    instruction_validate_parser.add_argument(
        "file",
        type=Path,
        help="LDraw model file.",
    )
    instruction_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    instruction_validate_parser.add_argument(
        "--max-parts",
        type=int,
        default=None,
        help="Warn when a step adds more than this many expanded parts.",
    )
    export_parser = instruction_subparsers.add_parser(
        "export",
        help="Write a schema-versioned JSON instruction manifest.",
    )
    export_parser.add_argument("file", type=Path, help="LDraw model file.")
    export_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write to a file instead of stdout.",
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing manifest file.",
    )
    snapshots_parser = instruction_subparsers.add_parser(
        "snapshots",
        help="Write cumulative MPD/LDR snapshots and their manifest.",
    )
    snapshots_parser.add_argument("file", type=Path, help="LDraw model file.")
    snapshots_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for the snapshot bundle.",
    )
    snapshots_parser.add_argument(
        "--section",
        help="Generate snapshots for one reachable section.",
    )
    snapshots_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate files owned by an existing pyldraw3 manifest.",
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
    except (
        requests.RequestException,
        ValueError,
        BadZipFile,
        CouldNotDetermineLatestVersionError,
        OSError,
    ) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    config = Config.load()
    config.ldraw_library_path = str(cache_ldraw / version)
    try:
        config.write()
    except OSError as exc:
        print(f"Could not update configuration: {exc}", file=sys.stderr)
        return 1

    print(f"Downloaded LDraw library release {release_id}.", file=sys.stderr)
    print(
        f"Configured ldraw_library_path: {config.ldraw_library_path}",
        file=sys.stderr,
    )
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
        print(
            f"{config.generated_path} is unwritable, select another out directory",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError:
        print(
            f"LDraw library not found under {config.ldraw_library_path}; "
            "run `ldraw download` first.",
            file=sys.stderr,
        )
        return 1
    print(
        "Run 'ldraw stubs' from your project root to refresh the ldraw-stubs "
        "package for IDE autocomplete and type checking.",
    )
    return 0


def _parts_lst_path() -> Path:
    return Path(Config.load().ldraw_library_path) / "ldraw" / "parts.lst"


def _try_load_parts(*, build_index: bool = False) -> Parts | None:
    """Load the configured parts catalog, or None when missing."""
    parts_lst = _parts_lst_path()
    if not parts_lst.exists():
        return None
    generated_path = Config.load().generated_path
    if build_index and not catalog_db_path(generated_path).is_file():
        print("Building parts index (first run may take a while)...", file=sys.stderr)
    return load_parts(parts_lst, generated_path, build_index=build_index)


def _load_parts() -> Parts | None:
    """Load the configured parts catalog, or None with a hint when missing.

    Catalog-querying commands pass through here, so a missing or stale
    index is built and persisted as a side effect.
    """
    if (parts := _try_load_parts(build_index=True)) is None:
        print(
            f"parts.lst not found at {_parts_lst_path()}; run `ldraw download` first.",
            file=sys.stderr,
        )
    return parts


def _suggested_import(entry: CatalogEntry) -> str | None:
    """Return the generated-library import statement for a catalog entry."""
    return suggested_import(entry)


def parts_search_command(*, term: str, limit: int) -> int:
    """Search the parts catalog through the shared public search API."""
    if (parts := _load_parts()) is None:
        return 1
    matches = parts.catalog.search(term)
    if not matches:
        print(f"No parts found matching {term!r}.", file=sys.stderr)
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
        print(f"No part with code {code!r}.", file=sys.stderr)
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


def validate_command(*, file: Path, strict: bool = False) -> int:
    """Validate an LDraw file, reporting issues with line numbers."""
    if not file.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    parts = _try_load_parts()
    if parts is None:
        print(
            "note: no parts library found; skipping unknown-part and colour checks",
            file=sys.stderr,
        )
    try:
        issues = list(iter_ldr_issues(file, parts))
    except UnicodeDecodeError as exc:
        print(f"{file}: error: not valid UTF-8 text ({exc})", file=sys.stderr)
        return 1
    if decode_issue := next(
        (issue for issue in issues if issue.code is DiagnosticCode.IO_DECODE_FAILED),
        None,
    ):
        print(f"{file}: error: {decode_issue.message}", file=sys.stderr)
        return 1
    for issue in issues:
        print(f"{file}:{issue.line_number}: {issue.severity}: {issue.message}")
    if not issues:
        print(f"{file}: OK")
        return 0
    errors = sum(1 for issue in issues if issue.severity is Severity.ERROR)
    warnings = len(issues) - errors
    print(f"{file}: {errors} error(s), {warnings} warning(s)")
    return 1 if errors or (warnings and strict) else 0


def _format_bom_table(rows: list[BomRow]) -> str:
    """Format BOM rows as an aligned text table."""
    if not rows:
        return "no pieces"
    lines = [f"{'qty':>5}  {'part':<12} {'colour':<20} description"]
    for row in rows:
        colour = row.colour_name or (
            str(row.colour_code) if row.colour_code is not None else ""
        )
        line = f"{row.quantity:>5}  {row.part:<12} {colour:<20} {row.description or ''}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def _format_bom(rows: list[BomRow], *, output_format: str) -> str:
    """Format BOM rows in the requested output format."""
    match output_format:
        case "csv":
            return rows_to_csv(rows)
        case "json":
            return rows_to_json(rows)
        case _:
            return _format_bom_table(rows)


def bom_command(*, file: Path, output_format: str, out: Path | None) -> int:
    """Print or write a bill of materials for an LDraw model file."""
    if not file.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    parts = _try_load_parts()
    if parts is None:
        print(
            "note: no parts library found; descriptions and colour names omitted",
            file=sys.stderr,
        )
    try:
        model = read_model(file)
        rows = model.bill_of_materials(parts=parts)
    except (PartError, UnicodeDecodeError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1
    text = _format_bom(rows, output_format=output_format)
    if not text.endswith("\n"):
        text = f"{text}\n"
    if out is not None:
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"Could not write {out}: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {len(rows)} rows to {out}")
    else:
        print(text, end="")
    return 0


def stubs_command(*, out: Path) -> int:
    """Write the ldraw-stubs package for IDE autocomplete and type checking."""
    try:
        stubs_dir = write_stub_package(
            generated_path=Config.load().generated_path,
            out_dir=out,
        )
    except LibraryNotGeneratedError as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Could not write stubs to {out}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote stub package to {stubs_dir}")
    return 0


def _instruction_document(
    *,
    file: Path,
    parts: Parts,
) -> InstructionDocument | None:
    """Read an instruction document, printing user-facing parse errors."""
    if not file.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return None
    try:
        return read_model(file).instruction_document(parts=parts)
    except (OSError, PartError, UnicodeDecodeError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return None


def _rotation_label(step: InstructionStep) -> str:
    if step.rotation is None:
        return "-"
    if step.rotation.angles is None:
        return step.rotation.mode.value
    angles = ",".join(f"{value:g}" for value in step.rotation.angles)
    return f"{step.rotation.mode.value}({angles})"


def instructions_inspect_command(
    *,
    file: Path,
    section_name: str | None,
    show_parts: bool,
) -> int:
    """Print one summary row per instruction step."""
    if (parts := _load_parts()) is None:
        return 1
    if (document := _instruction_document(file=file, parts=parts)) is None:
        return 1
    try:
        sections = (
            document.sections
            if section_name is None
            else (document.section(section_name),)
        )
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 1
    print(
        "section  step  direct  expanded  cumulative  rotation  camera  "
        "callouts  group  page  suppressed"
    )
    for section in sections:
        for step in section.steps:
            print(
                f"{section.name}  {step.number:>4}  {len(step.added_pieces):>6}  "
                f"{len(step.added_occurrences()):>8}  "
                f"{len(step.cumulative_occurrences()):>10}  "
                f"{_rotation_label(step):<12}  "
                f"{'yes' if step.camera != CameraState() else '-':<6}  "
                f"{len(step.callouts):>8}  "
                f"{step.multi_step_group or '-':>5}  "
                f"{'yes' if step.page_break_before else '-':>4}  "
                f"{'yes' if step.suppressed else '-'}"
            )
            if show_parts:
                tray = _format_bom_table(step.added_bill_of_materials(parts=parts))
                print("\n".join(f"    {line}" for line in tray.splitlines()))
    return 0


def _print_instruction_issue(file: Path, issue: InstructionIssue) -> None:
    line = "-" if issue.line_number is None else str(issue.line_number)
    print(
        f"{file}:{issue.section}:{line}: {issue.severity}: "
        f"[{issue.code}] {issue.message}"
    )


def instructions_validate_command(
    *,
    file: Path,
    strict: bool,
    max_parts: int | None,
) -> int:
    """Run raw LDraw and semantic instruction validation."""
    if max_parts is not None and max_parts < 0:
        print("--max-parts must be zero or greater", file=sys.stderr)
        return 1
    if (parts := _load_parts()) is None:
        return 1
    if (document := _instruction_document(file=file, parts=parts)) is None:
        return 1
    try:
        ldraw_issues = list(iter_ldr_issues(file, parts))
        instruction_issues = list(
            iter_instruction_issues(document, max_parts=max_parts)
        )
    except (OSError, PartError, UnicodeDecodeError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1
    for issue in ldraw_issues:
        print(f"{file}:{issue.line_number}: {issue.severity}: {issue.message}")
    for issue in instruction_issues:
        _print_instruction_issue(file, issue)
    severities = [
        *(issue.severity for issue in ldraw_issues),
        *(issue.severity for issue in instruction_issues),
    ]
    errors = severities.count(Severity.ERROR)
    warnings = severities.count(Severity.WARNING)
    if not severities:
        print(f"{file}: OK")
        return 0
    print(f"{file}: {errors} error(s), {warnings} warning(s)")
    return 1 if errors or (strict and warnings) else 0


def instructions_export_command(
    *,
    file: Path,
    output: Path | None,
    force: bool,
) -> int:
    """Write a deterministic instruction JSON manifest."""
    if (parts := _load_parts()) is None:
        return 1
    if (document := _instruction_document(file=file, parts=parts)) is None:
        return 1
    try:
        if output is None:
            print(
                manifest_json(instruction_manifest(document, parts=parts, source=file)),
                end="",
            )
        else:
            write_instruction_manifest(
                document,
                parts=parts,
                output=output,
                source=file,
                force=force,
            )
            print(f"Wrote instruction manifest to {output}", file=sys.stderr)
    except (OSError, PartError, ValueError) as exc:
        print(f"Could not export instructions: {exc}", file=sys.stderr)
        return 1
    return 0


def instructions_snapshots_command(
    *,
    file: Path,
    output: Path,
    section_name: str | None,
    force: bool,
) -> int:
    """Write paired cumulative MPD/LDR snapshots and their manifest."""
    if (parts := _load_parts()) is None:
        return 1
    if (document := _instruction_document(file=file, parts=parts)) is None:
        return 1
    try:
        manifest_path = write_instruction_snapshots(
            document,
            parts=parts,
            output=output,
            source=file,
            section_name=section_name,
            force=force,
        )
    except (OSError, KeyError, PartError, ValueError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) else str(exc)
        print(f"Could not write instruction snapshots: {message}", file=sys.stderr)
        return 1
    print(f"Wrote instruction snapshots and {manifest_path}", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    """Run the ldraw CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args=args, parser=parser)
    except ConfigLoadError as exc:
        print(exc, file=sys.stderr)
        return 1


def _dispatch(  # noqa: C901, PLR0911 - one branch per subcommand
    *,
    args: Namespace,
    parser: ArgumentParser,
) -> int:
    """Dispatch parsed arguments to the matching subcommand."""
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
            return validate_command(file=args.file, strict=args.strict)
        case "bom":
            return bom_command(
                file=args.file,
                output_format=args.format,
                out=args.output,
            )
        case "stubs":
            return stubs_command(out=args.out)
        case "instructions":
            return _dispatch_instructions(args)
        case "config":
            return config_command()
        case "version":
            return version_command()
        case _:
            parser.print_help()
            return 0


def _dispatch_instructions(args: Namespace) -> int:
    """Dispatch one nested instruction subcommand."""
    match args.instructions_command:
        case "inspect":
            return instructions_inspect_command(
                file=args.file,
                section_name=args.section,
                show_parts=args.parts,
            )
        case "validate":
            return instructions_validate_command(
                file=args.file,
                strict=args.strict,
                max_parts=args.max_parts,
            )
        case "export":
            return instructions_export_command(
                file=args.file,
                output=args.output,
                force=args.force,
            )
        case "snapshots":
            return instructions_snapshots_command(
                file=args.file,
                output=args.out,
                section_name=args.section,
                force=args.force,
            )
        case _:
            msg = f"Unhandled instructions subcommand: {args.instructions_command!r}"
            raise AssertionError(msg)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
