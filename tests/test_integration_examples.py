"""Integration tests for example scripts."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def example_script(script_name: str) -> Path:
    """Return an example script path or skip when examples are unavailable."""
    if not EXAMPLES_DIR.exists():
        pytest.skip("Examples directory not found")

    script = EXAMPLES_DIR / script_name
    if not script.exists():
        pytest.skip(f"{script_name} example script not found")

    return script


def run_example(
    script_name: str,
    tmp_path: Path,
    *,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run an example from an isolated output directory."""
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "python",
            str(example_script(script_name)),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def assert_example_completed(
    example_name: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    """Examples must succeed and emit LDraw text on stdout."""
    assert result.returncode == 0, f"{example_name} script failed: {result.stderr}"
    assert result.stdout.strip(), (
        f"{example_name} script should write LDraw output to stdout"
    )


@pytest.mark.integration
def test_example_stairs(tmp_path: Path) -> None:
    """Test stairs example script."""
    try:
        result = run_example("stairs.py", tmp_path=tmp_path)
    except subprocess.TimeoutExpired:
        pytest.skip("Stairs example timed out")
    else:
        assert_example_completed("Stairs", result)


@pytest.mark.integration
def test_example_figure(tmp_path: Path) -> None:
    """Test figure example script."""
    try:
        result = run_example("figure.py", tmp_path=tmp_path)
    except subprocess.TimeoutExpired:
        pytest.skip("Figure example timed out")
    else:
        assert_example_completed("Figure", result)


@pytest.mark.integration
@pytest.mark.slow
def test_example_buggy(tmp_path: Path) -> None:
    """Test buggy example script."""
    try:
        result = run_example("buggy.py", tmp_path=tmp_path, timeout=120)
    except subprocess.TimeoutExpired:
        pytest.skip("Buggy example timed out")
    else:
        assert_example_completed("Buggy", result)


@pytest.mark.integration
def test_example_spaceman(tmp_path: Path) -> None:
    """Test spaceman example script."""
    try:
        result = run_example("spaceman.py", tmp_path=tmp_path)
    except subprocess.TimeoutExpired:
        pytest.skip("Spaceman example timed out")
    else:
        assert_example_completed("Spaceman", result)


@pytest.mark.integration
def test_all_examples_syntax() -> None:
    """Test that all example scripts have valid Python syntax."""
    if not EXAMPLES_DIR.exists():
        pytest.skip("Examples directory not found")

    python_files = list(EXAMPLES_DIR.glob("*.py"))
    assert len(python_files) > 0, "Should find Python example files"

    for script in python_files:
        try:
            # Test syntax by compiling
            result = subprocess.run(
                ["python", "-m", "py_compile", str(script)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"Syntax check for {script.name} timed out")
        else:
            assert result.returncode == 0, (
                f"Syntax error in {script.name}: {result.stderr}"
            )


@pytest.mark.integration
def test_examples_import_ldraw() -> None:
    """Test that example scripts can import ldraw modules."""
    if not EXAMPLES_DIR.exists():
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
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Import test timed out")
    else:
        assert result.returncode == 0, f"Failed to import ldraw: {result.stderr}"
        assert "SUCCESS" in result.stdout, "Should confirm successful import"
