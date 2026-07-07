"""Tests for the argparse-based ldraw CLI."""

import sys
from importlib.metadata import version as package_version
from unittest.mock import MagicMock, patch

import pytest

from ldraw.cli import _confirm, build_parser, main
from ldraw.config import Config
from ldraw.downloads import COMPLETE_VERSION, cache_ldraw
from ldraw.generation.exceptions import UnwritableOutputError


class _FakeStdin:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    assert "usage" in capsys.readouterr().out


def test_no_args_prints_help(capsys) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "usage" in out
    assert "command" in out


def test_unknown_command_exits_two() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["bogus"])

    assert excinfo.value.code == 2


def test_version_prints_package_version(capsys) -> None:
    assert main(["version"]) == 0

    assert capsys.readouterr().out.strip() == package_version("pyldraw3")


@patch("ldraw.cli.Config.load")
def test_config_prints_yaml(config_load_mock, capsys) -> None:
    config_load_mock.return_value = Config(
        ldraw_library_path="/lib",
        generated_path="/gen",
    )

    assert main(["config"]) == 0

    out = capsys.readouterr().out
    assert "ldraw_library_path: /lib" in out
    assert "generated_path: /gen" in out


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", return_value="2024-01")
def test_download_default_version(do_download_mock, config_mock, capsys) -> None:
    assert main(["download", "--yes"]) == 0

    do_download_mock.assert_called_once()
    assert do_download_mock.call_args.kwargs["version"] == COMPLETE_VERSION
    config = config_mock.load.return_value
    assert config.ldraw_library_path == str(cache_ldraw / COMPLETE_VERSION)
    config.write.assert_called_once()
    assert "2024-01" in capsys.readouterr().out


@patch("ldraw.cli.Config")
@patch("ldraw.cli.do_download", return_value="2018-02")
def test_download_explicit_version(do_download_mock, config_mock) -> None:
    assert main(["download", "--version", "2018-02", "--yes"]) == 0

    assert do_download_mock.call_args.kwargs["version"] == "2018-02"
    config = config_mock.load.return_value
    assert config.ldraw_library_path == str(cache_ldraw / "2018-02")
    config.write.assert_called_once()


@patch("ldraw.cli._confirm", return_value=False)
@patch("ldraw.cli.do_download")
def test_download_declined(do_download_mock, confirm_mock, capsys) -> None:
    assert main(["download"]) == 1

    do_download_mock.assert_not_called()
    assert "Aborted." in capsys.readouterr().out


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate(do_generate_mock, config_load_mock) -> None:
    assert main(["generate", "--yes"]) == 0

    do_generate_mock.assert_called_once_with(
        config=config_load_mock.return_value,
        force=False,
    )


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate_force(do_generate_mock, config_load_mock) -> None:
    assert main(["generate", "--yes", "--force"]) == 0

    do_generate_mock.assert_called_once_with(
        config=config_load_mock.return_value,
        force=True,
    )


@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate", side_effect=UnwritableOutputError)
def test_generate_unwritable_returns_one(
    do_generate_mock,
    config_load_mock,
    capsys,
) -> None:
    config_load_mock.return_value = MagicMock(generated_path="/gen")

    assert main(["generate", "--yes"]) == 1

    assert "unwritable" in capsys.readouterr().out


@patch("ldraw.cli._confirm", return_value=False)
@patch("ldraw.cli.Config.load")
@patch("ldraw.cli.do_generate")
def test_generate_declined(
    do_generate_mock,
    config_load_mock,
    confirm_mock,
    capsys,
) -> None:
    assert main(["generate"]) == 1

    do_generate_mock.assert_not_called()
    assert "Aborted." in capsys.readouterr().out


def test_confirm_yes_flag_skips_prompt() -> None:
    assert _confirm("Continue?", yes=True) is True


def test_confirm_non_tty_proceeds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

    assert _confirm("Continue?", yes=False) is True
    assert "Non-interactive" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("y", True), ("yes", True), ("Y", True), ("n", False), ("", False)],
)
def test_confirm_tty_prompts(monkeypatch, answer: str, *, expected: bool) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda _: answer)

    assert _confirm("Continue?", yes=False) is expected


def test_build_parser_download_defaults() -> None:
    args = build_parser().parse_args(["download"])

    assert args.version == COMPLETE_VERSION
    assert args.yes is False


def test_build_parser_generate_defaults() -> None:
    args = build_parser().parse_args(["generate"])

    assert args.yes is False
    assert args.force is False
