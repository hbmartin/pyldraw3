"""Tests for public LDraw session and setup APIs."""

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest import MonkeyPatch

from ldraw.catalog import (
    CATALOG_SCHEMA_VERSION,
    catalog_db_path,
    parts_lst_md5,
    parts_tree_fingerprint,
)
from ldraw.catalog import save_catalog as catalog_save_catalog
from ldraw.config import Config
from ldraw.diagnostics import DiagnosticCode
from ldraw.generation import library_fingerprint, parse_library_fingerprint
from ldraw.generation.exceptions import (
    GeneratedModuleSyntaxError,
    UnwritableOutputError,
)
from ldraw.operations import CancellationToken, OperationCancelled
from ldraw.parts import PartCategory, Parts
from ldraw.progress import ProgressEvent, ProgressStage, ProgressUnit
from ldraw.session import (
    CatalogBuildOutcome,
    LDrawCapability,
    LDrawSession,
    LDrawStateReason,
    ensure_library,
    prepare_catalog,
)


def write_minimal_library(root: Path) -> Path:
    ldraw_dir = root / "ldraw"
    parts_dir = ldraw_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text(
        "0 Brick  2 x  4\n0 !CATEGORY Brick\n2 24 0 0 0 1 0 0\n",
    )
    (ldraw_dir / "parts.lst").write_text(
        "3001.dat                       Brick  2 x  4\n"
    )
    (ldraw_dir / "ldconfig.ldr").write_text(
        "0 !COLOUR Red CODE 4 VALUE #C91A09 EDGE #333333\n",
    )
    return ldraw_dir / "parts.lst"


def write_fresh_index(parts_lst: Path, generated_path: Path) -> None:
    parts = Parts(parts_lst)
    catalog_save_catalog(
        catalog_db_path(generated_path),
        md5=parts_lst_md5(parts_lst),
        catalog=parts.catalog,
        library_root=parts_lst.parent,
        tree_fingerprint=parts_tree_fingerprint(parts_lst.parent),
    )


def write_fresh_generation(parts_lst: Path, generated_path: Path) -> None:
    library = generated_path / "library"
    library.mkdir(parents=True)
    (library / "__hash__").write_text(library_fingerprint(parts_lst))


def test_session_none_config_loads_default(monkeypatch: MonkeyPatch) -> None:
    config = Config(ldraw_library_path="/library", generated_path="/generated")

    def fake_load() -> Config:
        return config

    monkeypatch.setattr("ldraw.session.Config.load", staticmethod(fake_load))

    assert LDrawSession(None).config is config


def test_session_state_reports_missing_library(tmp_path: Path) -> None:
    session = LDrawSession(
        Config(ldraw_library_path=str(tmp_path / "missing"), generated_path="/gen"),
    )

    state = session.state()

    assert not state.ready
    assert state.reasons == (LDrawStateReason.LIBRARY_MISSING,)
    assert not state.library_available


def test_session_state_reports_missing_index_and_generation(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "gen"),
        ),
    )

    state = session.state()

    assert state.reasons == (
        LDrawStateReason.INDEX_MISSING,
        LDrawStateReason.GENERATED_LIBRARY_MISSING,
    )
    assert state.needs_index_rebuild
    assert state.needs_generation


def test_session_state_reports_ready_and_paths(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    write_fresh_generation(parts_lst, generated_path)
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )

    state = session.state()

    assert state.ready
    assert state.reasons == ()
    assert session.paths.parts_lst == parts_lst
    assert session.paths.catalog_db == generated_path / "catalog.sqlite"
    assert session.paths.generation_hash == generated_path / "library" / "__hash__"


def test_session_state_reports_stale_and_unreadable_indexes(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    write_fresh_generation(parts_lst, generated_path)
    with (
        closing(sqlite3.connect(catalog_db_path(generated_path))) as connection,
        connection,
    ):
        connection.execute("PRAGMA user_version = 999")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )

    assert LDrawStateReason.INDEX_STALE in session.state().reasons

    catalog_db_path(generated_path).write_bytes(b"not sqlite")
    assert LDrawStateReason.INDEX_UNREADABLE in session.state().reasons


def test_session_state_reports_stale_generation(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    library = generated_path / "library"
    library.mkdir(parents=True)
    (library / "__hash__").write_text("old")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )

    assert LDrawStateReason.GENERATED_LIBRARY_STALE in session.state().reasons


def test_session_load_rebuild_index_and_open_model(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )
    model_path = tmp_path / "model.ldr"
    model_path.write_text("0 Model\n")

    assert session.load().get_entry_by_code("3001") is not None
    assert session.paths.catalog_db.is_file()
    session.paths.catalog_db.unlink()
    assert session.rebuild_index(force=True).get_entry_by_code("3001") is not None
    session.paths.catalog_db.write_bytes(b"not sqlite")
    assert session.rebuild_index(force=False).get_entry_by_code("3001") is not None
    assert session.open_model(model_path).description == "Model"


def test_rebuild_index_replaces_catalog_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    catalog_db = catalog_db_path(generated_path)
    with closing(sqlite3.connect(catalog_db)) as connection, connection:
        connection.execute("PRAGMA user_version = 999")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )
    observed_db_names: list[str] = []

    def fake_save_catalog(db_path, **_kwargs) -> None:
        observed_db_names.append(db_path.name)
        db_path.write_text("new catalog")

    monkeypatch.setattr("ldraw.session.save_catalog", fake_save_catalog)

    assert session.rebuild_index(force=False).get_entry_by_code("3001") is not None

    assert len(observed_db_names) == 1
    assert observed_db_names[0].startswith(".catalog.sqlite.")
    assert observed_db_names[0].endswith(".tmp")
    assert catalog_db.read_text() == "new catalog"
    assert list(generated_path.glob(".catalog.sqlite.*.tmp")) == []


def test_session_state_reads_catalog_with_file_uri(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated path"
    catalog_db = catalog_db_path(generated_path)
    catalog_db.parent.mkdir(parents=True)
    catalog_db.write_text("placeholder")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )
    captured: dict[str, object] = {}

    def fake_connect(database: str, *, uri: bool) -> SimpleNamespace:
        captured["database"] = database
        captured["uri"] = uri

        def execute(statement: str) -> SimpleNamespace:
            if statement == "PRAGMA user_version":
                return SimpleNamespace(fetchone=lambda: (CATALOG_SCHEMA_VERSION,))
            if statement == "SELECT value FROM meta WHERE key = 'parts_lst_md5'":
                return SimpleNamespace(fetchone=lambda: (parts_lst_md5(parts_lst),))
            if statement == "SELECT value FROM meta WHERE key = 'tree_fingerprint'":
                return SimpleNamespace(
                    fetchone=lambda: (parts_tree_fingerprint(parts_lst.parent),),
                )
            raise AssertionError(statement)

        return SimpleNamespace(
            execute=execute,
            close=lambda: captured.setdefault("closed", True),
        )

    monkeypatch.setattr("ldraw.session.sqlite3.connect", fake_connect)

    state = session.state()

    assert LDrawStateReason.INDEX_UNREADABLE not in state.reasons
    assert captured["uri"] is True
    assert captured["closed"] is True
    database = captured["database"]
    assert isinstance(database, str)
    assert database.startswith("file://")
    assert "%20" in database
    assert database.endswith("?mode=ro")


def test_ensure_library_downloads_generates_rebuilds_and_writes_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache = tmp_path / "cache"
    config = Config(
        ldraw_library_path=str(tmp_path / "missing"),
        generated_path=str(tmp_path / "generated"),
    )
    written: list[Path | str | None] = []
    events: list[ProgressEvent] = []
    calls: list[str] = []

    def fake_download(
        *, version, show_progress, on_progress, resume, cancellation
    ) -> str:
        calls.append(f"download:{version}:{show_progress}")
        parts_lst = write_minimal_library(cache / version)
        if on_progress is not None:
            on_progress(
                ProgressEvent(ProgressStage.DOWNLOAD, "downloaded", path=parts_lst)
            )
        return "2099-01"

    def fake_generate(*, config, force, on_progress, fingerprint, cancellation) -> None:
        calls.append(f"generate:{force}")
        parts_lst = Path(config.ldraw_library_path) / "ldraw" / "parts.lst"
        write_fresh_generation(parts_lst, Path(config.generated_path))
        if on_progress is not None:
            on_progress(
                ProgressEvent(
                    ProgressStage.LIBRARY_GENERATION,
                    "generated",
                    path=Path(config.generated_path),
                ),
            )

    def fake_write(*, config_file=None) -> None:
        written.append(config_file)

    monkeypatch.setattr("ldraw.session.cache_ldraw", cache)
    monkeypatch.setattr("ldraw.session.download_library", fake_download)
    monkeypatch.setattr("ldraw.session.generate_library", fake_generate)
    config.write = fake_write

    session = ensure_library(
        config,
        write_config=True,
        config_file=tmp_path / "config.yml",
        on_progress=events.append,
    )

    assert calls == ["download:complete:False", "generate:False"]
    assert config.ldraw_library_path == str(cache / "complete")
    assert written == [tmp_path / "config.yml"]
    assert session.state().ready
    stages = [event.stage for event in events]
    assert stages[0] is ProgressStage.DOWNLOAD
    assert ProgressStage.FINGERPRINT in stages
    assert ProgressStage.LIBRARY_GENERATION in stages
    assert ProgressStage.INDEX_REBUILD in stages
    assert stages[-1] is ProgressStage.DONE


def test_ensure_library_does_not_write_config_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    write_fresh_generation(parts_lst, generated_path)
    config = Config(
        ldraw_library_path=str(parts_lst.parents[1]),
        generated_path=str(generated_path),
    )
    written: list[Path | str | None] = []
    config.write = lambda *, config_file=None: written.append(config_file)
    set_configs = []
    monkeypatch.setattr("ldraw.session.LibraryImporter.set_config", set_configs.append)

    assert ensure_library(config).config is config

    assert written == []
    assert set_configs == [config]


def test_ensure_library_wraps_latest_version_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ldraw.errors import CouldNotDetermineLatestVersionError

    config = Config(
        ldraw_library_path=str(tmp_path / "missing"),
        generated_path=str(tmp_path / "generated"),
    )

    def failing_download(**_kwargs) -> str:
        raise CouldNotDetermineLatestVersionError

    monkeypatch.setattr("ldraw.session.download_library", failing_download)

    with pytest.raises(RuntimeError, match="Could not download"):
        ensure_library(config)


def test_ensure_library_wraps_oserror(tmp_path: Path, monkeypatch) -> None:
    config = Config(
        ldraw_library_path=str(tmp_path / "missing"),
        generated_path=str(tmp_path / "generated"),
    )

    def failing_download(**_kwargs) -> str:
        message = "disk full"
        raise OSError(message)

    monkeypatch.setattr("ldraw.session.download_library", failing_download)

    with pytest.raises(RuntimeError, match="disk full"):
        ensure_library(config)


def test_prepare_catalog_reports_missing_library_and_empty_capabilities(
    tmp_path: Path,
) -> None:
    config = Config(
        ldraw_library_path=str(tmp_path / "missing"),
        generated_path=str(tmp_path / "generated"),
    )
    session = LDrawSession(config)

    result = prepare_catalog(config)

    assert result.complete is False
    assert result.parts is None
    assert result.report.outcome is CatalogBuildOutcome.UNAVAILABLE
    assert result.report.fingerprint is None
    assert result.final_state == result.initial_state
    with pytest.raises(FileNotFoundError):
        session.load()
    with pytest.raises(ValueError, match="at least one"):
        session.prepare_catalog(capabilities=())


def test_prepare_catalog_generated_only_reports_generation_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    config = Config(
        ldraw_library_path=str(parts_lst.parents[1]),
        generated_path=str(tmp_path / "generated"),
    )
    generation_error = OSError("generator failed")

    def failing_generate(**_kwargs) -> None:
        raise generation_error

    monkeypatch.setattr("ldraw.session.generate_library", failing_generate)

    result = LDrawSession(config).prepare_catalog(
        capabilities=(LDrawCapability.GENERATED_MODULES,),
    )

    assert result.complete is False
    assert result.parts is not None
    assert result.report.outcome is CatalogBuildOutcome.LOADED
    assert result.report.entry_count == 1
    assert result.report.persisted is False
    assert "generator failed" in result.diagnostics[0].message


def test_prepare_catalog_returns_parts_when_index_cannot_be_persisted(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )
    persistence_error = sqlite3.OperationalError("read only")

    def failing_persist(**_kwargs) -> None:
        raise persistence_error

    monkeypatch.setattr("ldraw.session._persist_catalog_atomically", failing_persist)

    result = session.prepare_catalog()

    assert result.complete is True
    assert result.parts is not None
    assert result.report.outcome is CatalogBuildOutcome.REBUILT_NOT_PERSISTED
    assert result.report.persisted is False
    assert result.diagnostics[0].severity.value == "warning"


def test_prepare_catalog_returns_parts_when_index_directory_cannot_be_created(
    tmp_path: Path,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    generated_path.write_text("not a directory", encoding="utf-8")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )

    result = session.prepare_catalog()

    assert result.complete is True
    assert result.parts is not None
    assert result.parts.get_entry_by_code("3001") is not None
    assert result.report.outcome is CatalogBuildOutcome.REBUILT_NOT_PERSISTED
    assert result.report.persisted is False
    assert result.diagnostics[0].code is DiagnosticCode.CATALOG_PERSIST_FAILED
    assert result.diagnostics[0].path == generated_path / "catalog.sqlite"


def test_session_uses_existing_index_and_structured_model_loader(
    tmp_path: Path,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )
    model_path = tmp_path / "model.ldr"
    model_path.write_text("0 Model\ninvalid\n", encoding="utf-8")

    assert session.rebuild_index(force=False).get_entry_by_code("3001") is not None
    loaded = session.load_model(model_path)
    assert loaded.model is not None
    assert loaded.complete is False


def test_session_reports_connection_and_generation_hash_read_failures(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    write_fresh_generation(parts_lst, generated_path)
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )

    monkeypatch.setattr(
        "ldraw.session.sqlite3.connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.Error("no database")),
    )
    assert session.state(
        capabilities=(LDrawCapability.CATALOG,),
    ).reasons == (LDrawStateReason.INDEX_UNREADABLE,)

    original_read_text = Path.read_text
    hash_error = OSError("unreadable hash")

    def failing_hash_read(path: Path, *args, **kwargs) -> str:
        if path.name == "__hash__":
            raise hash_error
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", failing_hash_read)
    generated_state = session.state(
        capabilities=(LDrawCapability.GENERATED_MODULES,),
    )
    assert generated_state.reasons == (LDrawStateReason.GENERATED_LIBRARY_UNREADABLE,)


def test_ensure_library_wraps_forced_generation_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    config = Config(
        ldraw_library_path=str(parts_lst.parents[1]),
        generated_path=str(tmp_path / "generated"),
    )

    def failing_generate(**_kwargs) -> None:
        raise UnwritableOutputError(config.generated_path)

    monkeypatch.setattr("ldraw.session.generate_library", failing_generate)

    with pytest.raises(RuntimeError, match="unwritable"):
        ensure_library(config, force_generate=True)


def test_operation_cancelled_is_not_a_runtime_error() -> None:
    assert issubclass(OperationCancelled, Exception)
    assert not issubclass(OperationCancelled, RuntimeError)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        token.raise_if_cancelled()


def test_state_rejects_empty_capabilities_and_accepts_generators(
    tmp_path: Path,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )

    with pytest.raises(ValueError, match="at least one"):
        session.state(capabilities=())

    state = session.state(
        capabilities=(capability for capability in (LDrawCapability.CATALOG,)),
    )
    assert state.capabilities == frozenset({LDrawCapability.CATALOG})


def test_prepare_catalog_reports_rebuilt_and_state_transition(tmp_path: Path) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )

    result = session.prepare_catalog()

    assert result.complete is True
    assert result.report.outcome is CatalogBuildOutcome.REBUILT
    assert result.report.persisted is True
    assert result.report.entry_count == 1
    assert result.initial_state.needs_index_rebuild is True
    assert result.initial_state.ready is False
    assert result.final_state.ready is True
    assert result.initial_state.capabilities == frozenset({LDrawCapability.CATALOG})
    assert result.final_state.capabilities == frozenset({LDrawCapability.CATALOG})


def test_prepare_catalog_rebuild_recategorizes_after_in_place_dat_edit(
    tmp_path: Path,
) -> None:
    """An in-place .dat header edit must never persist a stale catalog."""
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )
    first = session.prepare_catalog()
    assert first.parts is not None
    assert first.parts.get_entry_by_code("3001").category is PartCategory.BRICK

    dat = parts_lst.parent / "parts" / "3001.dat"
    dat.write_text(dat.read_text().replace("!CATEGORY Brick", "!CATEGORY Tile"))

    second = session.prepare_catalog()

    assert second.report.outcome is CatalogBuildOutcome.REBUILT
    assert second.report.persisted is True
    assert second.parts is not None
    assert second.parts.get_entry_by_code("3001").category is PartCategory.TILE
    with closing(sqlite3.connect(session.paths.catalog_db)) as connection:
        row = connection.execute(
            "SELECT category FROM parts WHERE code = '3001'",
        ).fetchone()
    assert row == (PartCategory.TILE.value,)


def test_rebuild_index_force_recategorizes_after_in_place_dat_edit(
    tmp_path: Path,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(tmp_path / "generated"),
        ),
    )
    assert session.load().get_entry_by_code("3001").category is PartCategory.BRICK

    dat = parts_lst.parent / "parts" / "3001.dat"
    dat.write_text(dat.read_text().replace("!CATEGORY Brick", "!CATEGORY Tile"))

    parts = session.rebuild_index(force=True)

    assert parts.get_entry_by_code("3001").category is PartCategory.TILE
    with closing(sqlite3.connect(session.paths.catalog_db)) as connection:
        row = connection.execute(
            "SELECT category FROM parts WHERE code = '3001'",
        ).fetchone()
    assert row == (PartCategory.TILE.value,)


def test_prepare_catalog_cancel_between_save_and_replace_cleans_temp(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )
    token = CancellationToken()

    def cancelling_save(db_path: Path, **_kwargs: object) -> None:
        db_path.write_text("catalog data")
        token.cancel()

    monkeypatch.setattr("ldraw.session.save_catalog", cancelling_save)

    with pytest.raises(OperationCancelled):
        session.prepare_catalog(cancellation=token)

    assert not (generated_path / "catalog.sqlite").exists()
    assert list(generated_path.glob(".catalog.sqlite.*.tmp")) == []


def test_prepare_catalog_reports_generator_bug_and_failure_done_event(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    config = Config(
        ldraw_library_path=str(parts_lst.parents[1]),
        generated_path=str(tmp_path / "generated"),
    )
    error = GeneratedModuleSyntaxError(str(tmp_path / "generated" / "broken.py"))

    def failing_generate(**_kwargs: object) -> None:
        raise error

    monkeypatch.setattr("ldraw.session.generate_library", failing_generate)
    events: list[ProgressEvent] = []

    result = LDrawSession(config).prepare_catalog(
        capabilities=(LDrawCapability.GENERATED_MODULES,),
        on_progress=events.append,
    )

    assert result.complete is False
    assert result.diagnostics[0].code is DiagnosticCode.GENERATION_FAILED
    assert "does not compile" in result.diagnostics[0].message
    assert events[-1].stage is ProgressStage.DONE
    assert events[-1].message == "LDraw data preparation failed"


def test_prepare_catalog_missing_library_emits_terminal_done_event(
    tmp_path: Path,
) -> None:
    config = Config(
        ldraw_library_path=str(tmp_path / "missing"),
        generated_path=str(tmp_path / "generated"),
    )
    events: list[ProgressEvent] = []

    result = LDrawSession(config).prepare_catalog(on_progress=events.append)

    assert result.parts is None
    assert events
    assert events[-1].stage is ProgressStage.DONE
    assert "missing" in events[-1].message


def test_prepare_catalog_rebuilds_when_fresh_index_read_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A fresh-looking index that fails to load must be rebuilt, not faked."""
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    session = LDrawSession(
        Config(
            ldraw_library_path=str(parts_lst.parents[1]),
            generated_path=str(generated_path),
        ),
    )
    monkeypatch.setattr("ldraw.session.load_catalog", lambda *_args, **_kwargs: None)

    result = session.prepare_catalog()

    assert result.initial_state.needs_index_rebuild is False
    assert result.report.outcome is CatalogBuildOutcome.REBUILT
    assert result.report.persisted is True
    assert result.parts is not None
    assert result.report.entry_count == 1


def test_ensure_library_walks_parts_tree_once(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    generated_path = tmp_path / "generated"
    write_fresh_index(parts_lst, generated_path)
    write_fresh_generation(parts_lst, generated_path)
    config = Config(
        ldraw_library_path=str(parts_lst.parents[1]),
        generated_path=str(generated_path),
    )
    expected_generation_fingerprint = library_fingerprint(parts_lst)
    monkeypatch.setattr("ldraw.session.LibraryImporter.set_config", lambda _cfg: None)

    import ldraw.catalog

    original = ldraw.catalog.parts_tree_fingerprint
    calls = {"count": 0}

    def counting(ldraw_dir: Path, **kwargs: object) -> str:
        calls["count"] += 1
        return original(ldraw_dir, **kwargs)

    monkeypatch.setattr("ldraw.catalog.parts_tree_fingerprint", counting)
    monkeypatch.setattr("ldraw.generation.parts_tree_fingerprint", counting)
    forced_fingerprints: list[str | None] = []

    def fake_generate(
        *,
        config: Config,
        force: bool,
        on_progress: object,
        fingerprint: str | None,
        cancellation: object,
    ) -> None:
        forced_fingerprints.append(fingerprint)

    monkeypatch.setattr("ldraw.session.generate_library", fake_generate)

    ensure_library(config, force_generate=True)

    assert calls["count"] == 1
    assert forced_fingerprints == [expected_generation_fingerprint]


def test_progress_event_determinate_and_units() -> None:
    determinate = ProgressEvent(
        stage=ProgressStage.DOWNLOAD,
        message="Downloading",
        current=1,
        total=2,
        unit=ProgressUnit.BYTES,
    )
    assert determinate.determinate is True
    assert ProgressEvent(stage=ProgressStage.DONE, message="done").determinate is False
    missing_unit = ProgressEvent(
        stage=ProgressStage.DOWNLOAD,
        message="Downloading",
        current=1,
        total=2,
    )
    assert missing_unit.determinate is False
    assert [unit.value for unit in ProgressUnit] == [
        "bytes",
        "files",
        "parts",
        "steps",
        "views",
    ]


def test_parse_library_fingerprint_round_trips_and_rejects_malformed(
    tmp_path: Path,
) -> None:
    parts_lst = write_minimal_library(tmp_path / "library")
    serialized = library_fingerprint(parts_lst)

    fields = parse_library_fingerprint(serialized)

    assert fields.parts_lst_md5 == parts_lst_md5(parts_lst)
    assert fields.tree_fingerprint == parts_tree_fingerprint(parts_lst.parent)
    with pytest.raises(ValueError, match="malformed library fingerprint"):
        parse_library_fingerprint("only-one-line")
