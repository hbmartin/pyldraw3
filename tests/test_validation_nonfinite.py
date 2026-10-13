"""Retained non-finite geometry is invalid rather than an exception."""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from ldraw.bom import compare_inventory
from ldraw.cli import main
from ldraw.connection_types import (
    ConnectionFeature,
    ConnectionKind,
    ConnectionRole,
    GenericProfile,
)
from ldraw.diagnostics import Diagnostic, DiagnosticCode, Severity
from ldraw.geometry import Matrix, Vector, Vector2D
from ldraw.model import Model, ModelOccurrence, load_model, parse_model_result
from ldraw.part import parse_ldraw_line
from ldraw.part_geometry_types import BoundingBox
from ldraw.pieces import Group, Piece
from ldraw.validation import iter_duplicate_issues, iter_object_issues

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


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
def test_non_finite_objects_are_inspectable(
    token: str, caplog: pytest.LogCaptureFixture
) -> None:
    value = float(token)
    vector = Vector(value, 0, 0)
    matrix = Matrix([[value, 0, 0], [0, 1, 0], [0, 0, 1]])
    piece = Piece.place("3001", position=vector, matrix=matrix)
    occurrence = next(Model(objects=[Piece.place("3001")]).iter_occurrences())
    feature = ConnectionFeature(
        kind=ConnectionKind.GENERIC,
        role=ConnectionRole.NEUTRAL,
        position=vector,
        frame=matrix,
        profile=GenericProfile(name="Test"),
    )
    objects = (
        vector,
        matrix,
        Vector2D(value, 0),
        piece,
        replace(occurrence, position=vector, matrix=matrix),
        feature,
        BoundingBox(min=vector, max=vector),
        parse_ldraw_line(f"2 24 {token} 0 0 1 1 1"),
    )
    assert token in vector.repr
    for obj in objects:
        assert token in repr(obj)
        diagnostic = Diagnostic(offending_value=obj)
        json.dumps(diagnostic.to_dict(), allow_nan=False)
    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("Inspecting %r", piece)
    assert token in caplog.text
    with pytest.raises(ValueError, match="Cannot serialize non-finite"):
        piece.to_ldraw()


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
@pytest.mark.parametrize(("line", "field"), NON_FINITE_LINES)
def test_public_comparison_rejects_all_non_finite_source_geometry(
    token: str, line: str, field: str
) -> None:
    result = parse_model_result(f"0 FILE main.ldr\n{line.format(token=token)}\n")
    assert result.model is not None
    with pytest.raises(ValueError, match=r"model\.non_finite_numeric") as raised:
        compare_inventory(result.model, [])
    assert "main.ldr:2" in str(raised.value)
    assert f"{field}={token}" in str(raised.value)


@pytest.mark.parametrize("referenced", [False, True])
def test_public_comparison_checks_programmatic_and_nested_geometry(
    *, referenced: bool
) -> None:
    child = Model(name="child.ldr", objects=[parse_ldraw_line("2 24 nan 0 0 1 1 1")])
    middle = Model(name="middle.ldr", submodels={"child.ldr": child})
    if referenced:
        middle.add_submodel(child)
    root = Model(name="main.ldr", submodels={"middle.ldr": middle, "alias": middle})
    if referenced:
        root.add_submodel(middle)
    with pytest.raises(ValueError, match=r"child.ldr: non-finite.*point1.x=nan"):
        compare_inventory(root, [])


@dataclass
class _OccurrenceProvider:
    occurrences: tuple[ModelOccurrence, ...]

    def iter_occurrences(
        self, *, expand_submodels: bool = True, include_steps: bool = True
    ) -> Iterator[ModelOccurrence]:
        del expand_submodels, include_steps
        return iter(self.occurrences)


@pytest.mark.parametrize("field", ["position", "matrix"])
def test_comparison_checks_occurrence_only_providers(field: str) -> None:
    occurrence = next(Model(objects=[Piece.place("3001")]).iter_occurrences())
    value = (
        Vector(float("inf"), 0, 0)
        if field == "position"
        else Matrix([[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]])
    )
    provider = _OccurrenceProvider((replace(occurrence, **{field: value}),))
    with pytest.raises(ValueError, match=rf"non-finite numeric fields: {field}"):
        compare_inventory(provider, [])


def test_comparison_rejects_overflow_from_finite_submodel_transforms() -> None:
    child = Model(
        name="child.ldr", objects=[Piece.place("3001", position=Vector(1e308, 0, 0))]
    )
    root = Model(name="main.ldr")
    root.add_submodel(child, matrix=Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]))
    with (
        np.errstate(over="ignore", invalid="ignore"),
        pytest.raises(ValueError, match=r"position\.x=inf"),
    ):
        compare_inventory(root, [])


def test_comparison_rejects_non_finite_group_transform() -> None:
    group = Group(matrix=Matrix([[2, 0, 0], [0, 1, 0], [0, 0, 1]]))
    piece = Piece.place("3001", position=Vector(1e308, 0, 0), group=group)
    with (
        np.errstate(over="ignore", invalid="ignore"),
        pytest.raises(ValueError, match=r"position\.x=inf"),
    ):
        compare_inventory(Model(objects=[piece]), [])


def test_expanded_matrix_overflow_is_rejected_by_api_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "0 FILE main.ldr\n"
        "1 4 0 0 0 1e308 0 0 0 1 0 0 0 1 child.ldr\n"
        "0 FILE child.ldr\n"
        "1 16 0 0 0 2 0 0 0 1 0 0 0 1 3001.dat\n"
    )
    model = parse_model_result(text).model
    assert model is not None
    path = tmp_path / "overflow.mpd"
    path.write_text(text)
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("part,colour_code,quantity\n3001,4,1\n")
    output = tmp_path / "comparison.json"
    output.write_text("existing output")
    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match=r"matrix\[0\]\[0\]=inf"):
            compare_inventory(model, [])
        assert (
            main(["bom", str(path), "--compare", str(inventory), "-o", str(output)])
            == 2
        )
    assert "matrix[0][0]=inf" in capsys.readouterr().err
    assert output.read_text() == "existing output"


@pytest.mark.parametrize(
    ("matrix", "code"),
    [
        ("0 0 0 0 0 0 0 0 0", DiagnosticCode.MODEL_SINGULAR_MATRIX),
        ("2 0 0 0 1 0 0 0 1", DiagnosticCode.MODEL_NON_ORTHONORMAL_MATRIX),
    ],
)
def test_bad_position_does_not_hide_finite_matrix_warnings(
    matrix: str, code: DiagnosticCode
) -> None:
    result = parse_model_result(f"1 4 nan 0 0 {matrix} 3001.dat\n")
    assert [issue.code for issue in result.diagnostics] == [
        DiagnosticCode.MODEL_NON_FINITE_NUMERIC,
        code,
    ]
    assert result.model is not None
    piece = result.model.pieces[0]
    assert [
        issue.code
        for issue in iter_object_issues(piece, number=1, parts=None, submodels=set())
    ] == [DiagnosticCode.MODEL_NON_FINITE_NUMERIC, code]


def test_validation_reuses_transforms_without_persistent_numeric_cache() -> None:
    original = Piece._transformed  # noqa: SLF001 - count effective transform work
    with patch.object(
        Piece, "_transformed", autospec=True, side_effect=original
    ) as transformed:
        result = parse_model_result(
            f"1 4 0 0 0 {IDENTITY} 3001.dat\n1 4 0 0 0 {IDENTITY} 3001.dat\n"
        )
    assert transformed.call_count == 2
    assert result.model is not None
    assert len(list(iter_duplicate_issues(result.model))) == 1
    result.model.pieces[1].position.x = float("nan")
    assert list(iter_duplicate_issues(result.model)) == []


@pytest.mark.parametrize("varying", [False, True])
def test_duplicate_equivalence_survives_cache_sampling(*, varying: bool) -> None:
    rotation = Matrix.rotation(x=17, y=31, z=23)
    model = Model(
        objects=[
            Piece.place(
                "3001",
                position=Vector(index + 0.1234567, 0.1234567, 0.1234567),
                matrix=Matrix.rotation(
                    x=index * 0.037 + 0.113,
                    y=index * 0.029 + 0.131,
                    z=index * 0.019 + 0.173,
                )
                if varying
                else rotation,
            )
            for index in range(150)
        ]
    )
    model.objects.insert(0, Piece.place("3001", position=Vector(float("nan"), 0, 0)))
    model.objects.append(model.objects[1])
    assert len(list(iter_duplicate_issues(model))) == 1
