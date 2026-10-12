"""Command-line entry point with deferred command services."""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from importlib import import_module
from typing import TYPE_CHECKING, Any

from ldraw.errors import ConfigLoadError

if TYPE_CHECKING:
    from argparse import Namespace
_COMMANDS = (
    "download",
    "generate",
    "parts",
    "validate",
    "bom",
    "inspect",
    "render",
    "stubs",
    "instructions",
    "config",
    "version",
)
# Fixed historical import manifest: new implementation names need no entries.
# Import aliases do not forward assignments; patch the consuming handler module.
_LEGACY = {
    "_confirm": "ldraw.cli._common",
    "_parts_lst_path": "ldraw.cli._common",
    "_try_load_parts": "ldraw.cli._common",
    "_load_parts": "ldraw.cli._common",
    "_invalid_connection_source": "ldraw.cli._common",
    "_load_parts_with_connection_sources": "ldraw.cli._common",
    "_report_connection_source_error": "ldraw.cli._common",
    "_print_diagnostics": "ldraw.cli._common",
    "_write_report": "ldraw.cli._common",
    "_diagnostic_text": "ldraw.cli._common",
    "_print_report_diagnostics": "ldraw.cli._common",
    "download_command": "ldraw.cli._download",
    "generate_command": "ldraw.cli._generate",
    "_suggested_import": "ldraw.cli._parts",
    "parts_search_command": "ldraw.cli._parts",
    "parts_info_command": "ldraw.cli._parts",
    "parts_geometry_command": "ldraw.cli._parts",
    "_dispatch_parts": "ldraw.cli._parts",
    "inspect_command": "ldraw.cli._inspect",
    "_inspection_data": "ldraw.cli._inspect",
    "_format_inspection_table": "ldraw.cli._inspect",
    "_page": "ldraw.cli._inspect",
    "_stud_contact_data": "ldraw.cli._inspect",
    "_connection_contact_data": "ldraw.cli._inspect",
    "_connection_data": "ldraw.cli._inspect",
    "_connection_profile_data": "ldraw.cli._inspect",
    "_connection_metadata_data": "ldraw.cli._inspect",
    "_residual_data": "ldraw.cli._inspect",
    "_graph_edge_data": "ldraw.cli._inspect",
    "_box_data": "ldraw.cli._inspect",
    "_vector_data": "ldraw.cli._inspect",
    "_format_vector": "ldraw.cli._inspect",
    "_RenderPlan": "ldraw.cli._render",
    "render_command": "ldraw.cli._render",
    "_parse_render_size": "ldraw.cli._render",
    "_build_render_plan": "ldraw.cli._render",
    "_execute_render_plan": "ldraw.cli._render",
    "_report_render_results": "ldraw.cli._render",
    "_promote_render_outputs": "ldraw.cli._render",
    "_render_result_output": "ldraw.cli._render",
    "_backup_render_output": "ldraw.cli._render",
    "_rollback_render_outputs": "ldraw.cli._render",
    "validate_command": "ldraw.cli._validate",
    "_format_bom_table": "ldraw.cli._bom",
    "_format_bom": "ldraw.cli._bom",
    "bom_command": "ldraw.cli._bom",
    "_read_inventory_mapping": "ldraw.cli._bom",
    "_compare_inventory_command": "ldraw.cli._bom",
    "stubs_command": "ldraw.cli._stubs",
    "_instruction_document": "ldraw.cli._instructions",
    "_rotation_label": "ldraw.cli._instructions",
    "instructions_inspect_command": "ldraw.cli._instructions",
    "_print_instruction_issue": "ldraw.cli._instructions",
    "instructions_validate_command": "ldraw.cli._instructions",
    "instructions_export_command": "ldraw.cli._instructions",
    "instructions_snapshots_command": "ldraw.cli._instructions",
    "_dispatch_instructions": "ldraw.cli._instructions",
    "config_command": "ldraw.cli._config",
    "version_command": "ldraw.cli._version",
    "ArgumentParser": "argparse",
    "Namespace": "argparse",
    "dataclass": "dataclasses",
    "PackageNotFoundError": "importlib.metadata",
    "package_version": "importlib.metadata",
    "Path": "pathlib",
    "TemporaryDirectory": "tempfile",
    "BadZipFile": "zipfile",
    "is_zipfile": "zipfile",
    "do_generate": "ldraw",
    "BomRow": "ldraw.bom",
    "compare_inventory": "ldraw.bom",
    "comparison_to_csv": "ldraw.bom",
    "read_inventory": "ldraw.bom",
    "rows_to_csv": "ldraw.bom",
    "rows_to_json": "ldraw.bom",
    "catalog_db_path": "ldraw.catalog",
    "load_parts": "ldraw.catalog",
    "Config": "ldraw.config",
    "ConnectionMetadataReport": "ldraw.connection_metadata",
    "AnnularProfile": "ldraw.connection_types",
    "ConnectionFeature": "ldraw.connection_types",
    "CylindricalProfile": "ldraw.connection_types",
    "FingerProfile": "ldraw.connection_types",
    "GenericProfile": "ldraw.connection_types",
    "Diagnostic": "ldraw.diagnostics",
    "DiagnosticCode": "ldraw.diagnostics",
    "COMPLETE_VERSION": "ldraw.cli._defaults",
    "cache_ldraw": "ldraw.downloads",
    "do_download": "ldraw.downloads",
    "ConfigLoadError": "ldraw.errors",
    "CouldNotDetermineLatestVersionError": "ldraw.errors",
    "LibraryNotGeneratedError": "ldraw.errors",
    "PartError": "ldraw.errors",
    "UnwritableOutputError": "ldraw.generation.exceptions",
    "Vector": "ldraw.geometry",
    "DEFAULT_PAGE_MARKER_PREFIX": "ldraw.cli._defaults",
    "ConnectionContact": "ldraw.inspection",
    "ModelInspection": "ldraw.inspection",
    "OccurrenceContact": "ldraw.inspection",
    "StudContact": "ldraw.inspection",
    "inspect_model": "ldraw.inspection",
    "instruction_manifest": "ldraw.instruction_artifacts",
    "manifest_json": "ldraw.instruction_artifacts",
    "write_instruction_manifest": "ldraw.instruction_artifacts",
    "write_instruction_snapshots": "ldraw.instruction_artifacts",
    "CameraState": "ldraw.instructions",
    "InstructionDocument": "ldraw.instructions",
    "InstructionIssue": "ldraw.instructions",
    "InstructionStep": "ldraw.instructions",
    "iter_instruction_issues": "ldraw.instructions",
    "load_model": "ldraw.model",
    "read_model": "ldraw.model",
    "BoundingBox": "ldraw.part_geometry_types",
    "CatalogEntry": "ldraw.parts",
    "Parts": "ldraw.parts",
    "RenderBackend": "ldraw.rendering",
    "RenderResult": "ldraw.rendering",
    "RenderView": "ldraw.rendering",
    "render_preview": "ldraw.rendering",
    "suggested_import": "ldraw.snippets",
    "write_stub_package": "ldraw.stubs",
    "Severity": "ldraw.validation",
    "iter_ldr_issues": "ldraw.validation",
    "DEFAULT_SEARCH_LIMIT": "ldraw.cli._defaults",
    "DEFAULT_RENDER_SIZE": "ldraw.cli._defaults",
    "DEFAULT_RENDER_VIEWS": "ldraw.cli._defaults",
    "PACKAGE_NAME": "ldraw.cli._defaults",
    "_SAFE_RENDER_PREFIX": "ldraw.cli._defaults",
}
_ALIASES = {
    "package_version": "version",
    "do_generate": "generate",
    "do_download": "download",
}


def build_parser() -> ArgumentParser:
    """Build the argument parser for the ldraw CLI."""
    parser = ArgumentParser(
        prog="ldraw",
        description=(
            "Manage LDraw libraries and create, inspect, validate, "
            "and render LDraw models."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    for name in _COMMANDS:
        import_module(f"ldraw.cli.{name}").register(subparsers)
    return parser


def _dispatch(args: Namespace, parser: ArgumentParser) -> int:
    """Dispatch parsed arguments to the matching subcommand."""
    if args.command in _COMMANDS:
        return import_module(f"ldraw.cli.{args.command}").run(args)
    parser.print_help()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    try:
        return _dispatch(parser.parse_args(argv), parser)
    except ConfigLoadError as exc:
        print(exc, file=sys.stderr)
        return 1


def __getattr__(name: str) -> Any:  # noqa: ANN401 - legacy dynamic imports
    """Preserve historical handler imports with deferred loading."""
    if name not in _LEGACY:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(import_module(_LEGACY[name]), _ALIASES.get(name, name))
