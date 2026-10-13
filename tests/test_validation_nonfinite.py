"""Retained non-finite geometry is invalid rather than an exception."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.cli import main
from ldraw.diagnostics import DiagnosticCode, Severity
from ldraw.model import load_model, parse_model_result
from ldraw.validation import iter_duplicate_issues

IDENTITY = "1 0 0 0 1 0 0 0 1"
NON_FINITE_LINES = (
    (f"1 4 {{token}} 0 0 {IDENTITY} 3001.dat", "position.x"),
    ("1 4 0 0 0 1 0 0 0 {token} 0 0 0 1 3001.dat", "matrix[1][1]"),
    ("2 24 0 0 0 1 {token} 1", "point2.y"),
    ("3 4 0 0 0 1 1 1 2 2 {token}", "point3.z"),
    ("4 4 0 0 0 1 1 1 2 2 2 {token} 3 3", "point4.x"),
    ("5 24 0 0 0 1 1 1 2 {token} 2 3 3 3", "point3.y"),
)


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
@pytest.mark.parametrize(("line", "field"), NON_FINITE_LINES)
@pytest.mark.parametrize("tolerant", [False, True])
def test_non_finite_geometry_is_retained_with_source_diagnostics(
    tmp_path: Path, token: str, line: str, field: str, *, tolerant: bool
) -> None:
    path = tmp_path / "invalid.mpd"
    path.write_text(
        f"0 FILE main.ldr\n{line.format(token=token)}\n"
        f"1 4 20 0 0 {IDENTITY} 3001.dat\n0 NOFILE\n"
    )

    result = load_model(path, tolerant=tolerant)

    assert result.complete
    assert not result.valid
    assert result.model is not None
    assert len(result.model.objects) == 2
    assert len(result.diagnostics) == 1
    issue = result.diagnostics[0]
    assert issue.code is DiagnosticCode.MODEL_NON_FINITE_NUMERIC
    assert issue.severity is Severity.ERROR
    assert issue.path == path
    assert issue.section == "main.ldr"
    assert issue.line_number == 2
    assert f"{field}={token}" in issue.message
    json.dumps(issue.to_dict(), allow_nan=False)
    assert list(iter_duplicate_issues(result.model)) == []
    with pytest.raises(ValueError, match="Cannot serialize non-finite LDraw number"):
        result.model.to_ldraw()


def test_one_numeric_error_per_object_names_all_invalid_fields() -> None:
    line = "1 4 nan inf 0 1 0 0 0 -inf 0 0 0 1 3001.dat\n"
    result = parse_model_result(f"{line}{line}")
    assert len(result.diagnostics) == 2
    for issue in result.diagnostics:
        assert issue.code is DiagnosticCode.MODEL_NON_FINITE_NUMERIC
        assert "position.x=nan" in issue.message
        assert "position.y=inf" in issue.message
        assert "matrix[1][1]=-inf" in issue.message


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
def test_non_finite_cli_reports_errors_without_output_or_tracebacks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], token: str
) -> None:
    path = tmp_path / "invalid.ldr"
    path.write_text(f"1 4 {token} 0 0 {IDENTITY} 3001.dat\n")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n")
    output_path = tmp_path / "comparison.json"
    output_path.write_text("existing output")
    with patch("ldraw.cli._validate._try_load_parts", return_value=None):
        assert main(["validate", str(path)]) == 1
    output = capsys.readouterr()
    assert f"{path}:1: error: non-finite numeric fields" in output.out
    assert "Traceback" not in output.err

    assert (
        main(["bom", str(path), "--compare", str(inventory), "-o", str(output_path)])
        == 2
    )
    output = capsys.readouterr()
    assert not output.out
    assert "non-finite numeric fields" in output.err
    assert "Traceback" not in output.err
    assert output_path.read_text() == "existing output"
