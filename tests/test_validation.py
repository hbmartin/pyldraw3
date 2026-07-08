"""Tests for the LDraw file validator."""

from pathlib import Path

import pytest

from ldraw.parts import Parts
from ldraw.validation import (
    KNOWN_META_COMMANDS,
    Severity,
    ValidationIssue,
    iter_ldr_issues,
)

IDENTITY = "1 0 0 0 1 0 0 0 1"
ROTATED_90_Y = "0 0 -1 0 1 0 1 0 0"
SCALED = "2 0 0 0 1 0 0 0 1"
SINGULAR = "1 0 0 0 1 0 0 0 0"


@pytest.fixture
def parts() -> Parts:
    return Parts.get("tests/test_ldraw/ldraw/parts.lst")


def validate(tmp_path: Path, text: str, parts: Parts | None) -> list[ValidationIssue]:
    file = tmp_path / "model.ldr"
    file.write_text(text)
    return list(iter_ldr_issues(file, parts))


def test_clean_file_has_no_issues(tmp_path, parts) -> None:
    text = f"0 Model\n1 4 0 0 0 {IDENTITY} 3001.dat\n"

    assert validate(tmp_path, text, parts) == []


def test_unknown_colour_code_is_an_error(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 999 0 0 0 {IDENTITY} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown colour code 999"),
    ]
    assert issues[0].severity is Severity.ERROR


def test_unknown_colour_checked_on_geometry_lines(tmp_path, parts) -> None:
    issues = validate(tmp_path, "2 999 0 0 0 1 1 1\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown colour code 999"),
    ]


def test_legacy_dithered_colour_is_a_warning(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 256 0 0 0 {IDENTITY} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="legacy dithered colour code 256",
            severity=Severity.WARNING,
        ),
    ]


def test_garbage_colour_token_is_an_error_even_without_library(tmp_path) -> None:
    issues = validate(tmp_path, f"1 abc 0 0 0 {IDENTITY} 3001.dat\n", None)

    assert issues == [
        ValidationIssue(line_number=1, message="invalid colour value"),
    ]


def test_malformed_direct_colour_is_reported_not_crashed(tmp_path) -> None:
    issues = validate(tmp_path, f"1 0x2GGHHII 0 0 0 {IDENTITY} 3001.dat\n", None)

    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR
    assert "Invalid rgb value" in issues[0].message


def test_valid_direct_colour_is_clean(tmp_path, parts) -> None:
    assert validate(tmp_path, f"1 0x2FF0000 0 0 0 {IDENTITY} 3001.dat\n", parts) == []


def test_colour_codes_skipped_without_library(tmp_path) -> None:
    assert validate(tmp_path, "2 999 0 0 0 1 1 1\n", None) == []


def test_colour_codes_skipped_when_ldconfig_missing(tmp_path) -> None:
    ldraw_dir = tmp_path / "lib" / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    bare_parts = Parts(ldraw_dir / "parts.lst")

    text = f"1 999 0 0 0 {IDENTITY} 3001.dat\n"
    assert validate(tmp_path, text, bare_parts) == []


def test_singular_matrix_is_a_warning(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 4 0 0 0 {SINGULAR} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="singular transformation matrix (flattens geometry)",
            severity=Severity.WARNING,
        ),
    ]


def test_scaled_matrix_is_a_warning(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 4 0 0 0 {SCALED} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message=(
                "transformation matrix is not orthonormal (scaled or sheared part)"
            ),
            severity=Severity.WARNING,
        ),
    ]


def test_rotated_matrix_is_clean(tmp_path, parts) -> None:
    assert validate(tmp_path, f"1 4 0 0 0 {ROTATED_90_Y} 3001.dat\n", parts) == []


def test_unknown_bang_meta_is_a_warning(tmp_path, parts) -> None:
    issues = validate(tmp_path, "0 !FOOBAR something\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="unknown meta-command !FOOBAR",
            severity=Severity.WARNING,
        ),
    ]


@pytest.mark.parametrize("meta", sorted(KNOWN_META_COMMANDS))
def test_known_bang_metas_are_clean(tmp_path, meta) -> None:
    assert validate(tmp_path, f"0 !{meta} something\n", None) == []


def test_plain_comments_and_commands_are_never_flagged(tmp_path, parts) -> None:
    text = "0 STEP\n0 BFC CERTIFY CCW\n0 WRITE hello\n0 just some prose\n"

    assert validate(tmp_path, text, parts) == []


def test_blank_lines_are_ignored(tmp_path, parts) -> None:
    text = f"0 Model\n\n1 4 0 0 0 {IDENTITY} 3001.dat\n\n"

    assert validate(tmp_path, text, parts) == []


def test_malformed_line_is_an_error(tmp_path) -> None:
    issues = validate(tmp_path, "9 16 0 0 0\n", None)

    assert issues == [
        ValidationIssue(line_number=1, message="Unknown command (9)"),
    ]


def test_unknown_part_reference_is_an_error(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 4 0 0 0 {IDENTITY} 9999.dat\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown part 9999.dat"),
    ]


def test_own_submodel_references_are_not_unknown_parts(tmp_path, parts) -> None:
    text = (
        "0 FILE main.ldr\n"
        f"1 16 0 0 0 {IDENTITY} BODY.LDR\n"
        "0 NOFILE\n"
        "0 FILE body.ldr\n"
        f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
        "0 NOFILE\n"
    )

    assert validate(tmp_path, text, parts) == []


def test_one_line_can_produce_multiple_issues(tmp_path, parts) -> None:
    issues = validate(tmp_path, f"1 999 0 0 0 {SCALED} 9999.dat\n", parts)

    messages = [issue.message for issue in issues]
    assert messages == [
        "unknown colour code 999",
        "transformation matrix is not orthonormal (scaled or sheared part)",
        "unknown part 9999.dat",
    ]
