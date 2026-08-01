"""Behavioral coverage for report-oriented inspection and analysis APIs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ldraw.analysis import analyze_model
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.errors import NoGeometryError
from ldraw.geometry import Identity, Vector
from ldraw.inspection import (
    ModelInspection,
    bounds_gap,
    inspect_model,
    occurrence_bounds,
    transformed_bounds,
)
from ldraw.model import Model, ModelLoadResult, parse_model_result
from ldraw.operations import CancellationToken
from ldraw.part_geometry_types import BoundingBox
from ldraw.parts import Parts

if TYPE_CHECKING:
    from pathlib import Path

_IDENTITY = "1 0 0 0 1 0 0 0 1"


def _inspection_parts(tmp_path: Path) -> Parts:
    ldraw_path = tmp_path / "ldraw"
    files = {
        "p/stud.dat": "0 Stud\n2 24 -1 -1 -1 1 0 1\n",
        "p/stud4.dat": "0 Stud Tube Open\n2 24 -1 -1 -1 1 0 1\n",
        "p/studp.dat": "0 Stud Placeholder\n2 24 -1 -1 -1 1 0 1\n",
        "p/studz.dat": "0 Stud Zero Up\n2 24 -1 -1 -1 1 0 1\n",
        "parts/9001.dat": (
            "0 Test Studded Part\n"
            "0 Name: 9001.dat\n"
            "0 !LDRAW_ORG Part 2026-01\n"
            "2 24 -10 -8 -10 10 0 10\n"
            f"1 16 0 0 0 {_IDENTITY} stud.dat\n"
            f"1 16 2 0 0 {_IDENTITY} stud4.dat\n"
            f"1 16 4 0 0 {_IDENTITY} studp.dat\n"
            "1 16 6 0 0 1 0 0 0 0 0 0 0 1 studz.dat\n"
        ),
        "parts/9002.dat": "0 Test Support\n2 24 -5 -1 -5 5 1 5\n",
        "parts/9003.dat": "0 Empty Part\n0 Name: 9003.dat\n",
        "parts/9004.dat": b"\xff\xfe invalid header",
        "parts/9006.dat": (
            f"0 Hollow Part\n0 Name: 9006.dat\n1 16 0 0 0 {_IDENTITY} missing.dat\n"
        ),
    }
    for name, content in files.items():
        target = ldraw_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    (ldraw_path / "parts.lst").write_text(
        "9001.dat                       Test Studded Part\n"
        "9002.dat                       Test Support\n"
        "9003.dat                       Empty Part\n"
        "9004.dat                       Invalid Part\n"
        "9006.dat                       Hollow Part\n",
        encoding="utf-8",
    )
    (ldraw_path / "p.lst").write_text(
        "stud.dat                       Stud\n"
        "stud4.dat                      Stud Tube Open\n"
        "studp.dat                      Stud Placeholder\n"
        "studz.dat                      Stud Zero Up\n",
        encoding="utf-8",
    )
    return Parts(ldraw_path / "parts.lst")


def _inspection_model() -> Model:
    text = (
        "0 // PDF_PAGE not-a-number\n"
        "0 // PDF_PAGE -1\n"
        "0 // PDF_PAGE 1\n"
        f"1 4 0 0 0 {_IDENTITY} 9001.dat\n"
        f"1 4 0 0 0 {_IDENTITY} 9002.dat\n"
        "0 // PDF_PAGE 2\n"
        f"1 4 100 0 0 {_IDENTITY} 9002.dat\n"
        f"1 4 0 0 0 {_IDENTITY} 9003.dat\n"
    )
    result = parse_model_result(text, name="inspection.ldr")
    assert result.model is not None
    return result.model


def test_model_inspection_reports_geometry_contacts_and_provenance(
    tmp_path: Path,
) -> None:
    parts = _inspection_parts(tmp_path)
    model = _inspection_model()

    inspection = inspect_model(model, parts)

    assert inspection.occurrence_count == 4
    assert len(inspection.occurrences) == 3
    assert len(inspection.skipped_geometry) == 1
    assert inspection.complete is False
    assert inspection.bounds == BoundingBox(Vector(-10, -8, -10), Vector(105, 1, 10))
    first = inspection.occurrences[0]
    assert first.index == 0
    assert first.occurrence is first.attribution.occurrence
    assert first.attribution.step_path == first.attribution.local_step_path
    assert first.attribution.installation_page == 1
    assert first.attribution.source_page == 1
    assert inspection.skipped_geometry[0].reason.casefold().startswith("part 9003")

    geometry = first.local
    assert geometry.complete is True
    assert [stud.name for stud in geometry.top_studs] == ["stud"]
    assert [stud.name for stud in geometry.receptacles] == ["stud4"]
    assert any(stud.is_placeholder for stud in geometry.studs)
    assert any(abs(stud.up) == 0 for stud in geometry.studs)

    contacts = inspection.stud_contacts()
    assert len(contacts) == 1
    assert contacts[0].stud_occurrence.index == 0
    assert contacts[0].supported_occurrence.index == 1
    assert contacts[0].position == Vector(0, 0, 0)

    gaps = inspection.contact_gaps(minimum_gap=5)
    assert [contact.subject.index for contact in gaps] == [2]
    assert gaps[0].gap.distance == 85
    assert inspection.contact_gaps(minimum_gap=5, chronological=True) == gaps
    assert (
        ModelInspection(
            bounds=first.bounds,
            occurrences=(first,),
            skipped_geometry=(),
            diagnostics=(),
            occurrence_count=1,
        ).contact_gaps()
        == ()
    )

    with pytest.raises(ValueError, match="tolerance"):
        inspection.stud_contacts(tolerance=-1)
    with pytest.raises(ValueError, match="probe_distance"):
        inspection.stud_contacts(probe_distance=0)
    with pytest.raises(ValueError, match="minimum_gap"):
        inspection.contact_gaps(minimum_gap=-1)


def test_exact_bounds_helpers_and_empty_inspection(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    model = _inspection_model()
    occurrences = tuple(model.iter_occurrences())

    first_bounds = occurrence_bounds(occurrences[0], parts)
    assert first_bounds.min == Vector(-10, -8, -10)
    assert (
        transformed_bounds(
            (),
            position=Vector(0, 0, 0),
            matrix=Identity(),
        )
        is None
    )
    with pytest.raises(NoGeometryError, match="9003"):
        occurrence_bounds(occurrences[-1], parts)

    touching = bounds_gap(
        BoundingBox(Vector(0, 0, 0), Vector(1, 1, 1)),
        BoundingBox(Vector(1, -1, 0), Vector(2, 0, 1)),
    )
    separated = bounds_gap(
        BoundingBox(Vector(0, 0, 0), Vector(1, 1, 1)),
        BoundingBox(Vector(4, 5, 1), Vector(5, 6, 2)),
    )
    assert touching.intersects is True
    assert separated.axes == Vector(3, 4, 0)
    assert separated.distance == 5

    empty = inspect_model(Model(), parts, page_marker_prefix="")
    assert empty.complete is True
    assert empty.bounds is None
    assert empty.occurrences == ()


def test_analysis_reuses_occurrences_and_preserves_diagnostics(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    model = _inspection_model()
    incoming = Diagnostic(
        line_number=7,
        message="input warning",
        severity=Severity.WARNING,
    )

    analysis = analyze_model(model, parts=parts, diagnostics=(incoming,))

    assert analysis.summary.occurrence_count == 4
    assert sum(row.quantity for row in analysis.bom) == 4
    assert analysis.inspection is not None
    assert analysis.diagnostics[0] is incoming
    assert any(
        diagnostic.code is DiagnosticCode.GEOMETRY_INCOMPLETE
        for diagnostic in analysis.diagnostics
    )
    assert analyze_model(Model()).inspection is None

    load_result = ModelLoadResult(model, (incoming,), complete=True)
    assert load_result.analyze(parts) is not None
    assert ModelLoadResult(None, (), complete=False).analyze() is None


def test_analysis_emits_each_geometry_diagnostic_once(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    model = _inspection_model()

    analysis = analyze_model(model, parts=parts)

    incomplete = [
        diagnostic
        for diagnostic in analysis.diagnostics
        if diagnostic.code is DiagnosticCode.GEOMETRY_INCOMPLETE
    ]
    # Exactly one diagnostic for the single skipped 9003 placement — not
    # one from the summary plus an identical one from the inspection.
    assert len(incomplete) == 1
    assert incomplete[0].offending_value == "9003"


def test_repeated_part_reports_unresolved_reference_once(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    text = f"1 4 0 0 0 {_IDENTITY} 9006.dat\n1 4 40 0 0 {_IDENTITY} 9006.dat\n"
    result = parse_model_result(text, name="hollow.ldr")
    assert result.model is not None

    inspection = inspect_model(result.model, parts)

    unresolved = [
        diagnostic
        for diagnostic in inspection.diagnostics
        if diagnostic.code is DiagnosticCode.PART_REFERENCE_UNRESOLVED
    ]
    incomplete = [
        diagnostic
        for diagnostic in inspection.diagnostics
        if diagnostic.code is DiagnosticCode.GEOMETRY_INCOMPLETE
    ]
    # The part's cached unresolved-subfile cause is surfaced once per
    # part, while each skipped placement keeps its own skip diagnostic.
    assert len(unresolved) == 1
    assert len(incomplete) == 2
    assert len(inspection.skipped_geometry) == 2


def test_skipped_occurrences_surface_root_cause_diagnostics(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    result = parse_model_result(
        f"1 4 0 0 0 {_IDENTITY} 9006.dat\n",
        name="hollow.ldr",
    )
    assert result.model is not None

    inspection = inspect_model(result.model, parts)

    assert len(inspection.skipped_geometry) == 1
    codes = [diagnostic.code for diagnostic in inspection.diagnostics]
    assert DiagnosticCode.PART_REFERENCE_UNRESOLVED in codes
    assert DiagnosticCode.GEOMETRY_INCOMPLETE in codes


def test_analysis_computes_exact_geometry_once_per_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = _inspection_parts(tmp_path)
    model = _inspection_model()
    calls: list[str] = []
    original_geometry = Parts.geometry

    def counting_geometry(self: Parts, code: str) -> object:
        calls.append(code)
        return original_geometry(self, code)

    monkeypatch.setattr(Parts, "geometry", counting_geometry)

    analysis = analyze_model(model, parts=parts)

    assert analysis.summary.occurrence_count == 4
    assert analysis.inspection is not None
    # One geometry expansion per occurrence: the summary reuses the
    # bounds the inspection already computed.
    assert len(calls) == 4


def test_diagnostics_and_part_inspection_are_machine_readable(tmp_path: Path) -> None:
    parts = _inspection_parts(tmp_path)
    cause = ValueError("bad value")
    diagnostic = Diagnostic(
        line_number=3,
        message="broken",
        severity=Severity.WARNING,
        code=DiagnosticCode.PART_HEADER_INVALID,
        path=tmp_path / "part.dat",
        section="sub.ldr",
        offending_value="bad",
        suggestions=("good",),
        cause=cause,
    )

    serialized = diagnostic.to_dict()
    assert serialized["code"] == "part.header_invalid"
    assert serialized["severity"] == "warning"
    assert serialized["cause"] == {"type": "ValueError", "message": "bad value"}

    binary = Diagnostic(message="undecodable", offending_value=b"\xff\xfe")
    encoded = binary.to_dict()
    assert encoded["offending_value"] == repr(b"\xff\xfe")
    assert json.loads(json.dumps(encoded))["message"] == "undecodable"

    complete = parts.inspect_part("9001", include_geometry=False)
    assert complete.complete is True
    assert complete.geometry is None
    assert (
        parts.inspect_part("missing").diagnostics[0].code
        is DiagnosticCode.PART_NOT_FOUND
    )

    invalid = parts.inspect_part("9004")
    assert invalid.complete is False
    assert invalid.metadata is None
    assert {item.code for item in invalid.diagnostics} >= {
        DiagnosticCode.PART_HEADER_INVALID,
        DiagnosticCode.PART_REFERENCE_UNRESOLVED,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(float("nan"), "nan"), (float("inf"), "inf"), (float("-inf"), "-inf")],
)
def test_diagnostic_serializes_non_finite_floats_as_strings(
    value: float,
    expected: str,
) -> None:
    encoded = Diagnostic(message="non-finite", offending_value=value).to_dict()

    assert encoded["offending_value"] == expected
    strict_json = json.dumps(encoded, allow_nan=False)
    assert json.loads(strict_json)["offending_value"] == expected


def test_cancellation_token_is_idempotent_and_observable() -> None:
    token = CancellationToken()

    assert token.cancelled is False
    token.cancel()
    token.cancel()
    assert token.cancelled is True
