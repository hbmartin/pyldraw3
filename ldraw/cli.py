"""Command-line interface for the pyldraw3 package.

Provides subcommands to download the LDraw parts library, generate the
ldraw.library Python modules, query geometry, validate and inspect LDraw
files, render previews, show the configuration, and print the version.
"""

import json
import re
import sys
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

import requests
import yaml

from ldraw import generate as do_generate
from ldraw.bom import BomRow, rows_to_csv, rows_to_json
from ldraw.catalog import catalog_db_path, load_parts
from ldraw.config import Config
from ldraw.connection_types import (
    AnnularProfile,
    ConnectionFeature,
    CylindricalProfile,
    FingerProfile,
    GenericProfile,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.errors import (
    ConfigLoadError,
    CouldNotDetermineLatestVersionError,
    LibraryNotGeneratedError,
    PartError,
)
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.geometry import Vector
from ldraw.inspection import (
    DEFAULT_PAGE_MARKER_PREFIX,
    ConnectionContact,
    ModelInspection,
    OccurrenceContact,
    StudContact,
    inspect_model,
)
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
from ldraw.model import load_model, read_model
from ldraw.part_geometry_types import BoundingBox
from ldraw.parts import CatalogEntry, Parts
from ldraw.rendering import RenderBackend, RenderResult, RenderView, render_preview
from ldraw.snippets import suggested_import
from ldraw.stubs import write_stub_package
from ldraw.validation import Severity, iter_ldr_issues

PACKAGE_NAME = "pyldraw3"
DEFAULT_SEARCH_LIMIT = 25
DEFAULT_RENDER_SIZE = (800, 600)
DEFAULT_RENDER_VIEWS = tuple(RenderView)
_SAFE_RENDER_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class _RenderPlan:
    """Validated paths and options for one atomic render operation."""

    source: Path
    views: tuple[RenderView, ...]
    dimensions: tuple[int, int]
    backend: RenderBackend | None
    destination: Path
    outputs: tuple[Path, ...]
    refresh: bool
    overwrite: bool


def build_parser() -> ArgumentParser:  # noqa: PLR0915 - CLI options stay explicit
    """Build the argument parser for the ldraw CLI."""
    parser = ArgumentParser(
        prog="ldraw",
        description=(
            "Manage LDraw libraries and create, inspect, validate, and render "
            "LDraw models."
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
        help="Search parts by code, description, category, or keywords.",
    )
    search_parser.add_argument(
        "term",
        help=(
            "Case-insensitive search terms; every whitespace-separated token "
            "must match, and results are ranked by relevance."
        ),
    )
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
    geometry_parser = parts_subparsers.add_parser(
        "geometry",
        help="Show recursively expanded geometry for one part code.",
    )
    geometry_parser.add_argument("code", help="LDraw part code, e.g. 3001.")
    geometry_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )

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

    model_inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect exact world bounds, provenance, contacts, and gaps.",
    )
    model_inspect_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    model_inspect_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    model_inspect_parser.add_argument(
        "--gap-threshold",
        type=float,
        default=5.0,
        help="Report nearest AABB gaps larger than this many LDU (default: 5).",
    )
    model_inspect_parser.add_argument(
        "--chronological",
        action="store_true",
        help="Exclude neighbours installed on a later attributed page.",
    )
    model_inspect_parser.add_argument(
        "--page-marker-prefix",
        default=DEFAULT_PAGE_MARKER_PREFIX,
        help=(
            "Comment prefix used to attribute pages "
            f"(default: {DEFAULT_PAGE_MARKER_PREFIX!r})."
        ),
    )
    model_inspect_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write output to a file instead of stdout.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Render a deterministic set of standard preview views.",
    )
    render_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    render_parser.add_argument(
        "--view",
        action="append",
        type=RenderView,
        choices=DEFAULT_RENDER_VIEWS,
        default=None,
        help="Standard view to render; repeat for multiple views.",
    )
    render_parser.add_argument(
        "--size",
        default=f"{DEFAULT_RENDER_SIZE[0]}x{DEFAULT_RENDER_SIZE[1]}",
        metavar="WIDTHxHEIGHT",
        help=(
            f"Image size (default: {DEFAULT_RENDER_SIZE[0]}x{DEFAULT_RENDER_SIZE[1]})."
        ),
    )
    render_parser.add_argument(
        "--backend",
        choices=("auto", *(backend.value for backend in RenderBackend)),
        default="auto",
        help="Renderer backend (default: auto).",
    )
    render_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: beside the model).",
    )
    render_parser.add_argument(
        "--prefix",
        default=None,
        help="Output filename prefix (default: model stem).",
    )
    render_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass cached previews and render fresh images.",
    )
    render_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing requested images after every view succeeds.",
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


def parts_geometry_command(*, code: str, output_format: str) -> int:
    """Show expanded geometry and completeness diagnostics for one part."""
    if (parts := _load_parts()) is None:
        return 1
    try:
        geometry = parts.geometry(code)
    except PartError as exc:
        print(exc, file=sys.stderr)
        return 1

    payload = {
        "bounds": _box_data(geometry.bounds),
        "code": geometry.code,
        "complete": geometry.complete,
        "connection_count": len(geometry.connections),
        "connections": [
            _connection_data(connection) for connection in geometry.connections
        ],
        "description": geometry.description,
        "diagnostics": [item.to_dict() for item in geometry.diagnostics],
        "point_count": len(geometry.points),
        "receptacle_count": len(geometry.receptacles),
        "stud_count": len(geometry.studs),
        "studs": [
            {
                "description": stud.description,
                "is_placeholder": stud.is_placeholder,
                "is_receptacle": stud.is_receptacle,
                "is_top_stud": stud.is_top_stud,
                "name": stud.name,
                "position": _vector_data(stud.position),
                "up": _vector_data(stud.up),
            }
            for stud in geometry.studs
        ],
        "top_stud_count": len(geometry.top_studs),
    }
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"code: {geometry.code}")
    print(f"description: {geometry.description}")
    print(f"complete: {'yes' if geometry.complete else 'no'}")
    print(f"expanded points: {len(geometry.points)}")
    print(f"connections: {len(geometry.connections)}")
    print(
        f"studs: {len(geometry.studs)} "
        f"({len(geometry.top_studs)} top, "
        f"{len(geometry.receptacles)} receptacles)"
    )
    if geometry.bounds is None:
        print("bounds: none")
    else:
        print(f"bounds min: {_format_vector(geometry.bounds.min)}")
        print(f"bounds max: {_format_vector(geometry.bounds.max)}")
        print(f"size: {_format_vector(geometry.bounds.size)}")
    _print_report_diagnostics(geometry.diagnostics)
    return 0


def inspect_command(  # noqa: PLR0913 - mirrors explicit CLI controls
    *,
    file: Path,
    output_format: str,
    gap_threshold: float,
    chronological: bool,
    page_marker_prefix: str,
    out: Path | None,
) -> int:
    """Inspect exact occurrence geometry, provenance, contacts, and gaps."""
    if gap_threshold < 0:
        print("--gap-threshold must be non-negative", file=sys.stderr)
        return 1
    if (parts := _load_parts()) is None:
        return 1

    loaded = load_model(file, parts=parts)
    if loaded.model is None:
        _print_diagnostics(loaded.diagnostics, fallback_path=file)
        return 1
    try:
        inspection = inspect_model(
            loaded.model,
            parts=parts,
            page_marker_prefix=page_marker_prefix,
        )
        contacts = inspection.contact_gaps(
            minimum_gap=gap_threshold,
            chronological=chronological,
        )
    except PartError as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1

    diagnostics = (*loaded.diagnostics, *inspection.diagnostics)
    complete = loaded.complete and inspection.complete
    if output_format == "json":
        text = json.dumps(
            _inspection_data(
                file=file,
                inspection=inspection,
                contacts=contacts,
                diagnostics=diagnostics,
                complete=complete,
                gap_threshold=gap_threshold,
                chronological=chronological,
            ),
            indent=2,
            sort_keys=True,
        )
    else:
        text = _format_inspection_table(
            file=file,
            inspection=inspection,
            contacts=contacts,
            diagnostics=diagnostics,
            complete=complete,
            gap_threshold=gap_threshold,
            chronological=chronological,
        )
    if not _write_report(text, out=out, description="inspection"):
        return 1
    return int(any(item.severity is Severity.ERROR for item in diagnostics))


def render_command(  # noqa: PLR0913 - explicit CLI controls
    *,
    file: Path,
    views: list[RenderView] | None,
    size: str,
    backend: str,
    output_dir: Path | None,
    prefix: str | None,
    refresh: bool,
    overwrite: bool,
) -> int:
    """Render a safe, deterministic standard-view set."""
    source = file.expanduser().resolve()
    if not source.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    try:
        plan = _build_render_plan(
            source=source,
            views=views,
            size=size,
            backend=backend,
            output_dir=output_dir,
            prefix=prefix,
            refresh=refresh,
            overwrite=overwrite,
        )
        staged_results = _execute_render_plan(plan)
    except (OSError, ValueError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1
    if staged_results is None:
        return 1

    _report_render_results(results=staged_results, outputs=plan.outputs)
    return 0


def _inspection_data(  # noqa: PLR0913 - report inputs are explicit
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
    diagnostics: tuple[Diagnostic, ...],
    complete: bool,
    gap_threshold: float,
    chronological: bool,
) -> dict[str, object]:
    return {
        "bounds": _box_data(inspection.bounds),
        "chronological": chronological,
        "complete": complete,
        "diagnostics": [item.to_dict() for item in diagnostics],
        "disconnected": [
            {
                "axis_gaps": _vector_data(contact.gap.axes),
                "gap": contact.gap.distance,
                "nearest_index": contact.nearest.index,
                "nearest_installation_page": (
                    contact.nearest.attribution.installation_page
                ),
                "nearest_part": contact.nearest.occurrence.part_code,
                "occurrence_index": contact.subject.index,
                "occurrence_installation_page": (
                    contact.subject.attribution.installation_page
                ),
                "occurrence_part": contact.subject.occurrence.part_code,
            }
            for contact in contacts
        ],
        "gap_threshold": gap_threshold,
        "geometry_count": len(inspection.occurrences),
        "connection_contacts": [
            _connection_contact_data(contact)
            for contact in inspection.connection_contacts()
        ],
        "model": str(file),
        "occurrence_count": inspection.occurrence_count,
        "occurrences": [
            {
                "bounds": _box_data(item.bounds),
                "colour": (
                    item.occurrence.colour.code
                    if item.occurrence.colour.code is not None
                    else item.occurrence.colour.rgb
                ),
                "effective_step_path": list(item.attribution.effective_step_path),
                "index": item.index,
                "installation_page": item.attribution.installation_page,
                "connection_count": len(item.connections),
                "local_point_count": len(item.local.points),
                "local_step_path": list(item.attribution.local_step_path),
                "model_path": list(item.attribution.model_path),
                "page_path": list(item.attribution.page_path),
                "part": item.occurrence.part_code,
                "position": _vector_data(item.occurrence.position),
                "reference_path": list(item.attribution.reference_path),
                "source_line": item.occurrence.source_line,
                "source_line_path": list(item.attribution.source_line_path),
                "source_model": item.occurrence.source_model.name,
                "source_page": item.attribution.source_page,
                "source_step": item.occurrence.source_step,
                "step": item.occurrence.step,
                "step_path": list(item.attribution.step_path),
                "stud_count": len(item.studs),
            }
            for item in inspection.occurrences
        ],
        "skipped_geometry": [
            {
                "diagnostic": skipped.diagnostic.to_dict(),
                "index": skipped.attribution.index,
                "model_path": list(skipped.attribution.model_path),
                "page_path": list(skipped.attribution.page_path),
                "part": skipped.attribution.occurrence.part_code,
                "reason": skipped.reason,
            }
            for skipped in inspection.skipped_geometry
        ],
        "stud_contacts": [
            _stud_contact_data(contact) for contact in inspection.stud_contacts()
        ],
    }


def _format_inspection_table(  # noqa: PLR0913 - report inputs are explicit
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
    diagnostics: tuple[Diagnostic, ...],
    complete: bool,
    gap_threshold: float,
    chronological: bool,
) -> str:
    bounds = (
        "none"
        if inspection.bounds is None
        else (
            f"{_format_vector(inspection.bounds.min)} .. "
            f"{_format_vector(inspection.bounds.max)}"
        )
    )
    lines = [
        f"model: {file}",
        f"complete: {'yes' if complete else 'no'}",
        (
            f"occurrences: {inspection.occurrence_count} "
            f"geometry: {len(inspection.occurrences)} "
            f"skipped: {len(inspection.skipped_geometry)}"
        ),
        f"world bounds: {bounds}",
        f"stud/part contacts: {len(inspection.stud_contacts())}",
        f"connection contacts: {len(inspection.connection_contacts())}",
        "",
        " index  install source part         world origin             model path",
    ]
    for item in inspection.occurrences:
        attribution = item.attribution
        lines.append(
            f"{item.index:6d}  {_page(attribution.installation_page):>7} "
            f"{_page(attribution.source_page):>6} "
            f"{item.occurrence.part_code:<12} "
            f"{_format_vector(item.occurrence.position):<24} "
            f"{' > '.join(attribution.model_path)}"
        )
    lines.extend(
        (
            f"{skipped.attribution.index:6d}  "
            f"{_page(skipped.attribution.installation_page):>7} "
            f"{_page(skipped.attribution.source_page):>6} "
            f"{skipped.attribution.occurrence.part_code:<12} "
            f"SKIPPED: {skipped.reason}"
        )
        for skipped in inspection.skipped_geometry
    )

    mode = "chronological" if chronological else "all occurrences"
    lines.extend(
        (
            "",
            f"nearest AABB gaps > {gap_threshold:g} LDU ({mode}): {len(contacts)}",
        )
    )
    lines.extend(
        (
            f"gap={contact.gap.distance:8.3f} "
            f"#{contact.subject.index}/{contact.subject.occurrence.part_code} "
            f"p{_page(contact.subject.attribution.installation_page)} -> "
            f"#{contact.nearest.index}/{contact.nearest.occurrence.part_code} "
            f"p{_page(contact.nearest.attribution.installation_page)} "
            f"axes={_format_vector(contact.gap.axes)}"
        )
        for contact in contacts
    )
    if diagnostics:
        lines.extend(("", f"diagnostics: {len(diagnostics)}"))
        lines.extend(_diagnostic_text(item) for item in diagnostics)
    return "\n".join(lines)


def _page(page: int | None) -> str:
    return "-" if page is None else str(page)


def _stud_contact_data(contact: StudContact) -> dict[str, object]:
    return {
        "position": _vector_data(contact.position),
        "stud_index": contact.stud_occurrence.index,
        "stud_name": contact.stud.name,
        "stud_part": contact.stud_occurrence.occurrence.part_code,
        "supported_index": contact.supported_occurrence.index,
        "supported_part": contact.supported_occurrence.occurrence.part_code,
    }


def _connection_contact_data(contact: ConnectionContact) -> dict[str, object]:
    return {
        "first_feature": contact.first.feature_id,
        "first_index": contact.first_occurrence.index,
        "first_kind": contact.first.kind.value,
        "second_feature": contact.second.feature_id,
        "second_index": contact.second_occurrence.index,
        "second_kind": contact.second.kind.value,
        "residual": {
            "alignment": contact.residual.alignment,
            "axial_gap": contact.residual.axial_gap,
            "distance": contact.residual.distance,
            "roll_alignment": contact.residual.roll_alignment,
        },
    }


def _connection_data(connection: ConnectionFeature) -> dict[str, object]:
    return {
        "axis": _vector_data(connection.axis),
        "compatible_parts": list(connection.compatible_parts),
        "confidence": connection.confidence,
        "feature_id": connection.feature_id,
        "freedoms": sorted(freedom.value for freedom in connection.freedoms),
        "group": connection.group,
        "kind": connection.kind.value,
        "length": connection.length,
        "name": connection.name,
        "occupied": connection.occupied,
        "occupied_by": connection.occupied_by,
        "owner_code": connection.owner_code,
        "position": _vector_data(connection.position),
        "profile": _connection_profile_data(connection),
        "provenance": list(connection.provenance),
        "radial": _vector_data(connection.radial),
        "role": connection.role.value,
        "source": connection.source.value,
    }


def _connection_profile_data(connection: ConnectionFeature) -> dict[str, object]:
    match connection.profile:
        case CylindricalProfile() as profile:
            return {
                "centered": profile.centered,
                "friction": profile.friction,
                "sections": [
                    {
                        "flexible": section.flexible,
                        "length": section.length,
                        "radius": section.radius,
                        "shape": section.shape.value,
                    }
                    for section in profile.sections
                ],
                "type": "cylindrical",
            }
        case FingerProfile() as profile:
            return {
                "detents": list(profile.detents),
                "first_role": profile.first_role.value,
                "radius": profile.radius,
                "sequence": list(profile.sequence),
                "type": "finger",
            }
        case AnnularProfile() as profile:
            return {
                "offset": profile.offset,
                "radius": profile.radius,
                "type": "annular",
                "width": profile.width,
            }
        case GenericProfile() as profile:
            return {
                "length": profile.length,
                "name": profile.name,
                "type": "generic",
            }


def _box_data(box: BoundingBox | None) -> dict[str, object] | None:
    if box is None:
        return None
    return {
        "max": _vector_data(box.max),
        "min": _vector_data(box.min),
        "size": _vector_data(box.size),
    }


def _vector_data(vector: Vector) -> list[float]:
    return [float(vector.x), float(vector.y), float(vector.z)]


def _format_vector(vector: Vector) -> str:
    return f"({float(vector.x):g}, {float(vector.y):g}, {float(vector.z):g})"


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


def _parse_render_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.casefold().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        message = f"bad size {value!r}; expected WIDTHxHEIGHT"
        raise ValueError(message) from exc
    if width <= 0 or height <= 0:
        message = "render width and height must be positive"
        raise ValueError(message)
    return width, height


def _build_render_plan(  # noqa: PLR0913 - mirrors explicit CLI controls
    *,
    source: Path,
    views: list[RenderView] | None,
    size: str,
    backend: str,
    output_dir: Path | None,
    prefix: str | None,
    refresh: bool,
    overwrite: bool,
) -> _RenderPlan:
    """Validate a render request and resolve all output paths up front."""
    dimensions = _parse_render_size(size)
    requested_views = tuple(views) if views is not None else DEFAULT_RENDER_VIEWS
    if len(set(requested_views)) != len(requested_views):
        message = "render views must be unique"
        raise ValueError(message)

    output_prefix = prefix if prefix is not None else source.stem
    if not _SAFE_RENDER_PREFIX.fullmatch(output_prefix):
        message = (
            "render prefix must start with an alphanumeric character and contain "
            "only alphanumerics, '.', '_', or '-'"
        )
        raise ValueError(message)

    destination = (
        output_dir.expanduser().resolve() if output_dir is not None else source.parent
    )
    outputs = tuple(
        destination / f"{output_prefix}.{view.value}.png" for view in requested_views
    )
    if conflicts := tuple(output for output in outputs if output.exists()):
        names = ", ".join(str(output) for output in conflicts)
        if not overwrite:
            message = f"output already exists: {names}"
            raise FileExistsError(message)

    selected_backend = None if backend == "auto" else RenderBackend(backend)
    return _RenderPlan(
        source=source,
        views=requested_views,
        dimensions=dimensions,
        backend=selected_backend,
        destination=destination,
        outputs=outputs,
        refresh=refresh,
        overwrite=overwrite,
    )


def _execute_render_plan(plan: _RenderPlan) -> tuple[RenderResult, ...] | None:
    """Stage every view and atomically promote the complete render set."""
    plan.destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".pyldraw-render-",
        dir=plan.destination,
    ) as tmp:
        temporary = Path(tmp)
        staged_results: list[RenderResult] = []
        for view, output in zip(plan.views, plan.outputs, strict=True):
            result = render_preview(
                plan.source,
                view=view,
                size=plan.dimensions,
                backend=plan.backend,
                output=temporary / output.name,
                refresh=plan.refresh,
            )
            if not result.complete:
                _print_diagnostics(result.diagnostics, fallback_path=plan.source)
                return None
            staged_results.append(result)
        results = tuple(staged_results)
        _promote_render_outputs(
            results,
            outputs=plan.outputs,
            temporary=temporary,
            overwrite=plan.overwrite,
        )
    return results


def _report_render_results(
    *,
    results: tuple[RenderResult, ...],
    outputs: tuple[Path, ...],
) -> None:
    """Print the final location and cache status of each rendered view."""
    for result, output in zip(results, outputs, strict=True):
        status = "CACHED" if result.cached else "RENDERED"
        print(f"{status}: {output}")


def _promote_render_outputs(
    results: tuple[RenderResult, ...],
    *,
    outputs: tuple[Path, ...],
    temporary: Path,
    overwrite: bool,
) -> None:
    """Promote a complete staged view set, rolling back destination changes."""
    backups_dir = temporary / ".backups"
    backups: dict[Path, Path] = {}
    promoted: set[Path] = set()
    try:
        for index, (result, output) in enumerate(zip(results, outputs, strict=True)):
            staged = _render_result_output(result)
            backup = _backup_render_output(
                output,
                backup=backups_dir / f"{index}-{output.name}",
                overwrite=overwrite,
            )
            if backup is not None:
                backups[output] = backup
            staged.replace(output)
            promoted.add(output)
    except OSError as exc:
        rollback_errors = _rollback_render_outputs(
            outputs,
            promoted=promoted,
            backups=backups,
        )
        if rollback_errors:
            message = (
                f"{exc}; additionally could not restore {'; '.join(rollback_errors)}"
            )
            raise OSError(message) from exc
        raise


def _render_result_output(result: RenderResult) -> Path:
    if result.output is None:
        message = f"render result for {result.view.value} has no output"
        raise OSError(message)
    return result.output


def _backup_render_output(
    output: Path,
    *,
    backup: Path,
    overwrite: bool,
) -> Path | None:
    if not output.exists():
        return None
    if not overwrite:
        message = f"output already exists: {output}"
        raise FileExistsError(message)
    backup.parent.mkdir(exist_ok=True)
    output.replace(backup)
    return backup


def _rollback_render_outputs(
    outputs: tuple[Path, ...],
    *,
    promoted: set[Path],
    backups: dict[Path, Path],
) -> list[str]:
    errors: list[str] = []
    for output in reversed(outputs):
        try:
            if output in promoted:
                output.unlink(missing_ok=True)
            if (backup := backups.get(output)) is not None and backup.exists():
                backup.replace(output)
        except OSError as exc:
            errors.append(f"{output}: {exc}")
    return errors


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
        line = "" if issue.line_number is None else f":{issue.line_number}"
        print(f"{file}{line}: {issue.severity}: {issue.message}")
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
        line = "" if issue.line_number is None else f":{issue.line_number}"
        print(f"{file}{line}: {issue.severity}: {issue.message}")
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
        case "parts":
            return _dispatch_parts(args)
        case "validate":
            return validate_command(file=args.file, strict=args.strict)
        case "bom":
            return bom_command(
                file=args.file,
                output_format=args.format,
                out=args.output,
            )
        case "inspect":
            return inspect_command(
                file=args.file,
                output_format=args.format,
                gap_threshold=args.gap_threshold,
                chronological=args.chronological,
                page_marker_prefix=args.page_marker_prefix,
                out=args.output,
            )
        case "render":
            return render_command(
                file=args.file,
                views=args.view,
                size=args.size,
                backend=args.backend,
                output_dir=args.output_dir,
                prefix=args.prefix,
                refresh=args.refresh,
                overwrite=args.overwrite,
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


def _dispatch_parts(args: Namespace) -> int:
    """Dispatch one nested parts subcommand."""
    match args.parts_command:
        case "search":
            return parts_search_command(term=args.term, limit=args.limit)
        case "geometry":
            return parts_geometry_command(code=args.code, output_format=args.format)
        case "info":
            return parts_info_command(code=args.code)
        case _:
            msg = f"Unhandled parts subcommand: {args.parts_command!r}"
            raise AssertionError(msg)


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
