"""Tests for platform directory helpers."""

from pathlib import Path

import pytest

from ldraw.dirs import get_cache_dir, get_config_dir, get_data_dir


def test_dirs_do_not_create_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    never = tmp_path / "never"
    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_cache_dir",
        lambda _name: str(never / "cache"),
    )
    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_config_dir",
        lambda _name: str(never / "config"),
    )
    monkeypatch.setattr(
        "ldraw.dirs.platformdirs.user_data_dir",
        lambda _name: str(never / "data"),
    )

    assert get_cache_dir() == str(never / "cache")
    assert get_config_dir() == str(never / "config")
    assert get_data_dir() == str(never / "data")
    assert not never.exists()
