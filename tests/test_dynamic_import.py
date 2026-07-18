"""Tests for dynamic import functionality."""

import importlib
import importlib.util
import sys
import threading
import warnings
from pathlib import Path
from types import ModuleType

import pytest

from ldraw import LibraryImporter
from ldraw.config import Config
from ldraw.errors import (
    CouldNotFindModuleError,
    CouldNotLoadSpecError,
    StaleModuleSpecError,
)
from ldraw.imports import load_lib


@pytest.fixture
def generated_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    generated_path = tmp_path / "generated"
    library_path = generated_path / "library"
    library_path.mkdir(parents=True)
    (library_path / "__init__.py").write_text("__all__ = ['single', 'package']")

    config = Config(
        ldraw_library_path=str(tmp_path / "ldraw"),
        generated_path=str(generated_path),
    )
    # Equivalent to LibraryImporter.set_config(config), but monkeypatch
    # restores the previous default config on teardown.
    monkeypatch.setattr(LibraryImporter, "_default_config", config)
    LibraryImporter.clean()
    yield library_path
    LibraryImporter.clean()


def test_dynamic_import_single_py_module(generated_library: Path) -> None:
    (generated_library / "single.py").write_text("VALUE = 42")

    module = importlib.import_module("ldraw.library.single")

    assert module.VALUE == 42


def test_dynamic_import_package_init_module(generated_library: Path) -> None:
    package = generated_library / "package"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 'package'")

    module = importlib.import_module("ldraw.library.package")

    assert module.VALUE == "package"


def test_import_emits_no_import_warning(generated_library: Path) -> None:
    """The finder must use the modern loader protocol, not load_module()."""
    (generated_library / "single.py").write_text("VALUE = 42")

    with warnings.catch_warnings():
        warnings.simplefilter("error", ImportWarning)
        module = importlib.import_module("ldraw.library.single")

    assert module.VALUE == 42


def test_find_spec_returns_none_without_generated_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config(
        ldraw_library_path=str(tmp_path / "ldraw"),
        generated_path=str(tmp_path / "empty"),
    )
    importer = LibraryImporter(config)

    assert importer.find_spec("ldraw.library", None) is None
    assert importer.find_spec("ldraw.library.colours", None) is None

    monkeypatch.setattr(LibraryImporter, "_default_config", config)
    LibraryImporter.clean()
    assert importlib.util.find_spec("ldraw.library") is None
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ldraw.library")
    LibraryImporter.clean()


def test_missing_submodule_raises_could_not_find(generated_library: Path) -> None:
    with pytest.raises(CouldNotFindModuleError) as excinfo:
        importlib.import_module("ldraw.library.nonexistent")

    message = str(excinfo.value)
    assert "nonexistent/__init__.py" in message.replace("\\", "/")
    assert "nonexistent.py" in message


def test_importer_has_no_legacy_protocol() -> None:
    assert not hasattr(LibraryImporter, "load_module")
    assert not hasattr(LibraryImporter, "find_module")
    assert not hasattr(LibraryImporter, "get_code")


def test_load_lib_missing_module_raises(tmp_path: Path) -> None:
    with pytest.raises(CouldNotFindModuleError):
        load_lib(tmp_path, "ldraw.library.nonexistent")
    assert "ldraw.library.nonexistent" not in sys.modules


def test_load_lib_unloadable_spec_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "single.py").write_text("VALUE = 1")
    monkeypatch.setattr(
        "ldraw.imports.importlib.util.spec_from_file_location",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(CouldNotLoadSpecError):
        load_lib(tmp_path, "ldraw.library.single")
    assert "ldraw.library.single" not in sys.modules


def test_load_lib_exec_failure_rolls_back_sys_modules(tmp_path: Path) -> None:
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "broken.py").write_text("raise RuntimeError('boom')")

    with pytest.raises(RuntimeError, match="boom"):
        load_lib(tmp_path, "ldraw.library.broken")
    assert "ldraw.library.broken" not in sys.modules


def test_set_config_waits_for_inflight_import(
    generated_library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    clean_entered = threading.Event()
    gate_name = "_pyldraw_import_gate"
    gate = ModuleType(gate_name)
    gate.started = started
    gate.release = release
    sys.modules[gate_name] = gate
    (generated_library / "slow.py").write_text(
        f"from {gate_name} import release, started\n"
        "started.set()\n"
        "release.wait(timeout=5)\n"
        "VALUE = 42\n",
    )
    errors: list[Exception] = []

    def import_slow_module() -> None:
        try:
            importlib.import_module("ldraw.library.slow")
        except Exception as exc:  # noqa: BLE001 - surface thread failures
            errors.append(exc)

    config = Config(
        ldraw_library_path=str(generated_library.parent / "ldraw"),
        generated_path=str(generated_library.parent),
    )
    original_clean = LibraryImporter.clean

    def signaling_clean(
        cls: type[LibraryImporter],
        *,
        config: Config | None = None,
    ) -> None:
        assert cls is LibraryImporter
        clean_entered.set()
        original_clean(config=config)

    monkeypatch.setattr(LibraryImporter, "clean", classmethod(signaling_clean))
    import_thread = threading.Thread(target=import_slow_module)
    reconfigure_thread = threading.Thread(
        target=LibraryImporter.set_config,
        args=(config,),
    )
    try:
        import_thread.start()
        assert started.wait(timeout=5)
        reconfigure_thread.start()
        assert clean_entered.wait(timeout=5)
        reconfigure_thread.join(timeout=0.1)
        assert reconfigure_thread.is_alive()
    finally:
        release.set()
        import_thread.join(timeout=5)
        reconfigure_thread.join(timeout=5)
        sys.modules.pop(gate_name, None)

    assert not import_thread.is_alive()
    assert not reconfigure_thread.is_alive()
    assert errors == []
    assert "ldraw.library.slow" not in sys.modules


def test_stale_spec_is_rejected_after_reconfiguration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    for root, value in ((old_root, "old"), (new_root, "new")):
        library = root / "library"
        library.mkdir(parents=True)
        (library / "__init__.py").write_text("__all__ = ['stale']\n")
        (library / "stale.py").write_text(f"VALUE = {value!r}\n")

    old_config = Config(generated_path=str(old_root))
    new_config = Config(generated_path=str(new_root))
    monkeypatch.setattr(LibraryImporter, "_default_config", old_config)
    LibraryImporter.clean()

    fullname = "ldraw.library.stale"
    spec = LibraryImporter().find_spec(fullname)
    assert spec is not None
    assert isinstance(spec.loader, importlib.machinery.SourceFileLoader)
    stale_module = importlib.util.module_from_spec(spec)

    LibraryImporter.set_config(new_config)
    sys.modules[fullname] = stale_module
    try:
        with pytest.raises(StaleModuleSpecError, match="retry the import"):
            spec.loader.exec_module(stale_module)
    finally:
        sys.modules.pop(fullname, None)

    fresh_module = importlib.import_module(fullname)
    assert fresh_module.VALUE == "new"
    LibraryImporter.clean()
