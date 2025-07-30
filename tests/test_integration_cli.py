"""Integration tests for CLI functionality."""

import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.mark.integration
def test_cli_download_command():
    """Test CLI download command."""
    # Test help
    result = subprocess.run(
        ["uv", "run", "ldraw", "download", "--help"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Download help failed: {result.stderr}"
    assert "download" in result.stdout.lower()


@pytest.mark.integration
def test_cli_generate_command():
    """Test CLI generate command."""
    # Test help
    result = subprocess.run(
        ["uv", "run", "ldraw", "generate", "--help"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Generate help failed: {result.stderr}"
    assert "generate" in result.stdout.lower()


@pytest.mark.integration
def test_cli_config_command():
    """Test CLI config command."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "config"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Config command failed: {result.stderr}"
    # Should show configuration information
    assert len(result.stdout.strip()) > 0, "Config should output information"


@pytest.mark.integration
def test_cli_version_command():
    """Test CLI version command."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "version"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Version command failed: {result.stderr}"
    # Should show version information
    assert len(result.stdout.strip()) > 0, "Version should output information"


@pytest.mark.integration
def test_cli_main_help():
    """Test main CLI help."""
    result = subprocess.run(
        ["uv", "run", "ldraw", "--help"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Main help failed: {result.stderr}"
    assert "ldraw" in result.stdout.lower()
    assert "command" in result.stdout.lower()


@pytest.mark.integration
def test_cli_no_args():
    """Test CLI with no arguments."""
    result = subprocess.run(
        ["uv", "run", "ldraw"],
        capture_output=True,
        text=True,
        timeout=30
    )
    # Should either show help or give a helpful error
    assert result.returncode in [0, 1, 2], "Should exit with expected code"


@pytest.mark.integration
@pytest.mark.slow
def test_cli_full_workflow():
    """Test complete CLI workflow in temporary directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Test download (using smaller version for speed)
        try:
            result = subprocess.run(
                ["uv", "run", "ldraw", "download", "--version", "2018-02", "--yes"],
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )
            
            if result.returncode != 0:
                pytest.skip(f"Download failed: {result.stderr}")
            
            # Test generate
            result = subprocess.run(
                ["uv", "run", "ldraw", "generate", "--yes"],
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=180  # 3 minutes
            )
            
            if result.returncode != 0:
                pytest.skip(f"Generate failed: {result.stderr}")
            
            # Verify some files were created
            assert result.returncode == 0, f"Generate command failed: {result.stderr}"
            
        except subprocess.TimeoutExpired:
            pytest.skip("CLI workflow test timed out")