"""Tests for configuration functionality."""

from pathlib import Path

from ldraw.config import Config


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
