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
from ldraw.generation import library_fingerprint
from ldraw.generation.exceptions import UnwritableOutputError
from ldraw.parts import Parts
from ldraw.progress import ProgressEvent, ProgressStage
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
