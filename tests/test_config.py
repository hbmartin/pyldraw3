"""Tests for configuration functionality."""

from typing import Never
from unittest.mock import mock_open, patch

from pytest import raises
from yaml import YAMLError

from ldraw.config import Config


@patch(
    "ldraw.config.open",
    side_effect=mock_open(read_data="ldraw_library_path: C:\\file_path"),
)
def test_config_can_load_win(open_mock) -> None:
    config = Config.load()
    assert config.ldraw_library_path == "C:\\file_path"


@patch(
    "ldraw.config.open",
    side_effect=mock_open(read_data="ldraw_library_path: /home/file_path"),
)
def test_config_can_load(open_mock) -> None:
    config = Config.load()
    assert config.ldraw_library_path == "/home/file_path"
