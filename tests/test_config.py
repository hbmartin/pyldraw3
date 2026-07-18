"""Tests for configuration functionality."""

import sys
from pathlib import Path

import pytest
import yaml

from ldraw.config import CONFIG_FILE, Config, get_config
from ldraw.errors import ConfigLoadError


def test_get_config_never_reads_argv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A --config flag on the host process belongs to the embedding
    # application, not to this library.
    monkeypatch.setattr(
        sys,
        "argv",
        ["someapp", "--config", "/nonexistent/other.yml"],
    )
    isolated = tmp_path / "config.yml"
    monkeypatch.setattr("ldraw.config.CONFIG_FILE", isolated)

    assert get_config() == isolated
    assert get_config("/explicit/config.yml") == Path("/explicit/config.yml")
    # The module constant itself is what get_config falls back to.
    assert CONFIG_FILE.name == "config.yml"


def test_config_load_ignores_argv_config_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("ldraw.config.CONFIG_FILE", tmp_path / "config.yml")
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


def test_config_load_rejects_yaml_list(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("- a\n- b\n")

    with pytest.raises(ConfigLoadError, match=r"expected a mapping, got list") as exc:
        Config.load(config_path)
    assert str(config_path) in str(exc.value)


def test_config_load_rejects_malformed_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("{unclosed")

    with pytest.raises(ConfigLoadError, match=str(config_path)):
        Config.load(config_path)


def test_config_load_rejects_directory_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match=str(tmp_path)):
        Config.load(tmp_path)


def test_config_load_rejects_non_string_value(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("ldraw_library_path: 3")

    with pytest.raises(ConfigLoadError, match=r"ldraw_library_path must be a string"):
        Config.load(config_path)


def test_config_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = Config.load(tmp_path / "nonexistent.yml")

    assert config.ldraw_library_path
    assert config.generated_path


def test_config_write_is_atomic_and_creates_parent(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.yml"
    original = Config(
        ldraw_library_path="/library/path",
        generated_path="/generated/path",
    )

    original.write(config_path)

    loaded = Config.load(config_path)
    assert loaded.ldraw_library_path == "/library/path"
    assert loaded.generated_path == "/generated/path"
    assert not config_path.with_name("config.yml.tmp").exists()


def test_config_write_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    original = Config(
        ldraw_library_path="/library/path",
        generated_path="/generated/path",
    )
    original.write(path)

    loaded = Config.load(path)

    assert loaded.ldraw_library_path == "/library/path"
    assert loaded.generated_path == "/generated/path"
    assert yaml.safe_load(path.read_text()) == {
        "ldraw_library_path": "/library/path",
        "generated_path": "/generated/path",
    }
