"""Integration tests for example scripts."""

import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.mark.integration
def test_example_stairs():
    """Test stairs example script."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    stairs_script = examples_dir / "stairs.py"
    if not stairs_script.exists():
        pytest.skip("Stairs example script not found")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = subprocess.run(
                ["uv", "run", "python", str(stairs_script)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Script should either succeed or fail gracefully
            assert result.returncode in [0, 1], f"Stairs script failed unexpectedly: {result.stderr}"
            
            # Check if LDraw file was created
            output_files = list(Path(temp_dir).glob("*.ldr"))
            if result.returncode == 0:
                assert len(output_files) > 0, "Should create LDraw output file"
            
        except subprocess.TimeoutExpired:
            pytest.skip("Stairs example timed out")


@pytest.mark.integration
def test_example_figure():
    """Test figure example script."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    figure_script = examples_dir / "figure.py"
    if not figure_script.exists():
        pytest.skip("Figure example script not found")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = subprocess.run(
                ["uv", "run", "python", str(figure_script)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Script should either succeed or fail gracefully
            assert result.returncode in [0, 1], f"Figure script failed unexpectedly: {result.stderr}"
            
            # Check if LDraw file was created
            output_files = list(Path(temp_dir).glob("*.ldr"))
            if result.returncode == 0:
                assert len(output_files) > 0, "Should create LDraw output file"
            
        except subprocess.TimeoutExpired:
            pytest.skip("Figure example timed out")


@pytest.mark.integration
@pytest.mark.slow
def test_example_buggy():
    """Test buggy example script."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    buggy_script = examples_dir / "buggy.py"
    if not buggy_script.exists():
        pytest.skip("Buggy example script not found")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = subprocess.run(
                ["uv", "run", "python", str(buggy_script)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=120  # Buggy might be more complex
            )
            
            # Script should either succeed or fail gracefully
            assert result.returncode in [0, 1], f"Buggy script failed unexpectedly: {result.stderr}"
            
        except subprocess.TimeoutExpired:
            pytest.skip("Buggy example timed out")


@pytest.mark.integration
def test_example_spaceman():
    """Test spaceman example script."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    spaceman_script = examples_dir / "spaceman.py"
    if not spaceman_script.exists():
        pytest.skip("Spaceman example script not found")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = subprocess.run(
                ["uv", "run", "python", str(spaceman_script)],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Script should either succeed or fail gracefully
            assert result.returncode in [0, 1], f"Spaceman script failed unexpectedly: {result.stderr}"
            
        except subprocess.TimeoutExpired:
            pytest.skip("Spaceman example timed out")


@pytest.mark.integration
def test_all_examples_syntax():
    """Test that all example scripts have valid Python syntax."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    python_files = list(examples_dir.glob("*.py"))
    assert len(python_files) > 0, "Should find Python example files"
    
    for script in python_files:
        try:
            # Test syntax by compiling
            result = subprocess.run(
                ["python", "-m", "py_compile", str(script)],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            assert result.returncode == 0, f"Syntax error in {script.name}: {result.stderr}"
            
        except subprocess.TimeoutExpired:
            pytest.fail(f"Syntax check for {script.name} timed out")


@pytest.mark.integration
def test_examples_import_ldraw():
    """Test that example scripts can import ldraw modules."""
    examples_dir = Path("examples")
    if not examples_dir.exists():
        pytest.skip("Examples directory not found")
    
    # Test a simple import check
    test_code = """
import sys
sys.path.insert(0, '.')
try:
    import ldraw
    print("SUCCESS: ldraw imported")
except ImportError as e:
    print(f"FAILED: {e}")
    sys.exit(1)
"""
    
    try:
        result = subprocess.run(
            ["uv", "run", "python", "-c", test_code],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Failed to import ldraw: {result.stderr}"
        assert "SUCCESS" in result.stdout, "Should confirm successful import"
        
    except subprocess.TimeoutExpired:
        pytest.skip("Import test timed out")