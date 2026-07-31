"""CLI coverage for the nested instruction commands."""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from ldraw.cli import _dispatch_instructions, main
from ldraw.parts import Parts

TESTS_DIR = Path(__file__).resolve().parent
PARTS = Parts(TESTS_DIR / "test_ldraw" / "ldraw" / "parts.lst")


def _piece(reference: str = "3001.dat", *, x: int = 0) -> str:
    return f"1 4 {x} 0 0 1 0 0 0 1 0 0 0 1 {reference}"


def _write_model(path: Path, *, instructions: tuple[str, ...] = ()) -> Path:
    path.write_text(
        "\n".join((*instructions, _piece(), "0 STEP", _piece(x=20), "")),
        encoding="utf-8",
    )
    return path


def test_unknown_instruction_subcommand_fails_explicitly() -> None:
    with pytest.raises(AssertionError, match="Unhandled instructions subcommand"):
        _dispatch_instructions(Namespace(instructions_command="future"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["instructions", "inspect", "model.ldr"],
        ["instructions", "validate", "model.ldr"],
        ["instructions", "export", "model.ldr"],
        ["instructions", "snapshots", "model.ldr", "--out", "bundle"],
    ],
)
@patch("ldraw.cli._load_parts", return_value=None)
def test_all_instruction_commands_require_a_catalog(
    load_parts_mock: object,
    arguments: list[str],
) -> None:
    assert main(arguments) == 1


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_inspect_prints_step_rows_and_optional_parts_trays(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = _write_model(
        tmp_path / "model.ldr",
        instructions=("0 !LPUB INSERT PAGE",),
    )

    assert main(["instructions", "inspect", str(model), "--parts"]) == 0

    output = capsys.readouterr().out
    assert "section  step  direct  expanded  cumulative" in output
    assert "model.ldr" in output
    assert "yes" in output
    assert "3001" in output
    assert "Brick  2 x  4" in output


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_inspect_selects_sections_and_reports_unknown_names(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.mpd"
    model.write_text(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("sub.ldr"),
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(),
                "0 NOFILE",
            )
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "instructions",
                "inspect",
                str(model),
                "--section",
                "SUB.LDR",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "sub.ldr" in output
    assert "main.ldr  " not in output

    assert (
        main(
            [
                "instructions",
                "inspect",
                str(model),
                "--section",
                "missing.ldr",
            ]
        )
        == 1
    )
    assert "No reachable instruction section" in capsys.readouterr().err


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_instruction_validate_combines_lint_and_semantic_exit_codes(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    warning = tmp_path / "warning.ldr"
    warning.write_text(f"{_piece()}\n{_piece(x=20)}\n", encoding="utf-8")

    assert main(["instructions", "validate", str(warning)]) == 0
    output = capsys.readouterr().out
    assert "[no-step-boundaries]" in output
    assert "0 error(s), 1 warning(s)" in output

    assert main(["instructions", "validate", str(warning), "--strict"]) == 1
    capsys.readouterr()

    malformed = tmp_path / "malformed.ldr"
    malformed.write_text(f"{_piece()}\n0 ROTSTEP x 0 0\n", encoding="utf-8")
    assert main(["instructions", "validate", str(malformed)]) == 1
    assert "[malformed-directive]" in capsys.readouterr().out


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_instruction_validate_max_parts_and_invalid_threshold(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = _write_model(tmp_path / "model.ldr")

    assert (
        main(
            [
                "instructions",
                "validate",
                str(model),
                "--max-parts",
                "0",
                "--strict",
            ]
        )
        == 1
    )
    assert "[step-too-large]" in capsys.readouterr().out
    assert (
        main(
            [
                "instructions",
                "validate",
                str(model),
                "--max-parts",
                "-1",
            ]
        )
        == 1
    )
    assert "zero or greater" in capsys.readouterr().err


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_export_supports_stdout_files_collisions_and_force(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = _write_model(tmp_path / "model.ldr")

    assert main(["instructions", "export", str(model)]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["schema_version"] == 1
    assert manifest["source"] == str(model)

    output = tmp_path / "instructions.json"
    arguments = ["instructions", "export", str(model), "-o", str(output)]
    assert main(arguments) == 0
    assert output.is_file()
    capsys.readouterr()
    assert main(arguments) == 1
    assert "already exists" in capsys.readouterr().err
    assert main([*arguments, "--force"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_snapshots_support_section_selection_collisions_and_force(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.mpd"
    model.write_text(
        "\n".join(
            (
                "0 FILE main.ldr",
                _piece("sub.ldr"),
                "0 NOFILE",
                "0 FILE sub.ldr",
                _piece(),
                "0 NOFILE",
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "bundle"
    arguments = [
        "instructions",
        "snapshots",
        str(model),
        "--out",
        str(output),
        "--section",
        "sub.ldr",
    ]

    assert main(arguments) == 0
    assert (output / "001-sub/step-0001.mpd").is_file()
    assert "Wrote instruction snapshots" in capsys.readouterr().err
    assert main(arguments) == 1
    assert "not empty" in capsys.readouterr().err
    assert main([*arguments, "--force"]) == 0

    bad_section = [*arguments[:-1], "missing.ldr", "--force"]
    assert main(bad_section) == 1
    assert "No reachable instruction section" in capsys.readouterr().err


@patch("ldraw.cli._load_parts", return_value=PARTS)
def test_instruction_commands_report_missing_or_invalid_input(
    load_parts_mock: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.ldr"
    assert main(["instructions", "inspect", str(missing)]) == 1
    assert "not found" in capsys.readouterr().err

    invalid = tmp_path / "invalid.ldr"
    invalid.write_text("1 4 broken\n", encoding="utf-8")
    assert main(["instructions", "export", str(invalid)]) == 1
    assert "must have" in capsys.readouterr().err
