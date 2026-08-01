"""Tests for the LDraw file validator."""

from pathlib import Path

import pytest

from ldraw.diagnostics import DiagnosticCode
from ldraw.parts import Parts
from ldraw.validation import (
    KNOWN_META_COMMANDS,
    Severity,
    ValidationIssue,
    iter_ldr_issues,
)

TESTS_DIR = Path(__file__).resolve().parent

IDENTITY = "1 0 0 0 1 0 0 0 1"
ROTATED_90_Y = "0 0 -1 0 1 0 1 0 0"
SCALED = "2 0 0 0 1 0 0 0 1"
SINGULAR = "1 0 0 0 1 0 0 0 0"


@pytest.fixture
def parts() -> Parts:
    return Parts.get(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")


def validate(tmp_path: Path, text: str, parts: Parts | None) -> list[ValidationIssue]:
    file = tmp_path / "model.ldr"
    file.write_text(text)
    return list(iter_ldr_issues(file, parts))


def test_clean_file_has_no_issues(tmp_path: Path, parts: Parts) -> None:
    text = f"0 Model\n1 4 0 0 0 {IDENTITY} 3001.dat\n"

    assert validate(tmp_path, text, parts) == []


def test_unknown_colour_code_is_an_error(tmp_path: Path, parts: Parts) -> None:
    issues = validate(tmp_path, f"1 999 0 0 0 {IDENTITY} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown colour code 999"),
    ]
    assert issues[0].severity is Severity.ERROR


def test_unknown_colour_checked_on_geometry_lines(
    tmp_path: Path,
    parts: Parts,
) -> None:
    issues = validate(tmp_path, "2 999 0 0 0 1 1 1\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown colour code 999"),
    ]


def test_legacy_dithered_colour_is_a_warning(
    tmp_path: Path,
    parts: Parts,
) -> None:
    issues = validate(tmp_path, f"1 256 0 0 0 {IDENTITY} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="legacy dithered colour code 256",
            severity=Severity.WARNING,
        ),
    ]


def test_garbage_colour_token_is_an_error_even_without_library(
    tmp_path: Path,
) -> None:
    issues = validate(tmp_path, f"1 abc 0 0 0 {IDENTITY} 3001.dat\n", None)

    assert issues == [
        ValidationIssue(line_number=1, message="Invalid colour value 'abc'"),
    ]
    assert issues[0].severity is Severity.ERROR


def test_malformed_direct_colour_is_reported_not_crashed(tmp_path: Path) -> None:
    issues = validate(tmp_path, f"1 0x2GGHHII 0 0 0 {IDENTITY} 3001.dat\n", None)

    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR
    assert "Invalid colour value" in issues[0].message


def test_valid_direct_colour_is_clean(tmp_path: Path, parts: Parts) -> None:
    assert validate(tmp_path, f"1 0x2FF0000 0 0 0 {IDENTITY} 3001.dat\n", parts) == []


def test_decimal_direct_colour_is_clean(tmp_path: Path, parts: Parts) -> None:
    assert validate(tmp_path, f"1 50266112 0 0 0 {IDENTITY} 3001.dat\n", parts) == []


def test_uppercase_direct_colour_prefix_is_clean(
    tmp_path: Path,
    parts: Parts,
) -> None:
    assert validate(tmp_path, f"1 0X2FF0000 0 0 0 {IDENTITY} 3001.dat\n", parts) == []


def test_short_direct_colour_is_an_error(tmp_path: Path, parts: Parts) -> None:
    issues = validate(tmp_path, f"1 0x2FFF 0 0 0 {IDENTITY} 3001.dat\n", parts)

    assert len(issues) == 1
    assert issues[0].severity is Severity.ERROR
    assert "Invalid colour value '0x2FFF'" in issues[0].message


def test_catalogued_dithered_range_colour_does_not_warn(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "lib" / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    (ldraw_dir / "LDConfig.ldr").write_text(
        "0 !COLOUR Magnet CODE 493 VALUE #656761 EDGE #595959\n",
    )
    catalogued_parts = Parts(ldraw_dir / "parts.lst")

    text = f"1 493 0 0 0 {IDENTITY} 3001.dat\n"
    assert validate(tmp_path, text, catalogued_parts) == []


def test_colour_codes_skipped_without_library(tmp_path: Path) -> None:
    assert validate(tmp_path, "2 999 0 0 0 1 1 1\n", None) == []


def test_colour_codes_skipped_when_ldconfig_missing(tmp_path: Path) -> None:
    ldraw_dir = tmp_path / "lib" / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n")
    (ldraw_dir / "parts.lst").write_text("3001.dat  Brick 2 x 4\n")
    bare_parts = Parts(ldraw_dir / "parts.lst")

    text = f"1 999 0 0 0 {IDENTITY} 3001.dat\n"
    assert validate(tmp_path, text, bare_parts) == []


def test_singular_matrix_is_a_warning(tmp_path: Path, parts: Parts) -> None:
    issues = validate(tmp_path, f"1 4 0 0 0 {SINGULAR} 3001.dat\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="singular transformation matrix (flattens geometry)",
            severity=Severity.WARNING,
        ),
    ]


def test_scaled_matrix_is_a_warning(tmp_path: Path, parts: Parts) -> None:
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


def test_rotated_matrix_is_clean(tmp_path: Path, parts: Parts) -> None:
    assert validate(tmp_path, f"1 4 0 0 0 {ROTATED_90_Y} 3001.dat\n", parts) == []


def test_unknown_bang_meta_is_a_warning(tmp_path: Path, parts: Parts) -> None:
    issues = validate(tmp_path, "0 !FOOBAR something\n", parts)

    assert issues == [
        ValidationIssue(
            line_number=1,
            message="unknown meta-command !FOOBAR",
            severity=Severity.WARNING,
        ),
    ]


@pytest.mark.parametrize("meta", sorted(KNOWN_META_COMMANDS))
def test_known_bang_metas_are_clean(tmp_path: Path, meta: str) -> None:
    assert validate(tmp_path, f"0 !{meta} something\n", None) == []


def test_plain_comments_and_commands_are_never_flagged(
    tmp_path: Path,
    parts: Parts,
) -> None:
    text = "0 STEP\n0 BFC CERTIFY CCW\n0 WRITE hello\n0 just some prose\n"

    assert validate(tmp_path, text, parts) == []


def test_blank_lines_are_ignored(tmp_path: Path, parts: Parts) -> None:
    text = f"0 Model\n\n1 4 0 0 0 {IDENTITY} 3001.dat\n\n"

    assert validate(tmp_path, text, parts) == []


def test_malformed_line_is_an_error(tmp_path: Path) -> None:
    issues = validate(tmp_path, "9 16 0 0 0\n", None)

    assert issues == [
        ValidationIssue(line_number=1, message="Unknown command (9)"),
    ]


def test_unknown_part_reference_is_an_error(tmp_path: Path, parts: Parts) -> None:
    issues = validate(tmp_path, f"1 4 0 0 0 {IDENTITY} 9999.dat\n", parts)

    assert issues == [
        ValidationIssue(line_number=1, message="unknown part 9999.dat"),
    ]


def test_own_submodel_references_are_not_unknown_parts(
    tmp_path: Path,
    parts: Parts,
) -> None:
    text = (
        "0 FILE main.ldr\n"
        f"1 16 0 0 0 {IDENTITY} BODY.LDR\n"
        "0 NOFILE\n"
        "0 FILE body.ldr\n"
        f"1 4 0 0 0 {IDENTITY} 3001.dat\n"
        "0 NOFILE\n"
    )

    assert validate(tmp_path, text, parts) == []


def test_one_line_can_produce_multiple_issues(
    tmp_path: Path,
    parts: Parts,
) -> None:
    issues = validate(tmp_path, f"1 999 0 0 0 {SCALED} 9999.dat\n", parts)

    messages = [issue.message for issue in issues]
    assert messages == [
        "unknown colour code 999",
        "transformation matrix is not orthonormal (scaled or sheared part)",
        "unknown part 9999.dat",
    ]


def test_issues_are_yielded_in_line_order(tmp_path: Path) -> None:
    text = (
        f"0 !FOOBAR one\n9 16 0 0 0\n0 !BARBAZ three\n1 4 0 0 x {IDENTITY} 3001.dat\n"
    )

    issues = validate(tmp_path, text, None)

    assert [issue.line_number for issue in issues] == [1, 2, 3, 4]


def test_file_level_issues_come_before_numbered_ones(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ldr"

    issues = list(iter_ldr_issues(missing, None))

    assert [issue.line_number for issue in issues] == [None]
    assert issues[0].code is DiagnosticCode.IO_READ_FAILED


def test_every_diagnostic_code_is_a_stable_enum_member(
    tmp_path: Path,
    parts: Parts,
) -> None:
    text = (
        "0 !FOOBAR something\n"
        f"1 256 0 0 0 {IDENTITY} 3001.dat\n"
        f"1 4 0 0 0 {SINGULAR} 3001.dat\n"
        f"1 999 0 0 0 {SCALED} 9999.dat\n"
        "9 16 0 0 0\n"
        "2 16 bad 0 0 1 1 1\n"
        "1 abc 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
    )

    issues = validate(tmp_path, text, parts)

    assert issues
    assert all(isinstance(issue.code, DiagnosticCode) for issue in issues)
    assert {
        DiagnosticCode.MODEL_UNKNOWN_META,
        DiagnosticCode.MODEL_LEGACY_COLOUR,
        DiagnosticCode.MODEL_SINGULAR_MATRIX,
        DiagnosticCode.MODEL_NON_ORTHONORMAL_MATRIX,
    } <= {issue.code for issue in issues}
    assert DiagnosticCode.MODEL_LEGACY_COLOUR.value == "model.legacy_colour"
    assert DiagnosticCode.MODEL_SINGULAR_MATRIX.value == "model.singular_matrix"
    assert (
        DiagnosticCode.MODEL_NON_ORTHONORMAL_MATRIX.value
        == "model.non_orthonormal_matrix"
    )
    assert DiagnosticCode.MODEL_UNKNOWN_META.value == "model.unknown_meta"


@pytest.mark.parametrize("suffix", ["ldr", "mpd"])
def test_unresolved_sibling_reference_without_catalog_is_one_warning(
    tmp_path: Path,
    suffix: str,
) -> None:
    text = f"0 FILE main.ldr\n1 16 0 0 0 {IDENTITY} missing.{suffix}\n0 NOFILE\n"

    issues = validate(tmp_path, text, None)

    assert [issue.code for issue in issues] == [DiagnosticCode.MPD_UNRESOLVED_SUBMODEL]
    assert issues[0].severity is Severity.WARNING
    assert issues[0].section == "main.ldr"
    assert issues[0].line_number == 2


def test_unresolved_sibling_reference_with_catalog_is_not_double_reported(
    tmp_path: Path,
    parts: Parts,
) -> None:
    text = f"0 FILE main.ldr\n1 16 0 0 0 {IDENTITY} missing.ldr\n0 NOFILE\n"

    issues = validate(tmp_path, text, parts)

    assert [(issue.code, issue.section, issue.line_number) for issue in issues] == [
        (DiagnosticCode.MPD_UNRESOLVED_SUBMODEL, "main.ldr", 2)
    ]
    assert issues[0].severity is Severity.WARNING
    assert DiagnosticCode.MODEL_UNKNOWN_PART not in {issue.code for issue in issues}
