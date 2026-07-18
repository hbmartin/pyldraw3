"""Tests for the argparse-based ldraw CLI."""

import json
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from ldraw.cli import _confirm, _suggested_import, build_parser, main
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.errors import ConfigLoadError, CouldNotDetermineLatestVersionError
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.parts import CatalogEntry, MinifigSection, PartCategory

TESTS_DIR = Path(__file__).resolve().parent

FIXTURE_CONFIG = Config(
    ldraw_library_path=str(TESTS_DIR / "test_ldraw"),
    generated_path="/gen",
)


class _FakeStdin:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    assert "usage" in capsys.readouterr().out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "usage" in out
    assert "command" in out


def test_unknown_command_exits_two() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["bogus"])

    assert excinfo.value.code == 2


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0

    assert capsys.readouterr().out.strip() == package_version("pyldraw3")


@patch("ldraw.cli.Config.load")
def test_config_prints_yaml(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config(
        ldraw_library_path="/lib",
        generated_path="/gen",
    )
    config.internal_cache = "secret"
    config_load_mock.return_value = config

    assert main(["config"]) == 0

    out = capsys.readouterr().out
    assert "ldraw_library_path: /lib" in out
    assert "generated_path: /gen" in out
    assert "secret" not in out


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", return_value="2024-01")
def test_download_default_version(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["download", "--yes"]) == 0

    do_download_mock.assert_called_once()
    assert do_download_mock.call_args.kwargs["version"] == COMPLETE_VERSION
    config = config_mock.load.return_value
    assert config.ldraw_library_path == str(cache_ldraw / COMPLETE_VERSION)
    config.write.assert_called_once()
    assert "2024-01" in capsys.readouterr().err


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", return_value="2018-02")
def test_download_explicit_version(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
) -> None:
    assert main(["download", "--version", "2018-02", "--yes"]) == 0

    assert do_download_mock.call_args.kwargs["version"] == "2018-02"
    config = config_mock.load.return_value
    assert config.ldraw_library_path == str(cache_ldraw / "2018-02")
    config.write.assert_called_once()


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", return_value="2018-02")
def test_download_config_write_failure_returns_one(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_mock.load.return_value.write.side_effect = OSError("read-only")

    assert main(["download", "--version", "2018-02", "--yes"]) == 1

    do_download_mock.assert_called_once()
    assert "Could not update configuration: read-only" in capsys.readouterr().err


@patch("ldraw.cli._confirm", return_value=False)
@patch("ldraw.cli.do_download")
def test_download_declined(
    do_download_mock: MagicMock,
    confirm_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["download"]) == 1

    do_download_mock.assert_not_called()
    assert "Aborted." in capsys.readouterr().out


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", side_effect=requests.HTTPError("not found"))
def test_download_failure_returns_one(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["download", "--yes"]) == 1

    do_download_mock.assert_called_once()
    config_mock.load.assert_not_called()
    assert "Download failed: not found" in capsys.readouterr().err


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate(
    do_generate_mock: MagicMock,
    config_load_mock: MagicMock,
) -> None:
    assert main(["generate", "--yes"]) == 0

    do_generate_mock.assert_called_once_with(
        config=config_load_mock.return_value,
        force=False,
    )


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate_force(
    do_generate_mock: MagicMock,
    config_load_mock: MagicMock,
) -> None:
    assert main(["generate", "--yes", "--force"]) == 0

    do_generate_mock.assert_called_once_with(
        config=config_load_mock.return_value,
        force=True,
    )


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate", side_effect=UnwritableOutputError("/gen"))
def test_generate_unwritable_returns_one(
    do_generate_mock: MagicMock,
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_load_mock.return_value = MagicMock(generated_path="/gen")

    assert main(["generate", "--yes"]) == 1

    assert "unwritable" in capsys.readouterr().err


@patch("ldraw.cli._confirm", return_value=False)
@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate_declined(
    do_generate_mock: MagicMock,
    config_load_mock: MagicMock,
    confirm_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["generate"]) == 1

    do_generate_mock.assert_not_called()
    assert "Aborted." in capsys.readouterr().out


def test_confirm_yes_flag_skips_prompt() -> None:
    assert _confirm("Continue?", yes=True) is True


def test_confirm_non_tty_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

    assert _confirm("Continue?", yes=False) is True
    assert "Non-interactive" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("y", True), ("yes", True), ("Y", True), ("n", False), ("", False)],
)
def test_confirm_tty_prompts(
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    *,
    expected: bool,
) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda _: answer)

    assert _confirm("Continue?", yes=False) is expected


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_search_finds_fixture_brick(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "search", "brick"]) == 0

    out = capsys.readouterr().out
    assert "3001" in out
    assert "Brick  2 x  4" in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_search_no_match_returns_one(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "search", "nonexistent"]) == 1

    assert "No parts found matching" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_search_truncates_at_limit(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "search", "brick", "--limit", "0"]) == 0

    assert "... and 1 more (use --limit)." in capsys.readouterr().out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_info_shows_details_and_import(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "info", "3001"]) == 0

    out = capsys.readouterr().out
    assert "code: 3001" in out
    assert "description: Brick  2 x  4" in out
    assert "category: brick" in out
    assert "import: from ldraw.library.parts.bricks import Brick2X4" in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_info_unknown_code_returns_one(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "info", "9999"]) == 1

    assert "No part with code '9999'." in capsys.readouterr().err


@patch("ldraw.cli.Config.load")
def test_parts_commands_without_library_return_one(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_load_mock.return_value = Config(
        ldraw_library_path=str(tmp_path),
        generated_path="/gen",
    )

    assert main(["parts", "search", "brick"]) == 1
    assert main(["parts", "info", "3001"]) == 1

    assert "run `ldraw download` first" in capsys.readouterr().err


def test_suggested_import_minifig_section() -> None:
    entry = CatalogEntry(
        code="3901",
        description="Minifig Hair Male",
        category=PartCategory.OTHER,
        minifig_section=MinifigSection.HATS,
    )

    # The Minifig prefix is stripped from generated symbol names.
    assert _suggested_import(entry) == (
        "from ldraw.library.parts.minifig.hats import HairMale"
    )


def test_suggested_import_other_category_is_none() -> None:
    entry = CatalogEntry(
        code="9999",
        description="Weird Part",
        category=PartCategory.OTHER,
    )

    assert _suggested_import(entry) is None


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_clean_file(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 Model\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["validate", str(model)]) == 0

    assert "OK" in capsys.readouterr().out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_reports_issues_with_line_numbers(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(
        "0 Model\n9 16 0 0 0\n2 16 0 0 x 1 1 1\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 9999.dat\n",
    )

    assert main(["validate", str(model)]) == 1

    out = capsys.readouterr().out
    assert f"{model}:2: error: Unknown command (9)" in out
    assert f"{model}:3: error: Invalid numeric value 'x'" in out
    assert f"{model}:4: error: unknown part 9999.dat" in out
    assert "3 error(s), 0 warning(s)" in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_skips_submodel_references(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.mpd"
    model.write_text(
        "0 FILE main.ldr\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 BODY.LDR\n"
        "0 NOFILE\n"
        "0 FILE body.ldr\n"
        "1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        "0 NOFILE\n",
    )

    assert main(["validate", str(model)]) == 0

    assert "OK" in capsys.readouterr().out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_missing_file_returns_one(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", "does/not/exist.ldr"]) == 1

    assert "not found" in capsys.readouterr().err


@patch("ldraw.cli.Config.load")
def test_validate_without_library_is_syntax_only(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_load_mock.return_value = Config(
        ldraw_library_path=str(tmp_path),
        generated_path="/gen",
    )
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 9999.dat\n")

    assert main(["validate", str(model)]) == 0

    captured = capsys.readouterr()
    assert "skipping unknown-part and colour checks" in captured.err
    assert "OK" in captured.out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_warnings_pass_without_strict(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 2 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["validate", str(model)]) == 0

    out = capsys.readouterr().out
    assert "warning: transformation matrix is not orthonormal" in out
    assert "0 error(s), 1 warning(s)" in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_strict_fails_on_warnings(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 !FOOBAR meta\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["validate", str(model), "--strict"]) == 1

    out = capsys.readouterr().out
    assert "warning: unknown meta-command !FOOBAR" in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_reports_unknown_colours(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 999 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["validate", str(model)]) == 1

    out = capsys.readouterr().out
    assert f"{model}:1: error: unknown colour code 999" in out
    assert "1 error(s), 0 warning(s)" in out


def test_parts_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["parts"])

    assert excinfo.value.code == 2


def test_build_parser_parts_search_defaults() -> None:
    args = build_parser().parse_args(["parts", "search", "brick"])

    assert args.parts_command == "search"
    assert args.term == "brick"
    assert args.limit == 25


def test_build_parser_parts_info() -> None:
    args = build_parser().parse_args(["parts", "info", "3001"])

    assert args.parts_command == "info"
    assert args.code == "3001"


def test_build_parser_validate() -> None:
    args = build_parser().parse_args(["validate", "model.ldr"])

    assert args.file == Path("model.ldr")


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_table_output(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text(
        "0 Model\n"
        "1 189 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        "1 189 0 -24 0 1 0 0 0 1 0 0 0 1 3001.dat\n",
    )

    assert main(["bom", str(model)]) == 0

    out = capsys.readouterr().out
    assert "qty" in out
    assert "3001" in out
    assert "Reddish_Gold" in out
    assert "Brick  2 x  4" in out
    assert "    2  " in out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_csv_stdout_is_machine_clean(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 189 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["bom", str(model), "--format", "csv"]) == 0

    out = capsys.readouterr().out
    assert out == (
        "part,description,colour_code,colour_name,quantity\n"
        "3001,Brick  2 x  4,189,Reddish_Gold,1\n"
    )


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_json_output(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 189 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["bom", str(model), "--format", "json"]) == 0

    parsed = json.loads(capsys.readouterr().out)
    assert parsed == [
        {
            "part": "3001",
            "description": "Brick  2 x  4",
            "colour_code": 189,
            "colour_name": "Reddish_Gold",
            "quantity": 1,
        },
    ]


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_writes_output_file(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 189 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")
    out_file = tmp_path / "bom.csv"

    assert main(["bom", str(model), "--format", "csv", "-o", str(out_file)]) == 0

    assert "Wrote 1 rows to" in capsys.readouterr().out
    assert out_file.read_text().startswith("part,description,")


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_empty_model_prints_no_pieces(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("0 Just a comment\n")

    assert main(["bom", str(model)]) == 0

    assert "no pieces" in capsys.readouterr().out


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_missing_file_returns_one(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["bom", "does/not/exist.ldr"]) == 1

    assert "not found" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_malformed_file_returns_one(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("9 16 0 0 0\n")

    assert main(["bom", str(model)]) == 1

    assert "Unknown command (9)" in capsys.readouterr().err


@patch("ldraw.cli.Config.load")
def test_bom_without_library_notes_on_stderr(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_load_mock.return_value = Config(
        ldraw_library_path=str(tmp_path),
        generated_path="/gen",
    )
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")

    assert main(["bom", str(model), "--format", "csv"]) == 0

    captured = capsys.readouterr()
    assert "no parts library found" in captured.err
    assert captured.out == (
        "part,description,colour_code,colour_name,quantity\n3001,,4,,1\n"
    )


def test_build_parser_bom_defaults() -> None:
    args = build_parser().parse_args(["bom", "model.ldr"])

    assert args.file == Path("model.ldr")
    assert args.format == "table"
    assert args.output is None


def test_build_parser_stubs_defaults() -> None:
    args = build_parser().parse_args(["stubs"])

    assert args.out == Path()


@patch("ldraw.cli.Config.load")
def test_stubs_writes_package(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generated = tmp_path / "generated"
    (generated / "library").mkdir(parents=True)
    (generated / "library" / "__init__.py").write_text("__all__ = []\n")
    config_load_mock.return_value = Config(
        ldraw_library_path="/lib",
        generated_path=str(generated),
    )
    out_dir = tmp_path / "project"
    out_dir.mkdir()

    assert main(["stubs", "--out", str(out_dir)]) == 0

    assert "Wrote stub package to" in capsys.readouterr().out
    assert (out_dir / "ldraw-stubs" / "py.typed").read_text() == "partial\n"


@patch("ldraw.cli.Config.load")
def test_stubs_without_generated_library_returns_one(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_load_mock.return_value = Config(
        ldraw_library_path="/lib",
        generated_path=str(tmp_path),
    )

    assert main(["stubs"]) == 1

    assert "run `ldraw generate` first" in capsys.readouterr().err


def test_build_parser_download_defaults() -> None:
    args = build_parser().parse_args(["download"])

    assert args.version == COMPLETE_VERSION
    assert args.yes is False


def test_build_parser_generate_defaults() -> None:
    args = build_parser().parse_args(["generate"])

    assert args.yes is False
    assert args.force is False


@patch("ldraw.cli.package_version", side_effect=PackageNotFoundError)
def test_version_handles_missing_package(
    package_version_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["version"]) == 0

    package_version_mock.assert_called_once_with("pyldraw3")
    assert capsys.readouterr().out.strip() == "unknown (not installed)"


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
@patch("ldraw.cli.do_generate", side_effect=FileNotFoundError)
def test_generate_before_download_hints(
    do_generate_mock: MagicMock,
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["generate", "--yes"]) == 1

    assert "run `ldraw download` first" in capsys.readouterr().err


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", side_effect=CouldNotDetermineLatestVersionError)
def test_download_reports_latest_version_failure(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["download", "--yes"]) == 1

    assert "Download failed" in capsys.readouterr().err


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", side_effect=OSError("disk full"))
def test_download_reports_oserror(
    do_download_mock: MagicMock,
    config_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["download", "--yes"]) == 1

    assert "Download failed: disk full" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_validate_non_utf8_file_reports_error(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "binary.ldr"
    model.write_bytes(b"\xff\xfe\x00bad")

    assert main(["validate", str(model)]) == 1

    assert "not valid UTF-8" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_non_utf8_file_reports_error(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "binary.ldr"
    model.write_bytes(b"\xff\xfe\x00bad")

    assert main(["bom", str(model)]) == 1

    assert "codec" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_bom_output_write_failure_returns_one(
    config_load_mock: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = tmp_path / "model.ldr"
    model.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n")
    missing_dir = tmp_path / "nonexistent" / "bom.csv"

    assert main(["bom", str(model), "-o", str(missing_dir)]) == 1

    assert "Could not write" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
@patch("ldraw.cli.write_stub_package", side_effect=OSError("denied"))
def test_stubs_write_failure_returns_one(
    write_stub_mock: MagicMock,
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["stubs"]) == 1

    assert "Could not write stubs" in capsys.readouterr().err


@patch("ldraw.cli.Config.load", return_value=FIXTURE_CONFIG)
def test_parts_search_normalizes_whitespace(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["parts", "search", "brick 2 x 4"]) == 0

    assert "3001" in capsys.readouterr().out


@patch(
    "ldraw.cli.Config.load",
    side_effect=ConfigLoadError(path="/c.yml", reason="boom"),
)
def test_config_load_error_exits_one(
    config_load_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["config"]) == 1

    assert "Could not load config /c.yml: boom" in capsys.readouterr().err
