"""Tests for tolerant loading of imperfect models and their diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ldraw.analysis import analyze_model
from ldraw.bom import BomRow, bill_of_materials
from ldraw.cli import main
from ldraw.config import Config
from ldraw.diagnostics import DiagnosticCode, Severity
from ldraw.errors import SubmodelCycleError
from ldraw.model import ModelLoadResult, load_model, parse_model_result
from ldraw.model_summary import ModelSummary

TESTS_DIR = Path(__file__).resolve().parent

FIXTURE_CONFIG = Config(
    ldraw_library_path=str(TESTS_DIR / "test_ldraw"),
    generated_path="/gen",
)

IDENTITY = "1 0 0 0 1 0 0 0 1"

CYCLIC_MPD = (
    "0 FILE main.ldr\n"
    f"1 16 0 0 0 {IDENTITY} sub.ldr\n"
    "0 NOFILE\n"
    "0 FILE sub.ldr\n"
    f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
    f"1 16 0 0 0 {IDENTITY} main.ldr\n"
    "0 NOFILE\n"
)

DUPLICATE_SECTION_MPD = (
    "0 FILE main.ldr\n"
    f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
    "0 NOFILE\n"
    "0 FILE main.ldr\n"
    "0 NOFILE\n"
)


def _load_cyclic(tmp_path: Path) -> tuple[Path, ModelLoadResult]:
    path = tmp_path / "cycle.mpd"
    path.write_text(CYCLIC_MPD)
    return path, load_model(path)


def test_cyclic_model_analysis_succeeds_and_surfaces_cycle(tmp_path: Path) -> None:
    _, result = _load_cyclic(tmp_path)

    assert result.model is not None
    assert DiagnosticCode.MPD_CYCLE in {
        diagnostic.code for diagnostic in result.diagnostics
    }

    analysis = result.analyze()

    assert analysis is not None
    assert len(analysis.occurrences) == 1
    assert analysis.occurrences[0].part_code == "3001"
    cycle_diagnostics = [
        diagnostic
        for diagnostic in analysis.diagnostics
        if diagnostic.code is DiagnosticCode.MPD_CYCLE
    ]
    assert len(cycle_diagnostics) == 1
    assert cycle_diagnostics[0].line_number == 6


def test_analyze_model_directly_on_cyclic_model_emits_cycle_diagnostic(
    tmp_path: Path,
) -> None:
    _, result = _load_cyclic(tmp_path)
    assert result.model is not None

    analysis = analyze_model(result.model)

    assert [
        diagnostic.code
        for diagnostic in analysis.diagnostics
        if diagnostic.code is DiagnosticCode.MPD_CYCLE
    ] == [DiagnosticCode.MPD_CYCLE]


def test_cyclic_model_bill_of_materials_and_summary_succeed(tmp_path: Path) -> None:
    _, result = _load_cyclic(tmp_path)
    assert result.model is not None

    method_rows: list[BomRow] = result.model.bill_of_materials()
    function_rows: list[BomRow] = bill_of_materials(result.model)
    assert [(row.part, row.quantity) for row in method_rows] == [("3001", 1)]
    assert function_rows == method_rows

    summary = ModelSummary.from_model(result.model, None)
    assert summary.occurrence_count == 1
    assert summary.part_counts == {"3001": 1}


def test_strict_iter_occurrences_still_raises_on_cycle(tmp_path: Path) -> None:
    _, result = _load_cyclic(tmp_path)
    assert result.model is not None

    with pytest.raises(SubmodelCycleError):
        list(result.model.iter_occurrences())


def test_content_after_nofile_is_warning_and_model_stays_valid() -> None:
    text = (
        "0 FILE main.ldr\n"
        f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
        "0 NOFILE\n"
        "0 leftover after the last section\n"
    )

    result = parse_model_result(text)

    diagnostic = next(
        item
        for item in result.diagnostics
        if item.code is DiagnosticCode.MPD_CONTENT_AFTER_NOFILE
    )
    assert diagnostic.severity is Severity.WARNING
    assert result.valid is True
    assert result.complete is False


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_passes_spec_legal_content_after_nofile(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.mpd"
    model.write_text(
        "0 FILE main.ldr\n"
        f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
        "0 NOFILE\n"
        "0 leftover after the last section\n",
    )

    assert main(["validate", str(model)]) == 0

    assert "0 error(s), 1 warning(s)" in capsys.readouterr().out


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0,
    reason="requires POSIX permissions as a non-root user",
)
@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_formats_file_level_issues_without_line_number(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 Model\n")
    model.chmod(0)
    try:
        assert main(["validate", str(model)]) == 1
    finally:
        model.chmod(0o644)

    out = capsys.readouterr().out
    assert f"{model}: error: could not read model" in out
    assert "None" not in out


def test_strict_mode_reports_the_same_codes_as_tolerant_mode() -> None:
    strict = parse_model_result(DUPLICATE_SECTION_MPD, tolerant=False)
    tolerant = parse_model_result(DUPLICATE_SECTION_MPD, tolerant=True)

    assert strict.model is None
    assert strict.complete is False
    assert [
        (diagnostic.code, diagnostic.line_number) for diagnostic in strict.diagnostics
    ] == [
        (diagnostic.code, diagnostic.line_number) for diagnostic in tolerant.diagnostics
    ]
    assert strict.diagnostics[0].code is DiagnosticCode.MPD_DUPLICATE_SECTION
    assert strict.diagnostics[0].line_number == 4


def test_strict_mode_parse_error_keeps_real_line_numbers() -> None:
    text = f"0 Demo\n2 24 bad 0 0 1 1 1\n1 4 0 0 0 {IDENTITY} 3001.dat\n"

    strict = parse_model_result(text, tolerant=False)
    tolerant = parse_model_result(text, tolerant=True)

    assert strict.model is None
    assert strict.valid is False
    assert [
        (diagnostic.code, diagnostic.line_number) for diagnostic in strict.diagnostics
    ] == [
        (diagnostic.code, diagnostic.line_number) for diagnostic in tolerant.diagnostics
    ]
    assert strict.diagnostics[0].code is DiagnosticCode.PARSE_INVALID_NUMERIC
    assert strict.diagnostics[0].line_number == 2


def test_strict_mode_accepts_clean_text() -> None:
    result = parse_model_result(
        f"0 Demo\n1 4 0 0 0 {IDENTITY} 3001.dat\n",
        tolerant=False,
    )

    assert result.model is not None
    assert result.complete is True
    assert result.diagnostics == ()


def test_load_model_missing_file_reports_io_read_failed(tmp_path: Path) -> None:
    result = load_model(tmp_path / "missing.ldr")

    assert result.model is None
    assert result.complete is False
    assert result.valid is False
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        DiagnosticCode.IO_READ_FAILED,
    ]
    assert result.diagnostics[0].line_number is None


def test_bill_of_materials_requires_exactly_one_source() -> None:
    result = parse_model_result(f"0 Demo\n1 4 0 0 0 {IDENTITY} 3001.dat\n")
    assert result.model is not None

    with pytest.raises(ValueError, match="exactly one"):
        bill_of_materials()
    with pytest.raises(ValueError, match="exactly one"):
        bill_of_materials(result.model, occurrences=())


def test_bill_of_materials_from_occurrences_matches_model_counts() -> None:
    result = parse_model_result(
        f"0 Demo\n1 4 0 0 0 {IDENTITY} 3001.dat\n1 4 0 0 0 {IDENTITY} 3001.dat\n",
    )
    assert result.model is not None
    occurrences = tuple(result.model.iter_occurrences(include_steps=False))

    rows = bill_of_materials(occurrences=occurrences)

    assert rows == result.model.bill_of_materials()
    assert [(row.part, row.quantity) for row in rows] == [("3001", 2)]
