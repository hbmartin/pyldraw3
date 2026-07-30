"""Command-line interface for the pyldraw3 package.

Provides subcommands to download the LDraw parts library, generate the
ldraw.library Python modules, query geometry, validate and inspect LDraw
files, render through LeoCAD, show the configuration, and print the version.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, ArgumentTypeError, Namespace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import BadZipFile

import requests
import yaml

from ldraw import generate as do_generate
from ldraw.bom import BomRow, rows_to_csv, rows_to_json
from ldraw.catalog import catalog_db_path, load_parts
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.downloads import download as do_download
from ldraw.errors import (
    ConfigLoadError,
    CouldNotDetermineLatestVersionError,
    LibraryNotGeneratedError,
    PartError,
)
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.inspection import (
    DEFAULT_PAGE_MARKER_PREFIX,
    ModelInspection,
    OccurrenceContact,
    StudContact,
    inspect_model,
)
from ldraw.model import read_model
from ldraw.rendering import (
    DEFAULT_RENDER_HEIGHT,
    DEFAULT_RENDER_TIMEOUT,
    DEFAULT_RENDER_VIEWS,
    DEFAULT_RENDER_WIDTH,
    LeoCADRenderError,
    RenderView,
    render_leocad,
)
from ldraw.snippets import suggested_import
from ldraw.stubs import write_stub_package
from ldraw.validation import Severity, iter_ldr_issues

if TYPE_CHECKING:
    from ldraw.geometry import Vector
    from ldraw.part_geometry_types import BoundingBox
    from ldraw.parts import CatalogEntry, Parts

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

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect exact world bounds, source attribution, and contact gaps.",
    )
    inspect_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    inspect_parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default: table).",
    )
    inspect_parser.add_argument(
        "--gap-threshold",
        type=float,
        default=5.0,
        help="Report nearest AABB gaps larger than this many LDU (default: 5).",
    )
    inspect_parser.add_argument(
        "--chronological",
        action="store_true",
        help="Exclude neighbours installed on a later attributed page.",
    )
    inspect_parser.add_argument(
        "--page-marker-prefix",
        default=DEFAULT_PAGE_MARKER_PREFIX,
        help=(
            "Comment prefix used to attribute pages "
            f"(default: {DEFAULT_PAGE_MARKER_PREFIX!r})."
        ),
    )
    inspect_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write output to a file instead of stdout.",
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Render deterministic named camera views with LeoCAD.",
    )
    render_parser.add_argument(
        "file",
        type=Path,
        help="Path to the .ldr or .mpd file.",
    )
    render_parser.add_argument(
        "--view",
        action="append",
        type=_parse_render_view,
        default=None,
        metavar="NAME=LAT,LON",
        help="Named camera view; repeat for multiple views.",
    )
    render_parser.add_argument(
        "--size",
        default=f"{DEFAULT_RENDER_WIDTH}x{DEFAULT_RENDER_HEIGHT}",
        metavar="WIDTHxHEIGHT",
        help=(f"Image size (default: {DEFAULT_RENDER_WIDTH}x{DEFAULT_RENDER_HEIGHT})."),
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
        "--leocad",
        default=None,
        help="LeoCAD executable name or path.",
    )
    render_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_RENDER_TIMEOUT,
        help=f"Per-view timeout in seconds (default: {DEFAULT_RENDER_TIMEOUT:g}).",
    )
    render_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Atomically replace existing requested images after all views succeed.",
    )
    render_parser.add_argument(
        "--xvfb",
        choices=("auto", "always", "never"),
        default="auto",
        help="Headless Linux X server policy (default: auto).",
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


def _search_key(text: str) -> str:
    """Casefold and collapse whitespace runs for substring matching.

    Catalog descriptions are column-aligned with double spaces
    (``Arch  1 x  6``), so naturally spaced queries only match after
    normalization.
    """
    return " ".join(text.split()).casefold()


def parts_search_command(*, term: str, limit: int) -> int:
    """Search the parts catalog by description or code substring."""
    if (parts := _load_parts()) is None:
        return 1
    needle = _search_key(term)
    matches = sorted(
        (
            entry
            for entry in parts.catalog.by_code.values()
            if needle in _search_key(entry.description)
            or needle in entry.code.casefold()
        ),
        key=lambda entry: entry.description,
    )
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
    """Show catalog-backed expanded geometry for one part code."""
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
        "description": geometry.description,
        "point_count": len(geometry.points),
        "stud_count": len(geometry.studs),
        "studs": [
            {
                "description": stud.description,
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
    print(f"code: {payload['code']}")
    print(f"description: {payload['description']}")
    print(f"expanded points: {payload['point_count']}")
    print(f"studs: {payload['stud_count']} ({payload['top_stud_count']} top)")
    if geometry.bounds is None:
        print("bounds: none")
    else:
        print(f"bounds min: {_format_vector(geometry.bounds.min)}")
        print(f"bounds max: {_format_vector(geometry.bounds.max)}")
        print(f"size: {_format_vector(geometry.bounds.size)}")
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
    """Inspect model occurrence geometry, attribution, and nearest AABB gaps."""
    if not file.is_file():
        print(f"{file}: not found", file=sys.stderr)
        return 1
    if gap_threshold < 0:
        print("--gap-threshold must be non-negative", file=sys.stderr)
        return 1
    if (parts := _load_parts()) is None:
        return 1
    try:
        model = read_model(file)
        inspection = inspect_model(
            model,
            parts,
            page_marker_prefix=page_marker_prefix,
        )
        contacts = inspection.contact_gaps(
            minimum_gap=gap_threshold,
            chronological=chronological,
        )
    except (PartError, UnicodeDecodeError) as exc:
        print(f"{file}: {exc}", file=sys.stderr)
        return 1

    if output_format == "json":
        text = json.dumps(
            _inspection_data(
                file=file,
                inspection=inspection,
                contacts=contacts,
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
            gap_threshold=gap_threshold,
            chronological=chronological,
        )
    return _write_or_print(text, out=out)


def render_command(  # noqa: PLR0913 - mirrors explicit CLI controls
    *,
    file: Path,
    views: list[RenderView] | None,
    size: str,
    output_dir: Path | None,
    prefix: str | None,
    executable: str | None,
    timeout: float,
    overwrite: bool,
    xvfb: str,
) -> int:
    """Render a transactional named view set through LeoCAD."""
    try:
        width, height = _parse_render_size(size)
        use_xvfb = {"auto": None, "always": True, "never": False}[xvfb]
        results = render_leocad(
            file,
            output_dir=output_dir,
            views=tuple(views) if views is not None else DEFAULT_RENDER_VIEWS,
            prefix=prefix,
            width=width,
            height=height,
            executable=executable,
            overwrite=overwrite,
            timeout=timeout,
            use_xvfb=use_xvfb,
        )
    except (KeyError, LeoCADRenderError, OSError, ValueError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(f"RENDERED: {result.output}")
    return 0


def _inspection_data(
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
    gap_threshold: float,
    chronological: bool,
) -> dict[str, object]:
    return {
        "bounds": _box_data(inspection.bounds),
        "chronological": chronological,
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
                "index": item.index,
                "installation_page": item.attribution.installation_page,
                "local_point_count": len(item.local.points),
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


def _format_inspection_table(
    *,
    file: Path,
    inspection: ModelInspection,
    contacts: tuple[OccurrenceContact, ...],
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
        (
            f"occurrences: {inspection.occurrence_count} "
            f"geometry: {len(inspection.occurrences)} "
            f"skipped: {len(inspection.skipped_geometry)}"
        ),
        f"world bounds: {bounds}",
        f"stud/part contacts: {len(inspection.stud_contacts())}",
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
            f"{' > '.join(attribution.model_path)}",
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
            (f"nearest AABB gaps > {gap_threshold:g} LDU ({mode}): {len(contacts)}"),
        ),
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


def _write_or_print(text: str, *, out: Path | None) -> int:
    rendered = text if text.endswith("\n") else f"{text}\n"
    if out is None:
        print(rendered, end="")
        return 0
    try:
        out.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"Could not write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote inspection to {out}")
    return 0


def _parse_render_view(value: str) -> RenderView:
    name, separator, angles = value.partition("=")
    if not separator:
        msg = f"bad view {value!r}; expected NAME=LAT,LON"
        raise ArgumentTypeError(msg)
    try:
        latitude, longitude = (float(item) for item in angles.split(",", 1))
        return RenderView(name=name, latitude=latitude, longitude=longitude)
    except ValueError as exc:
        msg = f"bad view {value!r}; expected NAME=LAT,LON"
        raise ArgumentTypeError(msg) from exc


def _parse_render_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.casefold().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        msg = f"bad size {value!r}; expected WIDTHxHEIGHT"
        raise ValueError(msg) from exc
    if width <= 0 or height <= 0:
        msg = "render width and height must be positive"
        raise ValueError(msg)
    return width, height


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


def _dispatch(  # noqa: C901, PLR0911, PLR0912 - one branch per subcommand
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
        case "parts" if args.parts_command == "info":
            return parts_info_command(code=args.code)
        case "parts" if args.parts_command == "geometry":
            return parts_geometry_command(
                code=args.code,
                output_format=args.format,
            )
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
                output_dir=args.output_dir,
                prefix=args.prefix,
                executable=args.leocad,
                timeout=args.timeout,
                overwrite=args.overwrite,
                xvfb=args.xvfb,
            )
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
