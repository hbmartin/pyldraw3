"""Fresh-process import order checks for deferred service boundaries."""

import subprocess
import sys
from textwrap import dedent

import pytest


@pytest.mark.parametrize(
    "first_module",
    [
        "ldraw._connection_results",
        "ldraw._connection_sources",
        "ldraw._connection_parser",
        "ldraw._connection_reporting",
        "ldraw.connection_metadata",
    ],
)
def test_connection_import_orders_preserve_result_identity(first_module: str) -> None:
    source = dedent(f"""
        from importlib import import_module
        import sys
        import_module({first_module!r})
        if {first_module!r} == "ldraw._connection_results":
            assert "ldraw.connection_metadata" not in sys.modules
            assert "ldraw._connection_sources" not in sys.modules
            assert "ldraw._connection_parser" not in sys.modules
            assert "ldraw._connection_reporting" not in sys.modules
        from ldraw import connection_metadata as public
        from ldraw import _connection_results as internal
        from ldraw._connection_reporting import metadata_report
        assert public.ShadowConnectionResult is internal.ShadowConnectionResult
        assert public.ConnectionMetadataReport is internal.ConnectionMetadataReport
        assert public.ConnectionMetadataCoverage is internal.ConnectionMetadataCoverage
        result = public.parse_ldcad_text("3001", "0 !LDCAD SNAP_CLEAR")
        assert isinstance(result, public.ShadowConnectionResult)
        assert result.clear_all
        report = metadata_report("3001", features=(), result=result)
        assert isinstance(report, public.ConnectionMetadataReport)
    """)
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True)


def test_legacy_cli_imports_use_the_current_handlers() -> None:
    source = dedent("""
        from unittest.mock import patch
        from ldraw.cli import download_command, instructions_inspect_command, main
        from ldraw.cli._download import download_command as download_handler
        from ldraw.cli import _instructions
        assert download_command is download_handler
        inspect_handler = _instructions.instructions_inspect_command
        assert instructions_inspect_command is inspect_handler
        mocked = patch(
            "ldraw.cli._download.do_download", side_effect=ValueError("test sentinel")
        )
        with mocked as download_mock:
            assert main(["download", "--yes"]) == 1
            download_mock.assert_called_once()
    """)
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True)


def test_shared_constants_do_not_import_runtime_services() -> None:
    source = dedent("""
        import sys
        from ldraw._constants import COMPLETE_VERSION, DEFAULT_PAGE_MARKER_PREFIX
        assert COMPLETE_VERSION == "complete"
        assert DEFAULT_PAGE_MARKER_PREFIX == "// PDF_PAGE "
        assert "ldraw.downloads" not in sys.modules
        assert "ldraw.inspection" not in sys.modules
        assert "numpy" not in sys.modules
    """)
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True)
