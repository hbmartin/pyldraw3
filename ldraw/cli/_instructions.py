"""Runtime services for the instructions commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ldraw.cli._bom import _format_bom_table
from ldraw.cli._common import _load_parts
from ldraw.errors import PartError
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
from ldraw.validation import Severity, iter_ldr_issues

if TYPE_CHECKING:
    from argparse import Namespace
    from pathlib import Path

    from ldraw.parts import Parts


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
