"""Runtime services for extraction and qualified snap reports."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING

from ldraw.cli._common import (
    _invalid_connection_source,
    _load_parts_with_connection_sources,
    _print_diagnostics,
    _write_report,
)
from ldraw.coverage import Coverage
from ldraw.model import load_model

if TYPE_CHECKING:
    from argparse import Namespace
    from pathlib import Path

    from ldraw.inspection import ModelInspection
    from ldraw.inspection_limits import SnapReport


def extract_command(
    *, file: Path, section: str, namespace: str, output: Path, manifest: Path | None
) -> int:
    """Write a dependency closure with retained author and licence records."""
    if manifest is not None and manifest.resolve() == output.resolve():
        message = "Document and manifest must have different output paths"
        raise ValueError(message)
    loaded = load_model(file)
    if loaded.model is None or not loaded.complete:
        _print_diagnostics(loaded.diagnostics, fallback_path=file)
        return 1
    result = loaded.model.extract(section, namespace=namespace)
    try:
        result.model.save(output)
    except OSError as error:
        print(f"Could not write {output}: {error}", file=sys.stderr)
        return 1
    if manifest is not None:
        text = json.dumps([asdict(item) for item in result.manifest], indent=2)
        if not _write_report(text, out=manifest, description="extraction manifest"):
            return 1
    print(f"Extracted {result.model.name} to {output}")
    return 0


def snap_command(args: Namespace) -> int:
    """Search a deterministic pair prefix and qualify its candidate ranking."""
    shadows, studio = tuple(args.ldcad_shadow), tuple(args.studio_metadata)
    if error := _invalid_connection_source(
        connection_shadows=shadows, studio_metadata=studio
    ):
        print(error, file=sys.stderr)
        return 1
    parts = _load_parts_with_connection_sources(
        connection_shadows=shadows, studio_metadata=studio
    )
    if parts is None:
        return 1
    loaded = load_model(args.file, parts=parts)
    if loaded.model is None:
        _print_diagnostics(loaded.diagnostics, fallback_path=args.file)
        return 1
    from ldraw.inspection import inspect_model  # noqa: PLC0415

    inspection = inspect_model(
        loaded.model, parts, occurrence_budget=args.occurrence_budget
    )
    try:
        report = inspection.snap_report(
            moving=args.moving,
            fixed=args.fixed,
            limit=args.limit,
            feature_pair_budget=args.feature_pair_budget,
        )
    except IndexError as error:
        print(error, file=sys.stderr)
        return 1
    data = _snap_data(inspection, report=report)
    text = (
        json.dumps(data, indent=2)
        if args.format == "json"
        else "\n".join(f"{key}: {value}" for key, value in data.items())
    )
    if not _write_report(text, out=args.output, description="snap report"):
        return 1
    complete = all(
        value == Coverage.COMPLETE
        for value in (
            report.coverage,
            inspection.geometry_coverage,
            inspection.connection_coverage,
        )
    )
    return 1 if args.strict and not complete else 0


def _snap_data(inspection: ModelInspection, *, report: SnapReport) -> dict[str, object]:
    from ldraw.cli._inspect import _residual_data, _vector_data  # noqa: PLC0415

    return {
        "coverage": report.coverage.value,
        "geometry_coverage": inspection.geometry_coverage.value,
        "connection_coverage": inspection.connection_coverage.value,
        "examined_pairs": report.examined_pairs,
        "total_pairs": report.total_pairs,
        "unsupported_checks": list(report.unsupported_checks),
        "diagnostics": [item.to_dict() for item in report.diagnostics],
        "candidates": [
            {
                "moving_occurrence": item.moving_occurrence.index,
                "fixed_occurrence": item.fixed_occurrence.index,
                "moving_feature": item.moving.feature_id,
                "fixed_feature": item.fixed.feature_id,
                "position": _vector_data(item.transform.position),
                "matrix": item.transform.matrix.flatten(),
                "residual": _residual_data(item.residual),
                "contact_supported": item.contact_supported,
            }
            for item in report.candidates
        ],
    }
