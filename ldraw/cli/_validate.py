"""Runtime services for the validate commands."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ldraw.cli._common import _try_load_parts
from ldraw.diagnostics import DiagnosticCode
from ldraw.validation import Severity, iter_ldr_issues

if TYPE_CHECKING:
    from pathlib import Path


def validate_command(
    *,
    file: Path,
    strict: bool = False,
    profile: str = "format",
    matrix_tolerance: float = 1e-6,
    connectivity: bool = False,
) -> int:
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
        issues = list(
            iter_ldr_issues(
                file,
                parts,
                profile=profile,
                matrix_tolerance=matrix_tolerance,
                connectivity=connectivity,
            )
        )
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
