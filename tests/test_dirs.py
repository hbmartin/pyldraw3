"""Tests for platform directory helpers."""

from pathlib import Path

import pytest

from ldraw.dirs import get_cache_dir, get_config_dir, get_data_dir


def test_dirs_do_not_create_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    never = tmp_path / "never"

    def cache_dir(_name: str) -> str:
        return str(never / "cache")

    def config_dir(_name: str) -> str:
        return str(never / "config")

    def data_dir(_name: str) -> str:
        return str(never / "data")

    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_cache_dir",
        cache_dir,
    )
    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_config_dir",
        config_dir,
    )
    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_data_dir",
        data_dir,
    )

    assert get_cache_dir() == str(never / "cache")
    assert get_config_dir() == str(never / "config")
    assert get_data_dir() == str(never / "data")
    assert not never.exists()
