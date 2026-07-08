"""Tests for configuration functionality."""

import sys
from pathlib import Path

import pytest

from ldraw.config import CONFIG_FILE, Config, get_config


def test_get_config_never_reads_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A --config flag on the host process belongs to the embedding
    # application, not to this library.
    monkeypatch.setattr(
        sys,
        "argv",
        ["someapp", "--config", "/nonexistent/other.yml"],
    )

    assert get_config() == CONFIG_FILE
    assert get_config("/explicit/config.yml") == Path("/explicit/config.yml")


def test_config_load_ignores_argv_config_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    other = tmp_path / "other.yml"
    other.write_text("ldraw_library_path: /elsewhere")
    monkeypatch.setattr(sys, "argv", ["someapp", "--config", str(other)])

    config = Config.load()

    assert config.ldraw_library_path != "/elsewhere"


def test_config_can_load_win(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("ldraw_library_path: C:\\file_path")

    config = Config.load(config_path)
    assert config.ldraw_library_path == "C:\\file_path"


def test_config_can_load(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("ldraw_library_path: /home/file_path")

    config = Config.load(config_path)
    assert config.ldraw_library_path == "/home/file_path"
