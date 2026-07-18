"""Integration tests for CLI functionality."""

import os
import subprocess
from pathlib import Path

import pytest

NETWORK_ERROR_MARKERS = (
    "connectionerror",
    "connection refused",
    "connection reset",
    "temporary failure in name resolution",
    "max retries exceeded",
    "getaddrinfo",
    "timed out",
)


@pytest.mark.integration
def test_cli_download_command() -> None:
    """Test CLI download command."""
    # Test help
    result = subprocess.run(
        ["uv", "run", "ldraw", "download", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Download help failed: {result.stderr}"
    assert "download" in result.stdout.lower()


@pytest.mark.integration
def test_cli_generate_command() -> None:
    """Test CLI generate command."""
    # Test help
    result = subprocess.run(
        ["uv", "run", "ldraw", "generate", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Generate help failed: {result.stderr}"
    assert "generate" in result.stdout.lower()


@pytest.mark.integration
@pytest.mark.parametrize("command", ["parts", "validate", "bom", "stubs"])
def test_cli_new_command_help(command: str) -> None:
    """Test help for the parts, validate, bom, and stubs commands."""
    result = subprocess.run(
        ["uv", "run", "ldraw", command, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"{command} help failed: {result.stderr}"
    assert command in result.stdout.lower()


@pytest.mark.integration
def test_cli_config_command() -> None:
    """Test CLI config command."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "config"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Config command failed: {result.stderr}"
    # Should show configuration information
    assert len(result.stdout.strip()) > 0, "Config should output information"


@pytest.mark.integration
def test_cli_version_command() -> None:
    """Test CLI version command."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Version command failed: {result.stderr}"
    # Should show version information
    assert len(result.stdout.strip()) > 0, "Version should output information"


@pytest.mark.integration
def test_cli_main_help() -> None:
    """Test main CLI help."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Main help failed: {result.stderr}"
    assert "ldraw" in result.stdout.lower()
    assert "command" in result.stdout.lower()


@pytest.mark.integration
def test_cli_no_args() -> None:
    """Test CLI with no arguments prints help and exits cleanly."""
    result = subprocess.run(
        ["uv", "run", "ldraw"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Bare invocation failed: {result.stderr}"
    assert "usage" in result.stdout


@pytest.mark.integration
@pytest.mark.slow
def test_cli_full_workflow(tmp_path: Path) -> None:
    """Download a pinned release, then generate, in an isolated XDG home.

    Skips only when the network is genuinely unavailable; any other
    download failure, and any generate failure at all, is a real bug.
    (XDG variables are honored by platformdirs on the Linux CI runners;
    on macOS they are ignored and the real cache is used instead, which
    is behaviorally identical.)
    """
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    try:
        download = subprocess.run(
            ["uv", "run", "ldraw", "download", "--version", "2018-02", "--yes"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("network too slow: download timed out")
    if download.returncode != 0:
        blob = (download.stderr + download.stdout).lower()
        if any(marker in blob for marker in NETWORK_ERROR_MARKERS):
            pytest.skip(f"network unavailable: {download.stderr.strip()}")
        pytest.fail(f"download failed (not a network error): {download.stderr}")

    generate = subprocess.run(
        ["uv", "run", "ldraw", "generate", "--yes"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert generate.returncode == 0, f"generate failed: {generate.stderr}"
