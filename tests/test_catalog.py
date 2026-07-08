"""Tests for the persistent SQLite parts index."""

import sqlite3
from pathlib import Path

import pytest

from ldraw.catalog import (
    CATALOG_SCHEMA_VERSION,
    catalog_db_path,
    load_catalog,
    load_parts,
    parts_lst_md5,
    save_catalog,
)
from ldraw.parts import CatalogEntry, PartCategory, Parts, PartsCatalog

PARTS_LST = Path("tests/test_ldraw2/ldraw/parts.lst")
LIBRARY_ROOT = PARTS_LST.parent


@pytest.fixture
def slow_catalog() -> PartsCatalog:
    return Parts(PARTS_LST).catalog


def entry_key(entry: CatalogEntry) -> tuple:
    return (
        entry.code,
        entry.description,
        entry.category,
        entry.minifig_section,
        str(entry.part.path) if entry.part is not None else None,
        entry.keywords,
    )


def test_save_load_round_trip_matches_slow_path(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)

    save_catalog(db_path, md5=md5, catalog=slow_catalog, library_root=LIBRARY_ROOT)
    loaded = load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT)

    assert loaded is not None
    assert list(loaded.by_code) == list(slow_catalog.by_code)
    for code, entry in slow_catalog.by_code.items():
        assert entry_key(loaded.by_code[code]) == entry_key(entry)
    assert {s: len(e) for s, e in loaded.by_minifig_section.items()} == {
        s: len(e) for s, e in slow_catalog.by_minifig_section.items()
    }
    assert loaded.module_sections() == slow_catalog.module_sections()


def test_load_catalog_missing_file_returns_none(tmp_path) -> None:
    assert (
        load_catalog(tmp_path / "nope.sqlite", md5="x", library_root=LIBRARY_ROOT)
        is None
    )


def test_load_catalog_stale_md5_returns_none(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    save_catalog(db_path, md5="old", catalog=slow_catalog, library_root=LIBRARY_ROOT)

    assert load_catalog(db_path, md5="new", library_root=LIBRARY_ROOT) is None


def test_load_catalog_wrong_schema_version_returns_none(
    tmp_path,
    slow_catalog,
) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(db_path, md5=md5, catalog=slow_catalog, library_root=LIBRARY_ROOT)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION + 1}")

    assert load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT) is None


def test_fresh_catalog_entries_carry_keywords(slow_catalog) -> None:
    keywords = slow_catalog.by_code["3959"].keywords
    assert keywords[:3] == ("Space", "Castle", "Pirates")
    assert "female stud" in keywords  # from a second !KEYWORDS line


def test_keywords_round_trip_through_index(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)

    save_catalog(db_path, md5=md5, catalog=slow_catalog, library_root=LIBRARY_ROOT)
    loaded = load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT)

    assert loaded is not None
    assert loaded.by_code["3959"].keywords == slow_catalog.by_code["3959"].keywords
    assert loaded.by_code["3959"].keywords != ()


def test_load_catalog_v1_schema_returns_none(tmp_path) -> None:
    """An old v1 index (no keywords column) must trigger a rebuild, not crash."""
    db_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        )
        connection.execute(
            "CREATE TABLE parts (code TEXT PRIMARY KEY, description TEXT NOT NULL,"
            " category TEXT NOT NULL, minifig_section TEXT, path TEXT)",
        )
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('parts_lst_md5', 'x')",
        )

    assert load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT) is None


def test_load_catalog_corrupt_file_returns_none(tmp_path) -> None:
    db_path = tmp_path / "catalog.sqlite"
    db_path.write_bytes(b"this is not a sqlite database at all")

    assert load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT) is None


def test_load_catalog_unknown_category_returns_none(tmp_path, slow_catalog) -> None:
    db_path = tmp_path / "catalog.sqlite"
    md5 = parts_lst_md5(PARTS_LST)
    save_catalog(db_path, md5=md5, catalog=slow_catalog, library_root=LIBRARY_ROOT)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE parts SET category = 'duplo'")

    assert load_catalog(db_path, md5=md5, library_root=LIBRARY_ROOT) is None


def test_paths_outside_library_root_stay_absolute(tmp_path) -> None:
    from ldraw.part import Part

    outside = tmp_path / "elsewhere" / "3001.dat"
    outside.parent.mkdir()
    outside.write_text("0 Brick\n")
    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(
            code="3001",
            description="Brick",
            category=PartCategory.BRICK,
            part=Part(outside),
        ),
    )
    db_path = tmp_path / "catalog.sqlite"

    save_catalog(db_path, md5="x", catalog=catalog, library_root=LIBRARY_ROOT)
    loaded = load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT)

    assert loaded is not None
    assert loaded.by_code["3001"].part.path == outside


def test_save_catalog_handles_entries_without_part(tmp_path) -> None:
    catalog = PartsCatalog()
    catalog.add(
        CatalogEntry(code="3001", description="Brick", category=PartCategory.BRICK),
    )
    db_path = tmp_path / "catalog.sqlite"

    save_catalog(db_path, md5="x", catalog=catalog, library_root=LIBRARY_ROOT)
    loaded = load_catalog(db_path, md5="x", library_root=LIBRARY_ROOT)

    assert loaded is not None
    assert loaded.by_code["3001"].part is None


def test_load_parts_builds_and_reuses_the_index(tmp_path, monkeypatch) -> None:
    Parts.clear_cache()
    db_path = catalog_db_path(tmp_path)
    assert not db_path.exists()

    first = load_parts(PARTS_LST, tmp_path, build_index=True)
    assert first.get_entry_by_code("3005") is not None
    assert db_path.is_file()

    # The fast path must never run the categorization pass.
    def boom(self) -> None:
        message = "categorization must not run on the fast path"
        raise AssertionError(message)

    monkeypatch.setattr(Parts, "_categorize_parts", boom)
    Parts.clear_cache()
    second = load_parts(PARTS_LST, tmp_path)
    assert second.get_entry_by_code("3005") is not None
    assert list(second.catalog.by_code) == list(first.catalog.by_code)


def test_load_parts_without_build_index_leaves_no_file(tmp_path) -> None:
    Parts.clear_cache()

    parts = load_parts(PARTS_LST, tmp_path)

    assert parts.by_code  # cheap pass ran
    assert not catalog_db_path(tmp_path).exists()


def test_load_parts_swallows_save_failures(tmp_path) -> None:
    Parts.clear_cache()
    blocker = tmp_path / "generated"
    blocker.write_text("a file where the directory should be")

    parts = load_parts(PARTS_LST, blocker / "sub", build_index=True)

    assert parts.get_entry_by_code("3005") is not None


def test_catalog_db_path() -> None:
    assert catalog_db_path("/gen") == Path("/gen/catalog.sqlite")


def test_lazy_categorization_only_runs_on_catalog_access(monkeypatch) -> None:
    parts = Parts(PARTS_LST)
    assert parts.by_code  # parts.lst pass already done

    calls = {"count": 0}
    original = Parts._categorize_parts  # noqa: SLF001

    def counting(self) -> None:
        calls["count"] += 1
        original(self)

    monkeypatch.setattr(Parts, "_categorize_parts", counting)
    assert parts.part(code="3005") is not None  # no categorization needed
    assert calls["count"] == 0

    assert parts.get_entry_by_code("3005") is not None
    assert parts.entries_by_category(PartCategory.BRICK)
    assert calls["count"] == 1  # first catalog access, exactly once
