"""Tests for configuration functionality."""

from unittest.mock import mock_open, patch

from pytest import raises
from yaml import YAMLError

from ldraw.config import Config


def fails(*args, **kwargs):
    raise YAMLError()


@patch("yaml.load", side_effect=fails)
def test_config_cant_load(yaml_load_mock):
    yaml_load_mock.side_effect = fails

    raises(YAMLError, Config.load)


@patch(
    "ldraw.config.open",
    side_effect=mock_open(read_data="ldraw_library_path: C:\\file_path"),
)
def test_config_can_load_win(open_mock):
    config = Config.load()
    assert config.ldraw_library_path == "C:\\file_path"


@patch(
    "ldraw.config.open",
    side_effect=mock_open(read_data="ldraw_library_path: /home/file_path"),
)
def test_config_can_load(open_mock):
    config = Config.load()
    assert config.ldraw_library_path == "/home/file_path"
